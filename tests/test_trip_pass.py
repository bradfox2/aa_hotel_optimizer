import time
from datetime import timedelta
from types import SimpleNamespace

import stripe
from sqlalchemy import select

from aa_hotel_optimizer.service import billing
from aa_hotel_optimizer.service.db import Search, TripPass, User, now
from tests.test_billing import signed
from tests.test_service import connect, create_search, login, search_body


def configure(app):
    config = app.state.config
    config.stripe_secret_key = "sk_test_fixture"
    config.stripe_webhook_secret = "whsec_fixture"
    config.stripe_price_id = "price_monthly"
    config.stripe_trip_pass_price_id = "price_pass"
    return config


def send_event(client, config, event_id, kind, data):
    body, signature = signed(
        {"id": event_id, "object": "event", "type": kind, "data": {"object": data}},
        config.stripe_webhook_secret,
    )
    return client.post("/v1/billing/webhook", content=body, headers={"Stripe-Signature": signature})


def test_pass_checkout_payment_replay_refund_and_dispute(client, app, monkeypatch):
    login(client)
    config = configure(app)
    session = {
        "id": "cs_pass",
        "url": "https://checkout.stripe.com/fixture",
        "status": "open",
        "expires_at": int(time.time()) + 86400,
        "payment_status": "unpaid",
        "payment_intent": "pi_pass",
        "line_items": {"data": [{"price": {"id": "price_pass"}, "quantity": 1}]},
    }
    intent = {"status": "succeeded", "latest_charge": {"refunded": False, "disputed": False}}
    dispute = SimpleNamespace(status="needs_response")
    calls = []

    def create(params, options):
        calls.append(params)
        session.update({k: params[k] for k in ("customer", "client_reference_id", "mode")})
        return stripe.StripeObject.construct_from(session, None)

    api = SimpleNamespace(
        v1=SimpleNamespace(
            customers=SimpleNamespace(create=lambda *a, **k: SimpleNamespace(id="cus_pass")),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(
                    create=create,
                    retrieve=lambda *a: stripe.StripeObject.construct_from(session, None),
                )
            ),
            payment_intents=SimpleNamespace(
                retrieve=lambda *a: stripe.StripeObject.construct_from(intent, None)
            ),
            disputes=SimpleNamespace(list=lambda *a: SimpleNamespace(data=[dispute])),
        )
    )
    monkeypatch.setattr(billing, "client", lambda _: api)
    # A double click must not create a second purchase or grant any access.
    for _ in range(2):
        assert client.post("/v1/billing/checkout", json={"product": "trip_pass"}).status_code == 200
    assert len(calls) == 1 and calls[0]["mode"] == "payment"
    assert calls[0]["line_items"] == [{"price": "price_pass", "quantity": 1}]
    assert client.get("/v1/me").json()["usage"]["remaining"] == 2
    event_data = {"id": "cs_pass", "customer": "cus_pass", "mode": "payment"}
    session["status"] = "complete"
    assert (
        send_event(
            client, config, "evt_unpaid", "checkout.session.completed", event_data
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["usage"]["trip_pass_remaining"] == 0
    session["payment_status"] = "paid"
    for event_id in ("evt_paid", "evt_paid", "evt_redelivered"):
        assert (
            send_event(
                client, config, event_id, "checkout.session.async_payment_succeeded", event_data
            ).status_code
            == 200
        )
    assert client.get("/v1/me").json()["usage"]["remaining"] == 22
    with app.state.sessions() as db:
        assert len(db.scalars(select(TripPass)).all()) == 1
    # Chargebacks suspend access, winning restores it; a full refund removes it.
    intent["latest_charge"]["disputed"] = True
    assert (
        send_event(
            client, config, "evt_dispute", "charge.dispute.created", {"payment_intent": "pi_pass"}
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["usage"]["remaining"] == 2
    dispute.status = "won"
    assert (
        send_event(
            client, config, "evt_won", "charge.dispute.closed", {"payment_intent": "pi_pass"}
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["usage"]["remaining"] == 22
    intent["latest_charge"]["refunded"] = True
    assert (
        send_event(
            client, config, "evt_refund", "charge.refunded", {"payment_intent": "pi_pass"}
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["usage"]["remaining"] == 2
    assert (
        send_event(
            client, config, "evt_late_paid", "checkout.session.completed", event_data
        ).status_code
        == 200
    )
    assert client.get("/v1/me").json()["usage"]["trip_pass_remaining"] == 0
    # The signed event alone isn't enough; the stored purchase must match Stripe.
    session["line_items"]["data"][0]["price"]["id"] = "price_wrong"
    assert (
        send_event(
            client, config, "evt_wrong", "checkout.session.completed", event_data
        ).status_code
        == 400
    )


def test_two_free_then_payment_monthly_before_passes_and_failure_credit(client, app):
    login(client)
    connect(client)
    for index in range(2):
        result = create_search(client, f"free-search-{index}")
        with app.state.sessions() as db:
            row = db.get(Search, result["id"])
            assert row.allowance == "free"
            row.status = "completed"
            db.commit()
    assert (
        client.post(
            "/v1/searches", json=search_body(), headers={"Idempotency-Key": "third-search"}
        ).status_code
        == 402
    )
    with app.state.sessions() as db:
        user = db.scalar(select(User))
        user.subscription_status = "active"
        user.subscription_until = now() + timedelta(days=30)
        db.add(
            TripPass(
                user_id=user.id,
                checkout_session_id="cs_saved",
                checkout_expires_at=now(),
                price_id="price_pass",
                search_limit=20,
                status="paid",
            )
        )
        db.commit()
    app.state.config.paid_searches_per_month = 1
    monthly = create_search(client, "monthly-search")
    with app.state.sessions() as db:
        row = db.get(Search, monthly["id"])
        assert row.allowance == "membership" and row.trip_pass_id is None
        row.status = "completed"
        db.commit()
    result = create_search(client, "paid-pass-search")
    assert client.get("/v1/me").json()["usage"]["trip_pass_remaining"] == 19
    with app.state.sessions() as db:
        row = db.get(Search, result["id"])
        assert row.allowance == "trip_pass" and row.trip_pass_id
        row.status = "failed"
        user = db.scalar(select(User))
        user.subscription_status = "canceled"
        db.commit()
    me = client.get("/v1/me").json()
    assert not me["paid"]
    assert me["usage"]["remaining"] == 20
    assert me["usage"]["free_remaining"] == 0


def test_live_checkout_requires_released_companion_and_production(app):
    config = configure(app)
    assert config.billing_enabled  # Sandbox payments can be tested first.
    config.stripe_secret_key = "sk_live_fixture"
    assert not config.billing_enabled
    config.live_billing_enabled = True
    config.environment = "production"
    assert not config.billing_enabled
    config.companion_url = "https://chromewebstore.google.com/detail/lp/fixture"
    assert config.billing_enabled
    config.provider_enabled = False
    assert not config.billing_enabled
