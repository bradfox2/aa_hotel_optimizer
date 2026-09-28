"""Session-only transport for the shared planner on Streamlit Community Cloud.

This is not an account or payment server. No credentials or search results are
persisted, and nothing is shared between browser sessions. The standalone API
continues to own email, durable history, agent keys, the companion and billing.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import ValidationError

from . import main as provider
from .domain import Offer, SearchRequest, normalize_offer
from .legacy import parse_curl_command
from .service.demo import sample_offers
from .service.jobs import WARNINGS
from .solver import SearchTooComplex, optimize

MAX_ACTIVE = threading.BoundedSemaphore(3)
SESSION_SECONDS = 30 * 60


class PreviewError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


@dataclass
class SearchJob:
    request: SearchRequest
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    result: dict = field(default_factory=dict)
    deadline: float = field(default_factory=lambda: time.monotonic() + SESSION_SECONDS)

    def update(self, **values):
        with self.lock:
            self.result.update(values)

    def snapshot(self):
        with self.lock:
            return dict(self.result)

    def checkpoint(self):
        if self.cancelled.is_set():
            raise PreviewError("Search cancelled.")
        if time.monotonic() > self.deadline:
            raise PreviewError("This search expired. Try a smaller date window.")


def result_for(request: SearchRequest, offers: list[Offer], *, sample=False):
    plans = optimize(offers, request)
    baseline = (
        optimize(
            [
                q
                for q in offers
                if q.check_in == request.check_in and q.check_out == request.check_out
            ],
            request,
        )
        if request.mode == "trip"
        else []
    )
    return {
        "status": "completed",
        "sample": sample,
        "request": request.model_dump(mode="json"),
        "plans": [p.model_dump(mode="json") for p in plans],
        "baseline": baseline[0].model_dump(mode="json") if baseline else None,
        "warnings": (
            ["Fictional hotels and quotes. This example demonstrates how the comparison works."]
            if sample
            else [
                "The provider's quoted rewards are used as estimated hotel LP. Verify eligible LP before booking."
            ]
        )
        + WARNINGS,
    }


def collect_offers(job: SearchJob, headers: dict):
    """Use the existing fixed-host provider calls for every requested interval.

    Partial pagination must fail, rather than presenting incomplete results as
    an optimal plan. Each session has one worker and waits between intervals.
    """
    request = job.request
    offers = {}
    seen_pages = set()
    calls = done = 0
    total = len(request.cities) * len(request.intervals())
    invalid = 0

    def call(fn, *args, **kwargs):
        nonlocal calls
        job.checkpoint()
        calls += 1
        if calls > 1000:
            raise PreviewError(
                "This search needs too many provider requests. Use fewer cities or dates."
            )
        return fn(*args, **kwargs, session_headers=headers)

    for city in request.cities:
        places = call(provider.discover_place_ids, city)
        if not places:
            raise PreviewError(
                f"Could not find {city}. Check the city name and reconnect AA Hotels."
            )
        # Match the existing app: the provider's first relevant city is selected.
        location, place_id = places[0]
        for start, end in request.intervals():
            if done and job.cancelled.wait(2):
                job.checkpoint()
            check_in, check_out = start.strftime("%m/%d/%Y"), end.strftime("%m/%d/%Y")
            search_id = call(
                provider.search_aadvantage_hotels,
                check_in,
                check_out,
                location,
                place_id,
                adults=request.adults,
                rooms=request.rooms,
            )
            if not search_id:
                raise PreviewError(
                    "AA Hotels could not start this search. Reconnect your session and try again."
                )
            seen_pages.clear()
            for page in range(1, 21):
                data = call(
                    provider.get_hotel_results, search_id, location, check_in, page_number=page
                )
                if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                    raise PreviewError(
                        "AA Hotels did not return valid results. Reconnect and try again."
                    )
                if data.get("complete") is False:
                    raise PreviewError(
                        "AA Hotels has not finished returning results. Try again shortly."
                    )
                rows = data["results"]
                signature = json.dumps(rows, sort_keys=True)
                if rows and signature in seen_pages:
                    raise PreviewError("Could not verify every result page. Try a smaller search.")
                seen_pages.add(signature)
                for row in rows:
                    quote = normalize_offer(row, city, start, end)
                    if quote:
                        offers[quote.id] = quote
                    else:
                        invalid += 1
                if len(rows) < 45:
                    break
                if page == 20:
                    raise PreviewError(
                        "This search exceeded the result-page limit. Try a smaller search."
                    )
            done += 1
            job.update(progress={"done": done, "total": total})
    job.checkpoint()
    result = result_for(request, list(offers.values()))
    if invalid:
        result["warnings"].append("Some invalid or unsupported quotes were excluded.")
    return result


def run_job(job, headers):
    try:
        job.update(status="running")
        result = collect_offers(job, headers)
        job.checkpoint()
        job.update(**result)
    except (PreviewError, SearchTooComplex) as error:
        job.update(status="failed", error_message=str(error))
    except Exception:
        # Provider errors can contain tokens: do not print or return their text.
        job.update(
            status="failed",
            error_message="This comparison could not finish. Reconnect and try again.",
        )
    finally:
        if job.cancelled.is_set():
            job.update(status="cancelled", plans=[], baseline=None)
        headers.clear()
        MAX_ACTIVE.release()


class PreviewSession:
    def __init__(self):
        self.headers = {}
        self.connected_at = 0
        self.jobs: dict[str, SearchJob] = {}
        self.demo_times = deque(maxlen=20)
        self.expiry_timer = None

    def disconnect(self):
        if self.expiry_timer:
            self.expiry_timer.cancel()
            self.expiry_timer = None
        self.headers.clear()
        self.connected_at = 0
        for job in list(self.jobs.values()):
            if job.snapshot().get("status") in ("queued", "running"):
                job.cancelled.set()

    def handle(self, event):
        # A narrow dispatch table, not an arbitrary HTTP/ASGI tunnel.
        event_id = event.get("id") if isinstance(event, dict) else None
        try:
            if not isinstance(event, dict) or len(json.dumps(event)) > 100_000:
                raise PreviewError("Request is too large.")
            data = self.dispatch(event.get("path"), event.get("method", "GET"), event.get("body"))
            return {"id": event_id, "status": 200, "data": data}
        except ValidationError as error:
            message = error.errors(include_input=False, include_context=False)[0]["msg"]
            status = 422
        except (PreviewError, SearchTooComplex) as error:
            message, status = str(error), getattr(error, "status", 422)
        except Exception:
            message, status = "Unable to complete this request. Please try again.", 500
        return {"id": event_id, "status": status, "data": {"detail": {"message": message}}}

    def dispatch(self, path, method, body):
        if self.headers and time.monotonic() - self.connected_at > SESSION_SECONDS:
            self.disconnect()
        if (method, path) == ("GET", "/v1/config"):
            return {
                "deployment": "streamlit",
                "local_preview": False,
                "billing_enabled": False,
                "billing_test_mode": False,
                "email_enabled": False,
                "provider_enabled": True,
                "companion_url": "",
                "plan_price_label": "$19/month",
                "trip_pass_price_label": "$9",
                "trip_pass_searches": 20,
                "free_searches": 2,
                "paid_searches_per_month": 100,
                "popular_cities": [
                    "Phoenix, Arizona",
                    "Las Vegas, Nevada",
                    "Chicago, Illinois",
                    "Dallas, Texas",
                    "Miami, Florida",
                    "New York, New York",
                ],
            }
        if (method, path) == ("GET", "/v1/me"):
            return {
                "connection": {
                    "state": "connected" if self.headers else "disconnected",
                    "account_label": "Temporary session · expires after 30 minutes",
                }
            }
        if (method, path) == ("POST", "/v1/session/connection"):
            command = body.get("curl") if isinstance(body, dict) else None
            if not isinstance(command, str) or len(command) > 64000:
                raise PreviewError("Paste an AA Hotels cURL request, up to 64 KB.")
            try:
                url, headers = parse_curl_command(command)
                parsed = urlparse(url or "")
                if parsed.scheme != "https" or parsed.hostname != "www.aadvantagehotels.com":
                    raise ValueError()
                if not any(
                    k.lower() in ("cookie", "x-xsrf-token") and v for k, v in headers.items()
                ):
                    raise ValueError()
                headers = provider._safe_headers(headers)
            except ValueError:
                raise PreviewError(
                    "Use Copy as cURL (bash) on a signed-in AA Hotels search request."
                ) from None
            self.disconnect()
            self.headers, self.connected_at = headers, time.monotonic()
            self.expiry_timer = threading.Timer(SESSION_SECONDS, self.disconnect)
            self.expiry_timer.daemon = True
            self.expiry_timer.start()
            return {"ok": True}
        if (method, path) == ("DELETE", "/v1/session/connection"):
            self.disconnect()
            return {"ok": True}
        if method == "POST" and path in ("/v1/demo", "/v1/searches"):
            request = SearchRequest.model_validate(body)
            if path == "/v1/demo":
                if len(self.demo_times) == 20 and time.monotonic() - self.demo_times[0] < 60:
                    raise PreviewError("Please wait a minute before trying another example.", 429)
                if (
                    len(request.cities) > 2
                    or (request.check_out - request.check_in).days > 7
                    or request.max_hotel_changes > 1
                ):
                    raise PreviewError(
                        "Try the example with up to 7 nights, 2 cities, and 1 hotel change."
                    )
                self.demo_times.append(time.monotonic())
                return {"id": "sample", **result_for(request, sample_offers(request), sample=True)}
            if request.check_in < date.today():
                raise PreviewError("Choose today's date or a future check-in.")
            if not self.headers:
                raise PreviewError("Connect your AA Hotels session first.", 401)
            if any(j.snapshot().get("status") in ("running", "queued") for j in self.jobs.values()):
                raise PreviewError("Wait for your current search or cancel it first.", 409)
            if not MAX_ACTIVE.acquire(blocking=False):
                raise PreviewError("The preview is busy. Please try again in a minute.", 429)
            job = SearchJob(request, deadline=self.connected_at + SESSION_SECONDS)
            job.update(
                id=job.id,
                created_at=job.created_at,
                status="queued",
                request=request.model_dump(mode="json"),
                plans=[],
                progress={"done": 0, "total": len(request.intervals()) * len(request.cities)},
            )
            self.jobs[job.id] = job
            while len(self.jobs) > 10:
                del self.jobs[next(iter(self.jobs))]
            try:
                threading.Thread(
                    target=run_job, args=(job, self.headers.copy()), daemon=True
                ).start()
            except Exception:
                del self.jobs[job.id]
                MAX_ACTIVE.release()
                raise
            return job.snapshot()
        if (method, path) == ("GET", "/v1/searches"):
            return [job.snapshot() for job in reversed(list(self.jobs.values()))]
        if isinstance(path, str) and path.startswith("/v1/searches/"):
            parts = path.split("/")
            job = self.jobs.get(parts[3])
            if job:
                if method == "GET" and len(parts) == 4:
                    return job.snapshot()
                if method == "POST" and parts[4:] == ["cancel"]:
                    if job.snapshot().get("status") in ("queued", "running"):
                        job.cancelled.set()
                        job.update(status="cancelled")
                    return job.snapshot()
        raise PreviewError("This feature is not available in the Streamlit preview.", 404)
