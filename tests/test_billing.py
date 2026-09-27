import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import stripe
from sqlalchemy import select

from aa_hotel_optimizer.service import billing
from aa_hotel_optimizer.service.db import BillingEvent, User
from tests.test_service import login


def signed(event, secret):
    body = json.dumps(event, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return body, f"t={timestamp},v1={signature}"


def test_signed_idempotent_webhook_uses_current_state(client, app, monkeypatch):
    login(client)
    config = app.state.config
    config.stripe_secret_key = "sk_test_fixture"
    config.stripe_price_id = "price_membership"
    config.stripe_webhook_secret = "whsec_fixture"
    with app.state.sessions() as db:
        user = db.scalar(select(User))
        user.stripe_customer = "cus_fixture"
        db.commit()
    calls = []
    current = {
        "id": "sub_fixture",
        "customer": "cus_fixture",
        "status": "active",
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "price": {"id": "price_membership"},
                    "current_period_end": int(time.time()) + 86400,
                }
            ]
        },
    }

    def retrieve(id):
        calls.append(id)
        return stripe.StripeObject.construct_from(current, None)

    monkeypatch.setattr(
        billing,
        "client",
        lambda _: SimpleNamespace(
            v1=SimpleNamespace(subscriptions=SimpleNamespace(retrieve=retrieve))
        ),
    )
    event = {
        "id": "evt_first",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_fixture", "customer": "cus_fixture"}},
    }
    payload, signature = signed(event, config.stripe_webhook_secret)
    assert (
        client.post(
            "/v1/billing/webhook", content=payload, headers={"Stripe-Signature": "invalid"}
        ).status_code
        == 400
    )
    response = client.post(
        "/v1/billing/webhook", content=payload, headers={"Stripe-Signature": signature}
    )
    assert response.status_code == 200, response.text
    assert client.get("/v1/me").json()["paid"] is True
    assert (
        client.post(
            "/v1/billing/webhook", content=payload, headers={"Stripe-Signature": signature}
        ).status_code
        == 200
    )
    assert len(calls) == 1
    # A delayed earlier event must see today's cancelled Stripe state.
    current["status"] = "canceled"
    event["id"] = "evt_delayed"
    payload, signature = signed(event, config.stripe_webhook_secret)
    assert (
        client.post(
            "/v1/billing/webhook", content=payload, headers={"Stripe-Signature": signature}
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["paid"] is False
    with app.state.sessions() as db:
        assert len(db.scalars(select(BillingEvent)).all()) == 2


def test_unsigned_checkout_redirect_does_not_grant_access(client):
    login(client)
    assert client.get("/v1/me").json()["paid"] is False
    assert client.post("/v1/billing/checkout", json={}).status_code == 503
    assert client.get("/v1/me").json()["paid"] is False


def test_checkout_reuses_open_session_and_price_is_server_controlled(client, app, monkeypatch):
    login(client)
    config = app.state.config
    config.stripe_price_id = "price_server_chosen"
    config.stripe_trip_pass_price_id = "price_pass"
    config.stripe_secret_key = "sk_test_fixture"
    config.stripe_webhook_secret = "whsec_fixture"
    created = []
    existing = SimpleNamespace(
        id="cs_fixture",
        url="https://checkout.stripe.com/fixture",
        status="open",
        expires_at=int(time.time()) + 86400,
    )

    def create(params, options):
        created.append(params)
        return existing

    api = SimpleNamespace(
        v1=SimpleNamespace(
            customers=SimpleNamespace(
                create=lambda *args, **kwargs: SimpleNamespace(id="cus_fixture")
            ),
            subscriptions=SimpleNamespace(list=lambda *args, **kwargs: SimpleNamespace(data=[])),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(create=create, retrieve=lambda _: existing)
            ),
        )
    )
    monkeypatch.setattr(billing, "client", lambda _: api)
    assert (
        client.post("/v1/billing/checkout", json={"price": "attacker_supplied"}).status_code == 422
    )
    first = client.post("/v1/billing/checkout", json={})
    second = client.post("/v1/billing/checkout", json={})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(created) == 1
    assert created[0]["line_items"] == [{"price": "price_server_chosen", "quantity": 1}]
    assert client.get("/v1/me").json()["paid"] is False
