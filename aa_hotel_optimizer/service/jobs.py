"""Durable, bounded browser work. Every request has an expiring single-use lease."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select, update

from ..domain import Offer, SearchRequest, normalize_offer
from ..solver import SearchTooComplex, optimize
from .db import Connection, Quote, Search, Task, now
from .security import digest, fail, token

ACTIVE = ("queued", "running")
WARNINGS = [
    "Quotes are estimates, not reservations. Confirm the final price and eligible LP on AA Hotels.",
    "Separate reservations can require another check-in or a room change, even at the same hotel.",
    "Rewards are not guaranteed for no-shows. Confirm attendance and cancellation terms before booking.",
    "Use a starting LP balance for the qualification year being searched. Card spend and hotel rewards can post in different years; posting deadlines are not guaranteed.",
]


def add_task(db, search, kind, payload):
    db.add(Task(search_id=search.id, kind=kind, payload=payload))


def begin(db, search):
    for city in search.request["cities"]:
        add_task(db, search, "places", {"city": city})


def abort(db, search, code):
    search.status, search.error_code, search.finished_at = "failed", code, now()
    db.execute(
        update(Task)
        .where(Task.search_id == search.id, Task.status.in_(("pending", "leased")))
        .values(status="cancelled", lease_digest=None)
    )


def lease(db, connection, config):
    # The row lock serializes claims for this connection on PostgreSQL.
    connection = db.scalar(
        select(Connection).where(Connection.id == connection.id).with_for_update()
    )
    if connection.state != "connected":
        return None
    if connection.next_request_at and connection.next_request_at > now():
        return None
    tasks = db.scalars(
        select(Task)
        .join(Search)
        .where(
            Search.connection_id == connection.id,
            Search.status.in_(ACTIVE),
            Task.status.in_(("pending", "leased")),
        )
        .order_by(Task.created_at, Task.id)
    ).all()
    # One provider request at a time per connection, with server-enforced spacing.
    if any(t.status == "leased" and t.lease_until and t.lease_until > now() for t in tasks):
        return None
    for task in tasks:
        search = db.get(Search, task.search_id)
        if search.created_at < now() - timedelta(hours=2):
            abort(db, search, "search_expired")
            continue
        if task.attempts >= 3 or search.provider_calls + 2 > config.max_provider_calls:
            abort(db, search, "provider_limit")
            continue
        raw = token()
        task.status, task.lease_digest = "leased", digest(raw)
        task.lease_until = now() + timedelta(seconds=90)
        task.attempts += 1
        # Each task verifies the provider session before making its data request.
        search.provider_calls += 2
        search.status = "running"
        connection.next_request_at = now() + timedelta(seconds=2)
        db.commit()
        return {"id": task.id, "kind": task.kind, "payload": task.payload, "lease_token": raw}
    db.commit()
    return None


def finish_if_ready(db, search):
    db.flush()
    unfinished = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.search_id == search.id, Task.status.in_(("pending", "leased")))
    )
    if unfinished or search.status not in ACTIVE:
        return
    request = SearchRequest.model_validate(search.request)
    offers = [
        Offer.model_validate(q.data)
        for q in db.scalars(select(Quote).where(Quote.search_id == search.id))
    ]
    try:
        search.plans = [p.model_dump(mode="json") for p in optimize(offers, request)]
        search.status = "completed" if search.plans else "no_results"
        if request.mode == "status" and (request.objective != "cost" or request.max_overlaps > 1):
            search.warnings = search.warnings + [
                "This strategy ranks available offers; it does not guarantee the lowest total cost."
            ]
        if any(q.reward_basis == "provider_rewards" for q in offers):
            search.warnings = search.warnings + [
                "The provider's quoted rewards are used as estimated hotel LP. Promotional miles may not qualify; verify the breakdown at checkout."
            ]
    except SearchTooComplex:
        search.status, search.error_code = "failed", "search_too_complex"
    search.finished_at = now()


def accept(db, connection, task_id, result):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    search = db.get(Search, task.search_id) if task else None
    if not task or not search or search.connection_id != connection.id:
        fail(404, "not_found", "Task not found.")
    if (
        search.status not in ACTIVE
        or task.status != "leased"
        or not task.lease_until
        or task.lease_until < now()
        or task.lease_digest != digest(result.lease_token)
    ):
        fail(409, "lease_expired", "This task lease has expired or was already used.")
    task.lease_digest = None
    if result.status != "ok":
        task.status = "pending"
        if result.status in ("reauth_required", "browser_required"):
            connection.state = result.status
            task.attempts -= 1
        elif result.status == "rate_limited":
            connection.next_request_at = now() + timedelta(seconds=60)
        else:
            abort(db, search, "provider_unavailable")
        db.commit()
        return
    task.status = "done"
    request = SearchRequest.model_validate(search.request)
    payload, data = task.payload, result.data
    if task.kind == "places":
        places = data.get("places", [])
        if not isinstance(places, list) or len(places) > 50:
            abort(db, search, "provider_schema_changed")
        else:
            candidates = [
                p
                for p in places
                if isinstance(p, dict)
                and p.get("type") == "AGODA_CITY"
                and isinstance(p.get("id"), str)
                and 0 < len(p["id"]) <= 150
                and isinstance(p.get("name"), str)
            ]
            exact = [p for p in candidates if p["name"].casefold() == payload["city"].casefold()]
            candidates = exact or candidates
            if len(candidates) != 1:
                abort(db, search, "location_ambiguous" if candidates else "location_not_found")
                search.warnings = search.warnings + [
                    "Try a more specific city name, including the state or country."
                ]
            else:
                for start, end in request.intervals():
                    add_task(
                        db,
                        search,
                        "start",
                        {
                            "city": payload["city"],
                            "place_id": candidates[0]["id"],
                            "check_in": start.isoformat(),
                            "check_out": end.isoformat(),
                            "adults": request.adults,
                            "rooms": request.rooms,
                        },
                    )
    elif task.kind == "start":
        uuid = data.get("uuid")
        if (
            not isinstance(uuid, str)
            or not 1 <= len(uuid) <= 150
            or not all(c.isalnum() or c in "-_" for c in uuid)
        ):
            abort(db, search, "provider_schema_changed")
        else:
            add_task(db, search, "results", {**payload, "uuid": uuid, "page": 1})
    elif task.kind == "results":
        rows = data.get("results")
        if not isinstance(rows, list) or len(rows) > 100:
            abort(db, search, "provider_schema_changed")
        elif data.get("complete") is False:
            if task.attempts < 3:
                task.status = "pending"
                connection.next_request_at = now() + timedelta(seconds=5)
            else:
                abort(db, search, "provider_search_pending")
        else:
            start, end = (
                date.fromisoformat(payload["check_in"]),
                date.fromisoformat(payload["check_out"]),
            )
            existing = set(db.scalars(select(Quote.offer_id).where(Quote.search_id == search.id)))
            added, invalid = 0, 0
            for row in rows:
                offer = normalize_offer(row, payload["city"], start, end)
                if offer is None:
                    invalid += 1
                elif offer.id not in existing:
                    db.add(
                        Quote(
                            search_id=search.id,
                            offer_id=offer.id,
                            data=offer.model_dump(mode="json"),
                        )
                    )
                    existing.add(offer.id)
                    added += 1
            if (
                invalid
                and "Some invalid or unsupported quotes were excluded." not in search.warnings
            ):
                search.warnings = search.warnings + [
                    "Some invalid or unsupported quotes were excluded."
                ]
            # Stop at the first short page. A full repeated page is a schema failure,
            # never silently treated as a complete market search.
            if len(rows) >= 45:
                if payload["page"] >= 20 or not added:
                    abort(db, search, "pagination_limit")
                else:
                    add_task(db, search, "results", {**payload, "page": payload["page"] + 1})
    finish_if_ready(db, search)
    db.commit()


def describe(db, search):
    connection = db.get(Connection, search.connection_id) if search.connection_id else None
    status = search.status
    if status in ACTIVE:
        if not connection or connection.state != "connected":
            status = connection.state if connection else "browser_required"
        elif not connection.last_seen or connection.last_seen < now() - timedelta(seconds=90):
            status = "browser_required"
    counts = dict(
        db.execute(
            select(Task.status, func.count())
            .where(Task.search_id == search.id)
            .group_by(Task.status)
        ).all()
    )
    baseline = None
    if search.status == "completed" and search.request["mode"] == "trip":
        request = SearchRequest.model_validate(search.request)
        full_stay = [
            Offer.model_validate(q.data)
            for q in db.scalars(select(Quote).where(Quote.search_id == search.id))
            if q.data["check_in"] == search.request["check_in"]
            and q.data["check_out"] == search.request["check_out"]
        ]
        alternatives = optimize(full_stay, request)
        baseline = alternatives[0].model_dump(mode="json") if alternatives else None
    return {
        "id": search.id,
        "status": status,
        "error_code": search.error_code,
        "request": search.request,
        "plans": search.plans,
        "baseline": baseline,
        "warnings": search.warnings,
        "provider_calls": search.provider_calls,
        "progress": {"done": counts.get("done", 0), "total": sum(counts.values())},
        "created_at": search.created_at.isoformat() + "Z",
        "finished_at": search.finished_at.isoformat() + "Z" if search.finished_at else None,
        "action_url": "/?connect=1"
        if status in ("reauth_required", "browser_required", "pairing")
        else None,
    }
