from datetime import date, timedelta
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from aa_hotel_optimizer.service.config import Settings
from aa_hotel_optimizer.service.db import Connection, Credential, now
from aa_hotel_optimizer.service.security import digest

ORIGIN = "http://127.0.0.1:8765"


def login(client, email="traveler@example.com"):
    response = client.post("/v1/auth/link", json={"email": email})
    assert response.status_code == 200, response.text
    token = urlparse(response.json()["development_link"]).fragment.split("=", 1)[1]
    response = client.post("/v1/auth/consume", json={"token": token})
    assert response.status_code == 200, response.text
    return token


def connect(client):
    pair = client.post("/v1/connections", json={}).json()
    linked = client.post("/v1/bridge/pair", json={"token": pair["pairing_token"]}).json()
    headers = {"Authorization": "Bearer " + linked["bridge_key"]}
    assert (
        client.post(
            "/v1/bridge/heartbeat",
            json={"state": "connected", "account_fingerprint": "a" * 64},
            headers=headers,
        ).status_code
        == 200
    )
    return headers


def search_body():
    start = date.today() + timedelta(days=5)
    return {
        "mode": "trip",
        "cities": ["Phoenix"],
        "check_in": str(start),
        "check_out": str(start + timedelta(days=2)),
    }


def create_search(client, key="search-one"):
    response = client.post("/v1/searches", json=search_body(), headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return response.json()


def test_magic_link_single_use_and_cookie_properties(client, app):
    token = login(client)
    assert client.post("/v1/auth/consume", json={"token": token}).status_code == 401
    assert client.get("/v1/me").json()["email"] == "traveler@example.com"
    raw = client.cookies.get("lp_session")
    with app.state.sessions() as db:
        assert db.scalar(select(Credential).where(Credential.digest == digest(raw)))
        assert not db.scalar(select(Credential).where(Credential.digest == raw))
    assert client.post("/v1/auth/logout", json={}).status_code == 200
    assert client.get("/v1/me").status_code == 401


def test_csrf_and_body_limits(client):
    assert (
        client.post(
            "/v1/auth/link",
            json={"email": "x@example.com"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/auth/link", content="x" * 1_000_001, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )


def test_bearer_scopes_and_revocation(client):
    login(client)
    key = client.post("/v1/keys", json={"label": "Read only", "scopes": ["search:read"]}).json()
    headers = {"Authorization": "Bearer " + key["key"]}
    assert client.get("/v1/searches", headers=headers).status_code == 200
    assert client.post("/v1/searches", json=search_body(), headers=headers).status_code == 403
    assert client.post("/v1/billing/checkout", json={}, headers=headers).status_code == 403
    assert client.request("DELETE", "/v1/keys/" + key["id"], json={}).status_code == 200
    assert client.get("/v1/searches", headers=headers).status_code == 401


def test_account_isolation_and_idempotency(client, app):
    login(client)
    connect(client)
    first = create_search(client)
    assert create_search(client)["id"] == first["id"]
    changed = search_body() | {"adults": 2}
    assert (
        client.post(
            "/v1/searches", json=changed, headers={"Idempotency-Key": "search-one"}
        ).status_code
        == 409
    )
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as other:
        login(other, "other@example.com")
        assert other.get("/v1/searches/" + first["id"]).status_code == 404
        assert other.post("/v1/searches/" + first["id"] + "/cancel", json={}).status_code == 404


def test_full_durable_browser_job_and_replay_rejected(client, app):
    login(client)
    headers = connect(client)
    search = create_search(client)
    count = 0
    while count < 20:
        with app.state.sessions() as db:
            db.execute(update(Connection).values(next_request_at=now() - timedelta(seconds=1)))
            db.commit()
        task = client.post("/v1/bridge/tasks/claim", json={}, headers=headers).json()["task"]
        if not task:
            break
        count += 1
        assert (
            client.post("/v1/bridge/tasks/claim", json={}, headers=headers).json()["task"] is None
        )
        if task["kind"] == "places":
            data = {"places": [{"id": "city-1", "name": "Phoenix", "type": "AGODA_CITY"}]}
        elif task["kind"] == "start":
            data = {"uuid": "test-uuid"}
        else:
            nights = (
                date.fromisoformat(task["payload"]["check_out"])
                - date.fromisoformat(task["payload"]["check_in"])
            ).days
            data = {
                "results": [
                    {
                        "hotel": {"id": "h1", "name": "Test Hotel"},
                        "rewards": 4000 if nights == 1 else 5000,
                        "grandTotalPublishedPriceInclusiveWithFees": {
                            "amount": 100 * nights,
                            "currency": "USD",
                        },
                    }
                ]
            }
        body = {"lease_token": task["lease_token"], "status": "ok", "data": data}
        url = "/v1/bridge/tasks/" + task["id"] + "/result"
        assert client.post(url, json=body, headers=headers).status_code == 200
        assert client.post(url, json=body, headers=headers).status_code == 409
    result = client.get("/v1/searches/" + search["id"]).json()
    assert result["status"] == "completed", result
    assert result["plans"][0]["booking_count"] == 2
    assert result["plans"][0]["earned_lp"] == 8000
    assert count == 7


def test_reauth_and_cancel_are_explicit(client):
    login(client)
    headers = connect(client)
    search = create_search(client)
    task = client.post("/v1/bridge/tasks/claim", json={}, headers=headers).json()["task"]
    assert (
        client.post(
            "/v1/bridge/tasks/" + task["id"] + "/result",
            json={"lease_token": task["lease_token"], "status": "reauth_required"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/v1/searches/" + search["id"]).json()["status"] == "reauth_required"
    assert (
        client.post("/v1/searches/" + search["id"] + "/cancel", json={}).json()["status"]
        == "cancelled"
    )


def test_sample_needs_no_account_and_has_explicit_label(client):
    response = client.post("/v1/demo", json=search_body())
    assert response.status_code == 200, response.text
    assert response.json()["sample"] is True
    assert all(q["reward_basis"] == "sample" for p in response.json()["plans"] for q in p["offers"])


def test_production_rejects_insecure_config():
    with pytest.raises(ValueError):
        Settings(_env_file=None, environment="production").validate_deployment()
