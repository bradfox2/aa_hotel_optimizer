"""Session-only planner transport. AA credentials never reach Streamlit.

The browser companion performs provider requests in the signed-in AA Hotels tab.
The shared job engine leases bounded tasks and validates returned quotes. This
preview uses a separate in-memory database per Streamlit session, not accounts.
"""

from __future__ import annotations

import json
import time
import weakref
from collections import deque
from datetime import date
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .domain import SearchRequest
from .service import jobs
from .service.db import Base, Connection, Quote, Search, Task, User, now
from .service.demo import sample_offers
from .solver import SearchTooComplex, optimize


class PreviewError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


class BrowserResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "ok",
        "reauth_required",
        "browser_required",
        "rate_limited",
        "provider_error",
        "account_changed",
    ]
    account_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    account_label: str = Field(default="", max_length=60)
    data: dict = Field(default_factory=dict)
    lease_token: str = Field(default="", max_length=100)


def example(request):
    offers = sample_offers(request)
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
        "id": "sample",
        "status": "completed",
        "sample": True,
        "request": request.model_dump(mode="json"),
        "plans": [p.model_dump(mode="json") for p in plans],
        "baseline": baseline[0].model_dump(mode="json") if baseline else None,
        "warnings": [
            "Fictional hotels and quotes. This example demonstrates how the comparison works."
        ]
        + jobs.WARNINGS,
    }


class PreviewSession:
    VERSION = 3

    def __init__(self):
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        weakref.finalize(self, self.engine.dispose)
        self.demo_times = deque(maxlen=20)
        with self.sessions() as db:
            user = User(email=f"{uuid4().hex}@preview.invalid")
            db.add(user)
            db.flush()
            connection = Connection(user_id=user.id, state="disconnected")
            db.add(connection)
            db.commit()
            self.user_id, self.connection_id = user.id, connection.id

    def disconnect(self):
        with self.sessions() as db:
            connection = db.get(Connection, self.connection_id)
            connection.state = "disconnected"
            connection.account_fingerprint = None
            connection.account_label = ""
            for search in db.scalars(select(Search).where(Search.status.in_(jobs.ACTIVE))):
                jobs.abort(db, search, "connection_removed")
            db.commit()

    def handle(self, event):
        event_id = event.get("id") if isinstance(event, dict) else None
        try:
            if not isinstance(event, dict) or len(json.dumps(event)) > 1_000_000:
                raise PreviewError("Request is too large.")
            data = self.dispatch(event.get("path"), event.get("method", "GET"), event.get("body"))
            return {"id": event_id, "status": 200, "data": data}
        except ValidationError as error:
            message = error.errors(include_input=False, include_context=False)[0]["msg"]
            status = 422
        except HTTPException as error:
            message, status = error.detail.get("message", "Please try again."), error.status_code
        except (PreviewError, SearchTooComplex) as error:
            message, status = str(error), getattr(error, "status", 422)
        except Exception:
            message, status = "Unable to complete this request. Please try again.", 500
        return {"id": event_id, "status": status, "data": {"detail": {"message": message}}}

    def dispatch(self, path, method, body):
        if (method, path) == ("GET", "/v1/config"):
            return {
                "deployment": "streamlit",
                "preview_protocol": self.VERSION,
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
        if (method, path) == ("GET", "/v1/companion/download"):
            import base64

            from .companion_package import build_package

            return {
                "filename": "lp-optimizer-companion.zip",
                "base64": base64.b64encode(
                    build_package("https://aahoteloptimizer.streamlit.app")
                ).decode(),
            }
        if (method, path) == ("DELETE", "/v1/session/connection"):
            self.disconnect()
            return {"ok": True}
        with self.sessions() as db:
            connection = db.get(Connection, self.connection_id)
            if (method, path) == ("GET", "/v1/me"):
                return {
                    "connection": {
                        "state": connection.state,
                        "account_label": connection.account_label,
                    }
                }
            if (method, path) == ("POST", "/v1/session/connection"):
                result = BrowserResult.model_validate(body)
                if result.status != "ok" or not result.account_fingerprint:
                    connection.state = (
                        "reauth_required"
                        if result.status in ("reauth_required", "account_changed")
                        else "browser_required"
                    )
                    db.commit()
                    raise PreviewError(
                        "Open AA Hotels, sign in normally, then click Connect again."
                    )
                if (
                    connection.account_fingerprint
                    and connection.account_fingerprint != result.account_fingerprint
                ):
                    for search in db.scalars(select(Search).where(Search.status.in_(jobs.ACTIVE))):
                        jobs.abort(db, search, "connection_replaced")
                connection.state = "connected"
                connection.account_fingerprint = result.account_fingerprint
                connection.account_label = result.account_label
                connection.last_seen = now()
                db.commit()
                return {"ok": True}
            if method == "POST" and path in ("/v1/demo", "/v1/searches"):
                request = SearchRequest.model_validate(body)
                if path == "/v1/demo":
                    if len(self.demo_times) == 20 and time.monotonic() - self.demo_times[0] < 60:
                        raise PreviewError(
                            "Please wait a minute before trying another example.", 429
                        )
                    if (
                        len(request.cities) > 2
                        or (request.check_out - request.check_in).days > 7
                        or request.max_hotel_changes > 1
                    ):
                        raise PreviewError(
                            "Try the example with up to 7 nights, 2 cities, and 1 hotel change."
                        )
                    self.demo_times.append(time.monotonic())
                    return example(request)
                if request.check_in < date.today():
                    raise PreviewError("Choose today's date or a future check-in.")
                if connection.state != "connected":
                    raise PreviewError("Connect your AA Hotels browser first.", 401)
                if db.scalar(select(Search).where(Search.status.in_(jobs.ACTIVE))):
                    raise PreviewError("Wait for your current search or cancel it first.", 409)
                # Retain at most ten searches, with their normalized quotes only.
                old = db.scalars(select(Search).order_by(Search.created_at.desc()).offset(9)).all()
                for search in old:
                    db.execute(delete(Task).where(Task.search_id == search.id))
                    db.execute(delete(Quote).where(Quote.search_id == search.id))
                    db.delete(search)
                search = Search(
                    user_id=self.user_id,
                    connection_id=connection.id,
                    idempotency_key=uuid4().hex,
                    request=request.model_dump(mode="json"),
                    status="queued",
                    warnings=jobs.WARNINGS[:],
                    plans=[],
                )
                db.add(search)
                db.flush()
                jobs.begin(db, search)
                db.commit()
                return jobs.describe(db, search)
            if (method, path) == ("POST", "/v1/session/tasks/claim"):
                return {
                    "task": jobs.lease(db, connection, SimpleNamespace(max_provider_calls=1000))
                }
            if (
                method == "POST"
                and isinstance(path, str)
                and path.startswith("/v1/session/tasks/")
                and path.endswith("/result")
            ):
                result = BrowserResult.model_validate(body)
                task_id = path.split("/")[4]
                if result.status == "account_changed" or (
                    result.status == "ok"
                    and result.account_fingerprint != connection.account_fingerprint
                ):
                    connection.state = "reauth_required"
                    db.commit()
                    raise PreviewError(
                        "Your AA Hotels account changed. Click Connect to use the new account.", 409
                    )
                task = db.get(Task, task_id)
                if not task:
                    raise PreviewError("Task not found.", 404)
                if result.status == "ok":
                    connection.state, connection.last_seen = "connected", now()
                jobs.accept(db, connection, task_id, result)
                return jobs.describe(db, db.get(Search, task.search_id))
            if (method, path) == ("GET", "/v1/searches"):
                return [
                    jobs.describe(db, s)
                    for s in db.scalars(select(Search).order_by(Search.created_at.desc()))
                ]
            if isinstance(path, str) and path.startswith("/v1/searches/"):
                parts = path.split("/")
                search = db.get(Search, parts[3])
                if search:
                    if method == "GET" and len(parts) == 4:
                        return jobs.describe(db, search)
                    if method == "POST" and parts[4:] == ["cancel"]:
                        if search.status in jobs.ACTIVE:
                            jobs.abort(db, search, "cancelled")
                            search.status = "cancelled"
                            db.commit()
                        return jobs.describe(db, search)
        raise PreviewError("This feature is not available in the Streamlit preview.", 404)
