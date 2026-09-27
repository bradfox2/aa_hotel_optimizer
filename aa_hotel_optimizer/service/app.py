from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import stripe
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..domain import Plan, SearchRequest
from ..solver import SearchTooComplex, optimize
from . import billing, entitlements, jobs
from .config import Settings, settings
from .db import Connection, Credential, LoginToken, Search, Task, User, database, now
from .demo import sample_offers
from .security import (
    AGENT_SCOPES,
    COOKIE,
    digest,
    email_link,
    fail,
    identity,
    paid,
    rate_limit,
    token,
)

logger = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmailInput(Input):
    email: EmailStr


class TokenInput(Input):
    token: str = Field(min_length=20, max_length=100)


class KeyInput(Input):
    label: str = Field(default="My agent", min_length=1, max_length=80)
    scopes: list[Literal["search:read", "search:write"]] = Field(
        default=["search:read", "search:write"], min_length=1, max_length=2
    )


class Heartbeat(Input):
    state: Literal["connected", "reauth_required", "browser_required"]
    account_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    account_label: str = Field(default="", max_length=100)


class TaskResult(Input):
    lease_token: str = Field(min_length=20, max_length=100)
    status: Literal["ok", "reauth_required", "browser_required", "rate_limited", "provider_error"]
    data: dict = Field(default_factory=dict)


class DeleteAccount(Input):
    confirmation: Literal["delete my account"]


class CheckoutInput(Input):
    product: Literal["membership", "trip_pass"] = "membership"


class SearchResponse(BaseModel):
    id: str
    status: Literal[
        "queued",
        "running",
        "completed",
        "no_results",
        "failed",
        "cancelled",
        "pairing",
        "browser_required",
        "reauth_required",
    ]
    request: SearchRequest
    plans: list[Plan] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    baseline: Plan | None = None
    sample: bool = False
    error_code: str | None = None
    progress: dict[str, int] = Field(default_factory=dict)
    provider_calls: int = 0
    created_at: str | None = None
    finished_at: str | None = None
    action_url: str | None = None


class BodyLimit:
    """Bound actual streamed bytes too, not just the untrusted Content-Length."""

    def __init__(self, app, maximum=1_000_000):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.maximum:
                return await JSONResponse(
                    {"detail": {"code": "body_too_large", "message": "Request too large."}}, 413
                )(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        used = False

        async def replay():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(config: Settings | None = None):
    config = config or settings()
    config.validate_deployment()
    engine, sessions = database(config.database_url, initialize=not config.production)
    app = FastAPI(
        title="LP Optimizer API",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        description="Create and poll hotel LP searches. Scoped bearer keys are created in the app. "
        "Live searches require the account owner's connected browser.",
    )
    app.state.config, app.state.sessions, app.state.engine = config, sessions, engine
    app.add_middleware(BodyLimit)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(config.public_url).hostname])

    @app.middleware("http")
    async def protection(request, call_next):
        path = request.url.path
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            bearer = request.headers.get("authorization", "").startswith("Bearer ")
            webhook = path == "/v1/billing/webhook"
            if (
                not webhook
                and not bearer
                and request.headers.get("origin", "").rstrip("/") != config.public_url.rstrip("/")
            ):
                return JSONResponse(
                    {
                        "detail": {
                            "code": "invalid_origin",
                            "message": "Open the app in its original tab and try again.",
                        }
                    },
                    403,
                )
            if not webhook and not request.headers.get("content-type", "").startswith(
                "application/json"
            ):
                return JSONResponse(
                    {"detail": {"code": "json_required", "message": "Send a JSON request."}}, 415
                )
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        if config.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "detail": {
                    "code": "invalid_request",
                    "message": "Check the highlighted search details.",
                    "issues": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                        for e in exc.errors()
                    ],
                }
            },
            422,
        )

    @app.exception_handler(stripe.StripeError)
    async def stripe_error(request, exc):
        logger.warning("Billing request failed: %s", type(exc).__name__)
        return JSONResponse(
            {
                "detail": {
                    "code": "billing_unavailable",
                    "message": "Billing is temporarily unavailable. Please try again.",
                }
            },
            502,
        )

    @app.exception_handler(Exception)
    async def unknown_error(request, exc):
        logger.error("Request failed: %s", type(exc).__name__)
        return JSONResponse(
            {
                "detail": {
                    "code": "server_error",
                    "message": "Something went wrong. Please try again.",
                }
            },
            500,
        )

    def ip(request):
        # Proxy headers are accepted only from explicitly trusted upstreams by Uvicorn.
        return request.client.host if request.client else "unknown"

    def owned(db, user, search_id):
        search = db.scalar(select(Search).where(Search.id == search_id, Search.user_id == user.id))
        if not search:
            fail(404, "not_found", "Search not found.")
        return search

    def connection_for(db, user):
        return db.scalar(
            select(Connection)
            .where(Connection.user_id == user.id)
            .order_by(Connection.created_at.desc())
        )

    def describe_connection(connection):
        if not connection:
            return {"state": "not_connected"}
        state = connection.state
        if state == "connected" and (
            not connection.last_seen or connection.last_seen < now() - timedelta(seconds=90)
        ):
            state = "browser_required"
        return {"id": connection.id, "state": state, "account_label": connection.account_label}

    def bridge(request, db):
        authorization = request.headers.get("authorization", "")
        raw = authorization[7:] if authorization.startswith("Bearer ") else ""
        connection = (
            db.scalar(
                select(Connection).where(
                    Connection.bridge_digest == digest(raw), Connection.bridge_expires > now()
                )
            )
            if raw
            else None
        )
        if not connection:
            fail(401, "connection_expired", "Reconnect the browser companion from the app.")
        return connection

    def usage(db, user):
        return entitlements.usage(config, db, user)

    @app.get("/health", include_in_schema=False)
    def health():
        with sessions() as db:
            db.scalar(select(func.count()).select_from(User))
        return {"status": "ok"}

    @app.get("/v1/config")
    def public_config():
        return {
            "name": config.app_name,
            "local_preview": not config.production,
            "billing_enabled": config.billing_enabled,
            "billing_test_mode": config.test_billing,
            "email_enabled": config.email_enabled,
            "invite_only": bool(config.beta_emails),
            "provider_enabled": config.provider_enabled,
            "companion_url": config.companion_url,
            "plan_label": config.plan_label,
            "plan_price_label": config.plan_price_label,
            "trip_pass_price_label": config.trip_pass_price_label,
            "trip_pass_searches": config.trip_pass_searches,
            "free_searches": config.free_searches,
            "paid_searches_per_month": config.paid_searches_per_month,
            "popular_cities": [
                "New York, New York",
                "Los Angeles, California",
                "Chicago, Illinois",
                "Houston, Texas",
                "Phoenix, Arizona",
                "Philadelphia, Pennsylvania",
                "San Antonio, Texas",
                "San Diego, California",
                "Dallas, Texas",
                "San Jose, California",
                "Austin, Texas",
                "Jacksonville, Florida",
                "Fort Worth, Texas",
                "Columbus, Ohio",
                "Charlotte, North Carolina",
                "San Francisco, California",
                "Indianapolis, Indiana",
                "Seattle, Washington",
                "Denver, Colorado",
                "Washington, District of Columbia",
                "Boston, Massachusetts",
                "Nashville, Tennessee",
                "Las Vegas, Nevada",
                "Portland, Oregon",
                "Atlanta, Georgia",
                "Miami, Florida",
            ],
        }

    @app.post("/v1/auth/link")
    def login_link(body: EmailInput, request: Request):
        email = str(body.email).lower()
        if config.production and not config.email_enabled:
            fail(503, "email_unavailable", "Sign-in is being set up. You can explore the example.")
        allowed = {e.strip().lower() for e in config.beta_emails.split(",") if e.strip()}
        if allowed and email not in allowed:
            fail(403, "invite_required", "This beta is currently open to invited email addresses.")
        with sessions() as db:
            rate_limit(db, "login-ip:" + ip(request), 10, 900)
            rate_limit(db, "login-email:" + email, 3, 900)
            raw = token()
            db.execute(delete(LoginToken).where(LoginToken.email == email))
            db.add(
                LoginToken(
                    digest=digest(raw), email=email, expires_at=now() + timedelta(minutes=15)
                )
            )
            db.commit()
            link = config.public_url + "/#login=" + raw
            if config.email_enabled:
                try:
                    email_link(config, email, link)
                except Exception as exc:
                    logger.warning("Sign-in delivery failed: %s", type(exc).__name__)
                    fail(
                        503,
                        "email_unavailable",
                        "Email delivery is temporarily unavailable. Please try again.",
                    )
            elif not config.production:
                return {
                    "message": "Local preview: use this link to sign in.",
                    "development_link": link,
                }
        return {"message": "Check your email for a sign-in link. It expires in 15 minutes."}

    @app.post("/v1/auth/consume")
    def consume(body: TokenInput, request: Request, response: Response):
        with sessions() as db:
            rate_limit(db, "consume:" + ip(request), 30, 900)
            # DELETE RETURNING makes a link single-use even with concurrent requests.
            email = db.execute(
                delete(LoginToken)
                .where(LoginToken.digest == digest(body.token), LoginToken.expires_at > now())
                .returning(LoginToken.email)
            ).scalar_one_or_none()
            if not email:
                fail(
                    401,
                    "link_expired",
                    "This link has expired or was already used. Request another.",
                )
            user = db.scalar(select(User).where(User.email == email))
            if not user:
                user = User(email=email)
                db.add(user)
                db.flush()
            raw = token()
            db.add(
                Credential(
                    user_id=user.id,
                    digest=digest(raw),
                    kind="session",
                    expires_at=now() + timedelta(days=config.session_days),
                )
            )
            db.commit()
            response.set_cookie(
                COOKIE,
                raw,
                max_age=config.session_days * 86400,
                secure=config.production,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return {"signed_in": True}

    @app.post("/v1/auth/logout")
    def logout(request: Request, response: Response):
        with sessions() as db:
            _, credential = identity(request, db, session_only=True)
            db.delete(credential)
            db.commit()
        response.delete_cookie(COOKIE, path="/")
        return {"signed_out": True}

    @app.get("/v1/me")
    def me(request: Request):
        with sessions() as db:
            user, _ = identity(request, db)
            return {
                "id": user.id,
                "email": user.email,
                "paid": paid(user),
                "usage": usage(db, user),
                "subscription_status": user.subscription_status,
                "cancel_at_period_end": user.cancel_at_period_end,
                "billing_action": "portal"
                if user.subscription_id
                and user.subscription_status
                in ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")
                else "checkout",
                "connection": describe_connection(connection_for(db, user)),
            }

    @app.get("/v1/me/export")
    def export_account(request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            return {
                "email": user.email,
                "created_at": user.created_at.isoformat() + "Z",
                "searches": [
                    jobs.describe(db, search)
                    for search in db.scalars(select(Search).where(Search.user_id == user.id))
                ],
            }

    @app.delete("/v1/me")
    def delete_account(body: DeleteAccount, request: Request, response: Response):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            if user.subscription_id and user.subscription_status not in (
                "canceled",
                "incomplete_expired",
                "inactive",
                "free",
            ):
                api = billing.client(config)
                subscription = api.v1.subscriptions.retrieve(user.subscription_id)
                if subscription.status != "canceled":
                    api.v1.subscriptions.cancel(
                        user.subscription_id, options={"idempotency_key": "delete-" + user.id}
                    )
            db.execute(delete(LoginToken).where(LoginToken.email == user.email))
            db.delete(user)
            db.commit()
        response.delete_cookie(COOKIE, path="/")
        return {"deleted": True}

    @app.get("/v1/keys")
    def keys(request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            return [
                {
                    "id": k.id,
                    "label": k.label,
                    "scopes": k.scopes,
                    "expires_at": k.expires_at.isoformat() + "Z",
                }
                for k in db.scalars(
                    select(Credential).where(
                        Credential.user_id == user.id,
                        Credential.kind == "agent",
                        Credential.expires_at > now(),
                    )
                )
            ]

    @app.post("/v1/keys", status_code=201)
    def create_key(body: KeyInput, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            rate_limit(db, "keys:" + user.id, 10, 3600)
            raw = "lp_agent_" + token()
            credential = Credential(
                user_id=user.id,
                digest=digest(raw),
                kind="agent",
                label=body.label,
                scopes=sorted(set(body.scopes) & AGENT_SCOPES),
                expires_at=now() + timedelta(days=90),
            )
            db.add(credential)
            db.commit()
            return {
                "id": credential.id,
                "key": raw,
                "expires_at": credential.expires_at.isoformat() + "Z",
            }

    @app.delete("/v1/keys/{key_id}")
    def revoke_key(key_id: str, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            db.execute(
                delete(Credential).where(
                    Credential.id == key_id,
                    Credential.user_id == user.id,
                    Credential.kind == "agent",
                )
            )
            db.commit()
        return {"revoked": True}

    @app.post("/v1/connections")
    def connect(request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            rate_limit(db, "connect:" + user.id, 10, 900)
            connection = connection_for(db, user)
            if not connection:
                connection = Connection(user_id=user.id)
                db.add(connection)
            raw = token()
            connection.pair_digest, connection.pair_expires = (
                digest(raw),
                now() + timedelta(minutes=5),
            )
            connection.state = "pairing"
            connection.bridge_digest = None
            connection.account_fingerprint, connection.account_label = None, ""
            for active in db.scalars(
                select(Search).where(
                    Search.connection_id == connection.id, Search.status.in_(jobs.ACTIVE)
                )
            ):
                jobs.abort(db, active, "connection_replaced")
            db.commit()
            return {"connection_id": connection.id, "pairing_token": raw, "expires_in": 300}

    @app.delete("/v1/connections/{connection_id}")
    def disconnect(connection_id: str, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            connection = db.scalar(
                select(Connection).where(
                    Connection.id == connection_id, Connection.user_id == user.id
                )
            )
            if not connection:
                fail(404, "not_found", "Connection not found.")
            connection.state, connection.bridge_digest, connection.pair_digest = (
                "browser_required",
                None,
                None,
            )
            connection.account_fingerprint, connection.account_label = None, ""
            for search in db.scalars(
                select(Search).where(
                    Search.connection_id == connection.id, Search.status.in_(jobs.ACTIVE)
                )
            ):
                jobs.abort(db, search, "connection_removed")
            db.commit()
        return {"disconnected": True}

    @app.post("/v1/bridge/pair")
    def pair(body: TokenInput, request: Request):
        with sessions() as db:
            rate_limit(db, "pair:" + ip(request), 20, 900)
            connection = db.scalar(
                select(Connection)
                .where(
                    Connection.pair_digest == digest(body.token), Connection.pair_expires > now()
                )
                .with_for_update()
            )
            if not connection:
                fail(401, "pairing_expired", "Start connecting again from the app.")
            raw = "lp_bridge_" + token()
            connection.bridge_digest, connection.bridge_expires = (
                digest(raw),
                now() + timedelta(days=30),
            )
            connection.pair_digest, connection.pair_expires, connection.state = (
                None,
                None,
                "browser_required",
            )
            db.commit()
            return {"bridge_key": raw, "connection_id": connection.id}

    @app.post("/v1/bridge/heartbeat")
    def heartbeat(body: Heartbeat, request: Request):
        with sessions() as db:
            connection = bridge(request, db)
            if body.state == "connected" and not body.account_fingerprint:
                fail(422, "account_required", "Sign in to AA Hotels first.")
            if (
                connection.account_fingerprint
                and body.account_fingerprint
                and connection.account_fingerprint != body.account_fingerprint
            ):
                connection.state = "reauth_required"
                db.commit()
                fail(
                    409,
                    "account_changed",
                    "The AA account changed. Reconnect from the app to confirm it.",
                )
            connection.state, connection.last_seen = body.state, now()
            if body.account_fingerprint:
                connection.account_fingerprint, connection.account_label = (
                    body.account_fingerprint,
                    body.account_label,
                )
            db.commit()
            return {"state": connection.state}

    @app.post("/v1/bridge/tasks/claim")
    def claim(request: Request):
        with sessions() as db:
            connection = bridge(request, db)
            if not config.provider_enabled:
                return {"task": None, "retry_after": 30}
            return {"task": jobs.lease(db, connection, config), "retry_after": 3}

    @app.post("/v1/bridge/tasks/{task_id}/result")
    def task_result(task_id: str, body: TaskResult, request: Request):
        with sessions() as db:
            connection = bridge(request, db)
            jobs.accept(db, connection, task_id, body)
        return {"accepted": True}

    @app.post("/v1/demo", response_model=SearchResponse)
    def demo(body: SearchRequest, request: Request):
        if (
            len(body.cities) > 2
            or (body.check_out - body.check_in).days > 7
            or body.max_hotel_changes > 1
        ):
            fail(
                422,
                "sample_limit",
                "Try the example with up to 7 nights, 2 cities, and 1 hotel change.",
            )
        with sessions() as db:
            rate_limit(db, "demo:" + ip(request), 20, 60)
        try:
            offers = sample_offers(body)
            plans = optimize(offers, body)
        except SearchTooComplex:
            fail(422, "search_too_complex", "Try fewer nights or one hotel.")
        baseline = (
            optimize(
                [
                    q
                    for q in offers
                    if q.check_in == body.check_in and q.check_out == body.check_out
                ],
                body,
            )
            if body.mode == "trip"
            else []
        )
        return {
            "id": "sample",
            "status": "completed",
            "sample": True,
            "request": body.model_dump(mode="json"),
            "plans": [p.model_dump(mode="json") for p in plans],
            "baseline": baseline[0].model_dump(mode="json") if baseline else None,
            "warnings": [
                "Fictional hotels and quotes. This example demonstrates how the comparison works."
            ]
            + jobs.WARNINGS,
        }

    @app.post("/v1/searches", status_code=202, response_model=SearchResponse)
    def create_search(body: SearchRequest, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, "search:write")
            key = request.headers.get("idempotency-key", "")
            if not 8 <= len(key) <= 120:
                fail(
                    422,
                    "idempotency_key_required",
                    "Send a unique Idempotency-Key header (8–120 characters).",
                )
            previous = db.scalar(
                select(Search).where(Search.user_id == user.id, Search.idempotency_key == key)
            )
            if previous:
                if previous.request != body.model_dump(mode="json"):
                    fail(409, "idempotency_conflict", "Use a new key for a different search.")
                return jobs.describe(db, previous)
            if not config.provider_enabled:
                fail(
                    503,
                    "live_search_unavailable",
                    "Live searches are not enabled in this preview. Try the example.",
                )
            if body.check_in < date.today():
                fail(422, "past_dates", "Choose a future stay.")
            if body.mode == "status" and body.starting_lp >= body.target_lp:
                fail(
                    422,
                    "goal_already_met",
                    "Your balance already meets this goal. Choose a higher target.",
                )
            rate_limit(db, "search-create:" + user.id, 10, 3600)
            # Serialize entitlement and concurrent-search checks per account.
            user = db.scalar(select(User).where(User.id == user.id).with_for_update())
            previous = db.scalar(
                select(Search).where(Search.user_id == user.id, Search.idempotency_key == key)
            )
            if previous:
                if previous.request != body.model_dump(mode="json"):
                    fail(409, "idempotency_conflict", "Use a new key for a different search.")
                return jobs.describe(db, previous)
            allowance = usage(db, user)
            if not allowance["remaining"]:
                fail(
                    402,
                    "search_limit",
                    "You have used your included searches. Choose a trip pass or membership to continue.",
                )
            if db.scalar(
                select(Search.id).where(Search.user_id == user.id, Search.status.in_(jobs.ACTIVE))
            ):
                fail(409, "search_in_progress", "Finish or cancel your current search first.")
            connection = connection_for(db, user)
            if describe_connection(connection)["state"] != "connected":
                fail(
                    409, "connection_required", "Connect AA Hotels and keep its tab open to search."
                )
            search = Search(
                user_id=user.id,
                connection_id=connection.id,
                idempotency_key=key,
                **entitlements.allocate(allowance),
                request=body.model_dump(mode="json"),
                warnings=jobs.WARNINGS[:],
            )
            db.add(search)
            db.flush()
            jobs.begin(db, search)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                fail(409, "search_conflict", "Refresh your searches before trying again.")
            return jobs.describe(db, search)

    @app.get("/v1/searches")
    def list_searches(request: Request):
        with sessions() as db:
            user, _ = identity(request, db)
            return [
                {
                    "id": s.id,
                    "status": s.status,
                    "request": s.request,
                    "created_at": s.created_at.isoformat() + "Z",
                }
                for s in db.scalars(
                    select(Search)
                    .where(Search.user_id == user.id)
                    .order_by(Search.created_at.desc())
                    .limit(50)
                )
            ]

    @app.get("/v1/searches/{search_id}", response_model=SearchResponse)
    def get_search(search_id: str, request: Request):
        with sessions() as db:
            user, _ = identity(request, db)
            return jobs.describe(db, owned(db, user, search_id))

    @app.post("/v1/searches/{search_id}/cancel", response_model=SearchResponse)
    def cancel_search(search_id: str, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, "search:write")
            search = owned(db, user, search_id)
            if search.status in jobs.ACTIVE:
                search.status, search.finished_at = "cancelled", now()
                db.execute(
                    update(Task)
                    .where(Task.search_id == search.id, Task.status.in_(("pending", "leased")))
                    .values(status="cancelled", lease_digest=None)
                )
                db.commit()
            return jobs.describe(db, search)

    @app.post("/v1/billing/checkout")
    def checkout(body: CheckoutInput, request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            rate_limit(db, "checkout:" + user.id, 5, 600)
            return billing.checkout(config, db, user, body.product)

    @app.post("/v1/billing/portal")
    def portal(request: Request):
        with sessions() as db:
            user, _ = identity(request, db, session_only=True)
            return billing.portal(config, user)

    @app.post("/v1/billing/webhook", include_in_schema=False)
    async def webhook(request: Request):
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")

        def process():
            with sessions() as db:
                return billing.webhook(config, db, payload, signature)

        return await run_in_threadpool(process)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def schema():
        if app.openapi_schema:
            return app.openapi_schema
        document = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            servers=[{"url": config.public_url}],
        )
        document.setdefault("components", {})["securitySchemes"] = {
            "AgentKey": {
                "type": "http",
                "scheme": "bearer",
                "description": "Revocable key with search:read and/or search:write scopes.",
            },
            "AppSession": {"type": "apiKey", "in": "cookie", "name": COOKIE},
            "BrowserBridge": {
                "type": "http",
                "scheme": "bearer",
                "description": "Connection-scoped browser companion key. Not an agent key.",
            },
        }
        public = {"/v1/config", "/v1/demo", "/v1/auth/link", "/v1/auth/consume", "/v1/bridge/pair"}
        for path, methods in document["paths"].items():
            for operation in methods.values():
                if path in public:
                    continue
                if path.startswith("/v1/bridge/"):
                    operation["security"] = [{"BrowserBridge": []}]
                elif path.startswith("/v1/searches") or path == "/v1/me":
                    operation["security"] = [{"AgentKey": []}, {"AppSession": []}]
                else:
                    operation["security"] = [{"AppSession": []}]
        # Account deletion is deliberately unavailable to agent keys.
        document["paths"]["/v1/me"]["delete"]["security"] = [{"AppSession": []}]
        document["paths"]["/v1/searches"]["post"].setdefault("parameters", []).append(
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "description": "A unique ID for this search. Reuse with the same body when retrying.",
                "schema": {"type": "string", "minLength": 8, "maxLength": 120},
            }
        )
        app.openapi_schema = document
        return document

    app.openapi = schema
    return app
