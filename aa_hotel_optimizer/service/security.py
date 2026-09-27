"""Application credentials only. AA credentials never enter this database."""

from __future__ import annotations

import hashlib
import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from html import escape

import requests
from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select

from .db import Credential, RateEvent, User, now

COOKIE = "lp_session"
AGENT_SCOPES = {"search:read", "search:write"}


def token():
    return secrets.token_urlsafe(32)


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def fail(status, code, message):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def rate_limit(db, key: str, limit: int, seconds: int):
    key = digest(key)
    cutoff = now() - timedelta(seconds=seconds)
    count = db.scalar(
        select(func.count())
        .select_from(RateEvent)
        .where(RateEvent.key == key, RateEvent.created_at > cutoff)
    )
    if count >= limit:
        fail(429, "rate_limited", "Please wait a little before trying again.")
    db.add(RateEvent(key=key))
    db.execute(delete(RateEvent).where(RateEvent.created_at < now() - timedelta(days=2)))
    db.commit()


def identity(request: Request, db, scope="search:read", session_only=False):
    authorization = request.headers.get("authorization", "")
    bearer = authorization.startswith("Bearer ")
    raw = authorization[7:] if bearer else request.cookies.get(COOKIE, "")
    if not raw or len(raw) > 200:
        fail(401, "sign_in_required", "Sign in to continue.")
    credential = db.scalar(
        select(Credential).where(Credential.digest == digest(raw), Credential.expires_at > now())
    )
    expected_kind = "agent" if bearer else "session"
    if not credential or credential.kind != expected_kind:
        fail(401, "sign_in_required", "This sign-in has expired. Please sign in again.")
    if session_only and bearer:
        fail(403, "browser_required", "Manage your account in the app.")
    if bearer and scope not in credential.scopes:
        fail(403, "insufficient_scope", "This key does not have the required scope.")
    user = db.get(User, credential.user_id)
    if not user:
        fail(401, "sign_in_required", "Sign in to continue.")
    return user, credential


def email_link(config, email: str, link: str):
    message = EmailMessage()
    message["Subject"] = f"Your {config.app_name} sign-in link"
    message["From"] = config.email_from
    message["To"] = email
    message.set_content(
        f"Sign in to {config.app_name}:\n\n{link}\n\n"
        "This link expires in 15 minutes and works once. "
        "If you did not request it, you can ignore this email.\n"
    )
    message.add_alternative(
        f"<h1>Sign in to {escape(config.app_name)}</h1>"
        f'<p><a href="{escape(link, quote=True)}">Continue to your account</a></p>'
        "<p>This link expires in 15 minutes and works once. "
        "If you did not request it, you can ignore this email.</p>",
        subtype="html",
    )
    if config.resend_api_key:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer " + config.resend_api_key},
            json={
                "from": config.email_from,
                "to": [email],
                "subject": str(message["Subject"]),
                "text": message.get_body(preferencelist=("plain",)).get_content(),
                "html": message.get_body(preferencelist=("html",)).get_content(),
            },
            timeout=15,
        )
        response.raise_for_status()
        return
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
        if config.smtp_starttls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(message)


def paid(user: User):
    return (
        user.subscription_status in ("active", "trialing")
        and user.subscription_until is not None
        and user.subscription_until > now()
    )
