from datetime import timedelta

from sqlalchemy import func, select, update

from aa_hotel_optimizer.service.db import Connection, Credential, Quote, Search, Task, User, now
from tests.test_service import connect, create_search, login, search_body


def test_started_searches_consume_trial_and_cancel_blocks_upload(client, app):
    app.state.config.free_searches = 1
    login(client)
    bridge = connect(client)
    search = create_search(client)
    task = client.post("/v1/bridge/tasks/claim", json={}, headers=bridge).json()["task"]
    client.post("/v1/searches/" + search["id"] + "/cancel", json={})
    assert (
        client.post(
            "/v1/bridge/tasks/" + task["id"] + "/result",
            json={"lease_token": task["lease_token"], "status": "ok", "data": {}},
            headers=bridge,
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/v1/searches", json=search_body(), headers={"Idempotency-Key": "second-search"}
        ).status_code
        == 402
    )


def test_lease_recovery_and_previous_token_invalidated(client, app):
    login(client)
    bridge = connect(client)
    create_search(client)
    first = client.post("/v1/bridge/tasks/claim", json={}, headers=bridge).json()["task"]
    with app.state.sessions() as db:
        db.execute(
            update(Task)
            .where(Task.id == first["id"])
            .values(lease_until=now() - timedelta(seconds=1))
        )
        db.execute(update(Connection).values(next_request_at=now() - timedelta(seconds=1)))
        db.commit()
    second = client.post("/v1/bridge/tasks/claim", json={}, headers=bridge).json()["task"]
    assert first["id"] == second["id"] and first["lease_token"] != second["lease_token"]
    assert (
        client.post(
            "/v1/bridge/tasks/" + first["id"] + "/result",
            json={"lease_token": first["lease_token"], "status": "ok", "data": {}},
            headers=bridge,
        ).status_code
        == 409
    )
    assert client.get("/v1/searches", headers=bridge).status_code == 401


def test_changed_aa_account_requires_explicit_reconnect(client):
    login(client)
    bridge = connect(client)
    response = client.post(
        "/v1/bridge/heartbeat",
        json={"state": "connected", "account_fingerprint": "b" * 64},
        headers=bridge,
    )
    assert response.status_code == 409
    assert client.get("/v1/me").json()["connection"]["state"] == "reauth_required"


def test_provider_failure_returns_the_customers_search_allowance(client):
    login(client)
    bridge = connect(client)
    search = create_search(client)
    task = client.post("/v1/bridge/tasks/claim", json={}, headers=bridge).json()["task"]
    result = {"lease_token": task["lease_token"], "status": "provider_error"}
    assert (
        client.post(
            "/v1/bridge/tasks/" + task["id"] + "/result", json=result, headers=bridge
        ).status_code
        == 200
    )
    assert client.get("/v1/searches/" + search["id"]).json()["status"] == "failed"
    assert client.get("/v1/me").json()["usage"]["remaining"] == 2


def test_account_delete_cascades_and_requires_confirmation(client, app):
    login(client)
    connect(client)
    create_search(client)
    assert client.request("DELETE", "/v1/me", json={"confirmation": "oops"}).status_code == 422
    assert client.get("/v1/me/export").json()["searches"]
    assert (
        client.request("DELETE", "/v1/me", json={"confirmation": "delete my account"}).status_code
        == 200
    )
    with app.state.sessions() as db:
        for model in (User, Credential, Connection, Search, Task, Quote):
            assert db.scalar(select(func.count()).select_from(model)) == 0
