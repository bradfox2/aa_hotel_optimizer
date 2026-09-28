import io
import json
from datetime import date, timedelta
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from aa_hotel_optimizer import streamlit_runtime as runtime
from aa_hotel_optimizer.companion_package import build_package
from aa_hotel_optimizer.domain import SearchRequest
from aa_hotel_optimizer.service.db import Connection, Quote, Search, now

ACCOUNT = {"status": "ok", "account_fingerprint": "a" * 64, "account_label": "Example", "data": {}}


def request(**kwargs):
    start = date.today() + timedelta(days=28)
    return SearchRequest(
        cities=["Phoenix"], check_in=start, check_out=start + timedelta(days=2), **kwargs
    )


def call(session, path, method="GET", body=None):
    return session.handle({"id": "test", "path": path, "method": method, "body": body})


@pytest.fixture
def session():
    value = runtime.PreviewSession()
    yield value
    value.disconnect()
    value.engine.dispose()


def connect(session):
    assert call(session, "/v1/session/connection", "POST", ACCOUNT)["status"] == 200


def claim(session):
    # Avoid sleeping in unit tests; production leases enforce spacing.
    with session.sessions() as db:
        db.get(Connection, session.connection_id).next_request_at = now()
        db.commit()
    return call(session, "/v1/session/tasks/claim", "POST", {})["data"]["task"]


def submit(session, task, data=None, **override):
    return call(
        session,
        f"/v1/session/tasks/{task['id']}/result",
        "POST",
        {**ACCOUNT, "lease_token": task["lease_token"], "data": data or {}, **override},
    )


def test_preview_is_explicit_and_uses_shared_optimizer(session):
    config = call(session, "/v1/config")["data"]
    assert config["deployment"] == "streamlit"
    assert not config["billing_enabled"] and not config["email_enabled"]
    result = call(session, "/v1/demo", "POST", request().model_dump(mode="json"))["data"]
    assert result["sample"] and result["plans"][0]["booking_count"] == 2
    assert result["plans"][0]["earned_lp"] > result["baseline"]["earned_lp"]
    assert not call(session, "/v1/searches")["data"]


def test_browser_connection_is_isolated_and_rejects_curl(session):
    connect(session)
    other = runtime.PreviewSession()
    assert call(other, "/v1/me")["data"]["connection"]["state"] == "disconnected"
    result = call(session, "/v1/session/connection", "POST", {"curl": "sensitive-request"})
    assert result["status"] == 422 and "sensitive-request" not in json.dumps(result)
    assert not hasattr(session, "headers")
    assert call(session, "/v1/auth/link", "POST", {"email": "test@example.com"})["status"] == 404
    assert call(session, "/v1/billing/checkout", "POST", {})["status"] == 404
    call(session, "/v1/session/connection", "DELETE")
    assert call(session, "/v1/me")["data"]["connection"]["state"] == "disconnected"
    other.engine.dispose()


@pytest.mark.parametrize(
    "reply",
    [
        {"status": "browser_required"},
        {"status": "reauth_required"},
        {"status": "ok"},
        {**ACCOUNT, "cookie": "DO-NOT-EXPORT"},
        {**ACCOUNT, "account_fingerprint": "invalid"},
    ],
)
def test_unusable_or_secret_bearing_connect_payloads_fail(session, reply):
    result = call(session, "/v1/session/connection", "POST", reply)
    assert result["status"] == 422 and "DO-NOT-EXPORT" not in json.dumps(result)
    assert call(session, "/v1/me")["data"]["connection"]["state"] != "connected"


def test_browser_tasks_cover_whole_and_split_stays_and_validate_leases(session):
    connect(session)
    created = call(
        session, "/v1/searches", "POST", request(adults=2, rooms=2).model_dump(mode="json")
    )["data"]
    places = claim(session)
    result = submit(
        session, places, {"places": [{"id": "city", "name": "Phoenix", "type": "AGODA_CITY"}]}
    )
    assert result["status"] == 200
    assert submit(session, places)["status"] == 409
    intervals = []
    while task := claim(session):
        if task["kind"] == "start":
            p = task["payload"]
            assert p["adults"] == 2 and p["rooms"] == 2
            intervals.append((p["check_in"], p["check_out"]))
            data = {"uuid": "fixture"}
        else:
            p = task["payload"]
            nights = (date.fromisoformat(p["check_out"]) - date.fromisoformat(p["check_in"])).days
            data = {
                "results": [
                    {
                        "hotel": {"id": "hotel", "name": "Fixture Hotel"},
                        "grandTotalPublishedPriceInclusiveWithFees": {"amount": 100 * nights},
                        "rewards": 4000 if nights == 1 else 3000,
                    }
                ]
            }
        assert submit(session, task, data)["status"] == 200
    assert len(set(intervals)) == 3
    result = call(session, f"/v1/searches/{created['id']}")["data"]
    assert result["status"] == "completed"
    assert result["plans"][0]["earned_lp"] == 8000
    assert result["baseline"]["earned_lp"] == 3000
    assert not claim(session)


def test_account_change_cannot_return_another_accounts_quotes(session):
    connect(session)
    created = call(session, "/v1/searches", "POST", request().model_dump(mode="json"))["data"]
    task = claim(session)
    result = submit(session, task, account_fingerprint="b" * 64)
    assert result["status"] == 409
    assert call(session, "/v1/searches/" + created["id"])["data"]["status"] == "reauth_required"
    assert not claim(session)
    with session.sessions() as db:
        assert not list(db.scalars(select(Quote)))


def test_disconnect_cancels_search_and_late_result_is_rejected(session):
    connect(session)
    created = call(session, "/v1/searches", "POST", request().model_dump(mode="json"))["data"]
    task = claim(session)
    call(session, "/v1/session/connection", "DELETE")
    assert submit(session, task)["status"] == 409
    with session.sessions() as db:
        assert db.get(Search, created["id"]).status == "failed"
    other = runtime.PreviewSession()
    assert call(other, "/v1/searches/" + created["id"])["status"] == 404
    other.engine.dispose()


def test_validation_and_connection_are_required(session):
    body = request().model_dump(mode="json")
    assert call(session, "/v1/searches", "POST", body)["status"] == 401
    body["check_out"] = body["check_in"]
    assert call(session, "/v1/demo", "POST", body)["status"] == 422
    assert session.handle({"body": "x" * 1000001})["status"] == 422


def test_package_is_bound_to_public_origin_and_includes_streamlit_frames():
    with ZipFile(io.BytesIO(build_package("https://aahoteloptimizer.streamlit.app"))) as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["version"] == "0.3.0"
        assert manifest["content_scripts"][0]["all_frames"]
        assert manifest["content_scripts"][0]["matches"] == [
            "https://aahoteloptimizer.streamlit.app/*"
        ]
        assert b"127.0.0.1" not in package.read("config.js")
        assert b"PREVIEW_CONNECT" in package.read("background.js")
