"""Hosted Stripe billing. Access changes only after a verified webhook."""

from datetime import UTC, datetime

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import BillingEvent, TripPass, User, now
from .security import fail


def client(config):
    if not config.stripe_secret_key:
        fail(503, "billing_unavailable", "Checkout is not available yet.")
    return stripe.StripeClient(
        config.stripe_secret_key,
        max_network_retries=1,
        http_client=stripe.RequestsClient(timeout=15),
    )


def checkout(config, db, user, product="membership"):
    if not config.billing_enabled:
        fail(503, "billing_unavailable", "Checkout is not available yet.")
    api = client(config)
    if not config.provider_enabled and not config.test_billing:
        fail(503, "live_search_unavailable", "Membership opens when live searches are available.")
    user = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if product == "membership" and user.subscription_status in (
        "active",
        "trialing",
        "past_due",
        "unpaid",
        "incomplete",
    ):
        fail(409, "subscription_exists", "Use Manage membership to update your subscription.")
    if not user.stripe_customer:
        customer = api.v1.customers.create(
            {"email": user.email, "metadata": {"user_id": user.id}},
            options={"idempotency_key": f"customer-{user.id}"},
        )
        user.stripe_customer = customer.id
        db.flush()
    if product == "trip_pass":
        return pass_checkout(config, api, db, user)
    if user.checkout_session_id and user.checkout_expires_at and user.checkout_expires_at > now():
        existing = api.v1.checkout.sessions.retrieve(user.checkout_session_id)
        if existing.status == "open":
            return {"url": existing.url}
        if existing.status == "complete":
            fail(409, "payment_pending", "Your payment is being confirmed. Refresh in a moment.")
    # A webhook may be delayed; don't create a second subscription in that gap.
    subscriptions = api.v1.subscriptions.list(
        {"customer": user.stripe_customer, "status": "all", "limit": 100}
    )
    if any(
        item.status in ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")
        for item in subscriptions.data
    ):
        fail(409, "subscription_exists", "A membership already exists. Refresh to manage it.")
    # One checkout per customer per ten-minute window prevents double-click duplication.
    window = int(datetime.now(UTC).timestamp()) // 600
    session = api.v1.checkout.sessions.create(
        {
            "mode": "subscription",
            "customer": user.stripe_customer,
            "line_items": [{"price": config.stripe_price_id, "quantity": 1}],
            "client_reference_id": user.id,
            "subscription_data": {"metadata": {"user_id": user.id}},
            "success_url": config.public_url + "/?billing=success",
            "cancel_url": config.public_url + "/?billing=cancelled",
            "allow_promotion_codes": True,
        },
        options={"idempotency_key": f"checkout-{user.id}-{window}"},
    )
    user.checkout_session_id = session.id
    user.checkout_expires_at = datetime.fromtimestamp(session.expires_at, UTC).replace(tzinfo=None)
    db.commit()
    return {"url": session.url}


def pass_checkout(config, api, db, user):
    pending = db.scalars(
        select(TripPass).where(TripPass.user_id == user.id, TripPass.status == "pending")
    ).all()
    for item in pending:
        session = api.v1.checkout.sessions.retrieve(item.checkout_session_id)
        if session.status == "open" and item.checkout_expires_at > now():
            return {"url": session.url}
        if session.status == "complete":
            fail(409, "payment_pending", "Your payment is being confirmed. Refresh in a moment.")
        item.status = "expired"
    window = int(datetime.now(UTC).timestamp()) // 600
    # Include the previous purchase so a second intentional purchase can be made
    # in the same window, while double clicks still reuse an open checkout.
    previous = db.scalar(
        select(TripPass.id).where(TripPass.user_id == user.id).order_by(TripPass.created_at.desc())
    )
    session = api.v1.checkout.sessions.create(
        {
            "mode": "payment",
            "customer": user.stripe_customer,
            "line_items": [{"price": config.stripe_trip_pass_price_id, "quantity": 1}],
            "client_reference_id": user.id,
            "metadata": {"user_id": user.id, "product": "trip_pass"},
            "payment_intent_data": {
                "metadata": {"user_id": user.id, "product": "trip_pass"},
                "receipt_email": user.email,
            },
            "success_url": config.public_url + "/?billing=success",
            "cancel_url": config.public_url + "/?billing=cancelled",
        },
        options={"idempotency_key": f"pass-{user.id}-{previous or 'first'}-{window}"},
    )
    db.add(
        TripPass(
            user_id=user.id,
            checkout_session_id=session.id,
            checkout_expires_at=datetime.fromtimestamp(session.expires_at, UTC).replace(
                tzinfo=None
            ),
            price_id=config.stripe_trip_pass_price_id,
            search_limit=config.trip_pass_searches,
        )
    )
    db.commit()
    return {"url": session.url}


def payment_state(api, payment_intent):
    intent = api.v1.payment_intents.retrieve(
        payment_intent, {"expand": ["latest_charge"]}
    ).to_dict()
    if intent.get("status") != "succeeded":
        return "pending"
    charge = intent.get("latest_charge") or {}
    if charge.get("refunded"):
        return "refunded"
    if charge.get("disputed"):
        disputes = api.v1.disputes.list({"payment_intent": payment_intent, "limit": 100})
        if any(d.status not in ("won", "warning_closed") for d in disputes.data):
            return "disputed"
    return "paid"


def fulfill_pass(api, db, user, session_id):
    purchase = db.scalar(
        select(TripPass).where(
            TripPass.checkout_session_id == session_id, TripPass.user_id == user.id
        )
    )
    if not purchase:
        return
    session = api.v1.checkout.sessions.retrieve(session_id, {"expand": ["line_items"]}).to_dict()
    items = session.get("line_items", {}).get("data", [])
    if (
        session.get("customer") != user.stripe_customer
        or session.get("client_reference_id") != user.id
        or session.get("mode") != "payment"
        or len(items) != 1
        or items[0].get("price", {}).get("id") != purchase.price_id
        or items[0].get("quantity") != 1
    ):
        fail(400, "purchase_mismatch", "The payment did not match this purchase.")
    if session.get("payment_status") != "paid" or not session.get("payment_intent"):
        return
    purchase.payment_intent = session["payment_intent"]
    purchase.status = payment_state(api, purchase.payment_intent)
    if purchase.status == "paid" and not purchase.paid_at:
        purchase.paid_at = now()


def portal(config, user):
    api = client(config)
    if not user.stripe_customer:
        fail(409, "no_membership", "There is no membership to manage yet.")
    session = api.v1.billing_portal.sessions.create(
        {"customer": user.stripe_customer, "return_url": config.public_url + "/"}
    )
    return {"url": session.url}


def webhook(config, db, payload: bytes, signature: str):
    api = client(config)
    if not config.stripe_webhook_secret:
        fail(503, "billing_unavailable", "The billing endpoint is not configured.")
    try:
        event = stripe.Webhook.construct_event(payload, signature, config.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        fail(400, "invalid_signature", "Invalid billing signature.")
    event = event.to_dict()
    if db.get(BillingEvent, event["id"]):
        return {"received": True}
    supported = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "charge.refunded",
        "charge.dispute.created",
        "charge.dispute.closed",
    }
    if event["type"] in supported:
        data = event["data"]["object"]
        if event["type"].startswith("charge."):
            user = (
                db.scalar(
                    select(User)
                    .join(TripPass, TripPass.user_id == User.id)
                    .where(TripPass.payment_intent == data.get("payment_intent"))
                    .with_for_update(of=User)
                )
                if data.get("payment_intent")
                else None
            )
            if user:
                purchase = db.scalar(
                    select(TripPass).where(TripPass.payment_intent == data["payment_intent"])
                )
                purchase.status = payment_state(api, purchase.payment_intent)
            # Charge events do not contain a subscription.
            data = {}
        subscription_id = (
            data.get("id")
            if event["type"].startswith("customer.subscription.")
            else data.get("subscription")
        )
        if event["type"].startswith("checkout") and data.get("mode") == "payment":
            user = (
                db.scalar(
                    select(User)
                    .where(User.stripe_customer == data.get("customer"))
                    .with_for_update()
                )
                if data.get("customer")
                else None
            )
            if user:
                if event["type"] == "checkout.session.async_payment_failed":
                    purchase = db.scalar(
                        select(TripPass).where(
                            TripPass.checkout_session_id == data["id"],
                            TripPass.user_id == user.id,
                            TripPass.status == "pending",
                        )
                    )
                    if purchase:
                        current = api.v1.checkout.sessions.retrieve(data["id"])
                        if current.payment_status != "paid":
                            purchase.status = "failed"
                else:
                    fulfill_pass(api, db, user, data["id"])
        if subscription_id and data.get("customer"):
            user = db.scalar(
                select(User).where(User.stripe_customer == data["customer"]).with_for_update()
            )
            if user:
                # Fetch after acquiring the account lock, so concurrent deliveries
                # cannot commit an older snapshot after a newer subscription state.
                subscription = api.v1.subscriptions.retrieve(subscription_id).to_dict()
                if subscription["customer"] != user.stripe_customer:
                    fail(400, "billing_customer_mismatch", "Billing customer did not match.")
                items = subscription.get("items", {}).get("data", [])
                configured = [
                    item
                    for item in items
                    if item.get("price", {}).get("id") == config.stripe_price_id
                ]
                if user.subscription_id not in (None, subscription["id"]) and subscription[
                    "status"
                ] not in ("active", "trialing"):
                    # A late cancellation of a previous subscription must not
                    # remove the customer's replacement membership.
                    configured = []
                if configured:
                    user.subscription_id = subscription["id"]
                    user.subscription_status = subscription["status"]
                    end = subscription.get("current_period_end") or max(
                        (item.get("current_period_end", 0) for item in configured), default=0
                    )
                    user.subscription_until = datetime.fromtimestamp(end, UTC).replace(tzinfo=None)
                    user.cancel_at_period_end = bool(subscription.get("cancel_at_period_end"))
                elif user.subscription_id == subscription["id"]:
                    user.subscription_status = "inactive"
                    user.subscription_until = None
    db.add(BillingEvent(id=event["id"]))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # A concurrently delivered duplicate has already committed.
    return {"received": True}
