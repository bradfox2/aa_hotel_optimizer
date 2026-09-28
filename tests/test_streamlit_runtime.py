import json
import threading
from datetime import date, timedelta

import pytest

from aa_hotel_optimizer import streamlit_runtime as runtime
from aa_hotel_optimizer.domain import SearchRequest

FIXTURE_CURL = "curl 'https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest' -H 'Cookie: fixture-only-secret'"


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


def test_preview_is_explicit_and_uses_shared_optimizer(session):
    config = call(session, "/v1/config")["data"]
    assert config["deployment"] == "streamlit"
    assert not config["billing_enabled"] and not config["email_enabled"]
    result = call(session, "/v1/demo", "POST", request().model_dump(mode="json"))["data"]
    assert result["sample"] and result["plans"][0]["booking_count"] == 2
    assert result["plans"][0]["earned_lp"] > result["baseline"]["earned_lp"]
    assert not call(session, "/v1/searches")["data"]


def test_credentials_stay_in_the_owning_session(session):
    reply = call(session, "/v1/session/connection", "POST", {"curl": FIXTURE_CURL})
    assert reply["status"] == 200
    assert "fixture-only-secret" not in json.dumps(reply)
    assert session.headers["Cookie"] == "fixture-only-secret"
    assert call(runtime.PreviewSession(), "/v1/me")["data"]["connection"]["state"] == "disconnected"
    assert "fixture-only-secret" not in json.dumps(call(session, "/v1/me"))
    assert call(session, "/v1/auth/link", "POST", {"email": "test@example.com"})["status"] == 404
    assert call(session, "/v1/billing/checkout", "POST", {})["status"] == 404
    call(session, "/v1/session/connection", "DELETE")
    assert not session.headers


@pytest.mark.parametrize(
    "command",
    [
        FIXTURE_CURL.replace("www.aadvantagehotels.com", "other.example"),
        "curl 'https://www.aadvantagehotels.com'",
        "curl 'unterminated",
        FIXTURE_CURL.replace("https:", "http:"),
    ],
)
def test_rejects_unusable_connections_without_reflecting_credentials(session, command):
    reply = call(session, "/v1/session/connection", "POST", {"curl": command})
    assert reply["status"] == 422 and not session.headers
    assert "fixture-only-secret" not in json.dumps(reply)


def test_connection_expires_even_without_a_browser_request(session, monkeypatch):
    monkeypatch.setattr(runtime, "SESSION_SECONDS", 0.02)
    call(session, "/v1/session/connection", "POST", {"curl": FIXTURE_CURL})
    session.expiry_timer.join(timeout=1)
    assert not session.headers


def mock_provider(monkeypatch, rows=None):
    calls = []
    searches = {}
    monkeypatch.setattr(
        runtime.provider, "discover_place_ids", lambda *a, **kw: [("Phoenix", "123")]
    )

    def start(check_in, check_out, location, place_id, **kw):
        assert kw["adults"] == 2 and kw["rooms"] == 2
        assert kw["session_headers"] == {"Cookie": "fixture"}
        searches[str(len(searches))] = (check_in, check_out)
        calls.append((check_in, check_out))
        return str(len(searches) - 1)

    def results(search_id, *args, **kwargs):
        if rows is not None:
            return rows
        check_in, check_out = searches[search_id]
        from datetime import datetime

        nights = (
            datetime.strptime(check_out, "%m/%d/%Y") - datetime.strptime(check_in, "%m/%d/%Y")
        ).days
        return {
            "results": [
                {
                    "hotel": {"id": "hotel", "name": "Fixture Hotel"},
                    "grandTotalPublishedPriceInclusiveWithFees": {"amount": 100 * nights},
                    "rewards": 4000 if nights == 1 else 3000,
                }
            ]
        }

    monkeypatch.setattr(runtime.provider, "search_aadvantage_hotels", start)
    monkeypatch.setattr(runtime.provider, "get_hotel_results", results)
    return calls


def test_live_transport_fetches_whole_stay_and_every_split(monkeypatch):
    calls = mock_provider(monkeypatch)
    job = runtime.SearchJob(request(adults=2, rooms=2))
    monkeypatch.setattr(job.cancelled, "wait", lambda seconds: False)
    result = runtime.collect_offers(job, {"Cookie": "fixture"})
    assert len(calls) == 3 and len(set(calls)) == 3
    assert not result["sample"]
    assert result["plans"][0]["earned_lp"] == 8000
    assert result["baseline"]["earned_lp"] == 3000
    assert job.snapshot()["progress"] == {"done": 3, "total": 3}


@pytest.mark.parametrize("data", [None, {"results": [], "complete": False}, {"results": [{}] * 45}])
def test_incomplete_or_repeated_pages_never_become_successful_plans(monkeypatch, data):
    mock_provider(monkeypatch, rows=data or {"unexpected": True})
    job = runtime.SearchJob(request(adults=2, rooms=2))
    with pytest.raises(runtime.PreviewError):
        runtime.collect_offers(job, {"Cookie": "fixture"})
    assert not job.snapshot().get("plans")


def test_worker_clears_headers_and_does_not_return_exception_secrets(monkeypatch):
    def broken(job, headers):
        raise RuntimeError("fixture-only-secret")

    monkeypatch.setattr(runtime, "collect_offers", broken)
    headers = {"Cookie": "fixture-only-secret"}
    job = runtime.SearchJob(request())
    assert runtime.MAX_ACTIVE.acquire(blocking=False)
    runtime.run_job(job, headers)
    assert not headers and job.snapshot()["status"] == "failed"
    assert "fixture-only-secret" not in json.dumps(job.snapshot())


def test_cancel_owner_scope_and_busy_limit(session, monkeypatch):
    job = runtime.SearchJob(request())
    job.update(status="running")
    session.jobs[job.id] = job
    assert call(runtime.PreviewSession(), f"/v1/searches/{job.id}")["status"] == 404
    assert call(session, f"/v1/searches/{job.id}/cancel", "POST")["data"]["status"] == "cancelled"
    assert job.cancelled.is_set()
    call(session, "/v1/session/connection", "POST", {"curl": FIXTURE_CURL})
    monkeypatch.setattr(runtime, "MAX_ACTIVE", threading.BoundedSemaphore(0))
    result = call(session, "/v1/searches", "POST", request().model_dump(mode="json"))
    assert result["status"] == 429


def test_validation_and_credentials_are_required_for_live_searches(session):
    body = request().model_dump(mode="json")
    assert call(session, "/v1/searches", "POST", body)["status"] == 401
    body["check_out"] = body["check_in"]
    assert call(session, "/v1/demo", "POST", body)["status"] == 422
    assert session.handle({"body": "x" * 100001})["status"] == 422
