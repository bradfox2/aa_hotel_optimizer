from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(UTC).replace(tzinfo=None)


def uid():
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    stripe_customer: Mapped[str | None] = mapped_column(String(100), unique=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(150))
    checkout_expires_at: Mapped[datetime | None] = mapped_column()
    subscription_id: Mapped[str | None] = mapped_column(String(100))
    subscription_status: Mapped[str] = mapped_column(String(30), default="free")
    subscription_until: Mapped[datetime | None] = mapped_column()
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginToken(Base):
    __tablename__ = "login_tokens"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    expires_at: Mapped[datetime] = mapped_column()


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(80), default="")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime] = mapped_column()


class Connection(Base):
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(30), default="pairing")
    pair_digest: Mapped[str | None] = mapped_column(String(64), unique=True)
    pair_expires: Mapped[datetime | None] = mapped_column()
    bridge_digest: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    bridge_expires: Mapped[datetime | None] = mapped_column()
    account_fingerprint: Mapped[str | None] = mapped_column(String(64))
    account_label: Mapped[str] = mapped_column(String(100), default="")
    last_seen: Mapped[datetime | None] = mapped_column()
    next_request_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=now)


class Search(Base):
    __tablename__ = "searches"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("connections.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str] = mapped_column(String(120))
    allowance: Mapped[str] = mapped_column(String(20), default="free")
    trip_pass_id: Mapped[str | None] = mapped_column(
        ForeignKey("trip_passes.id", ondelete="SET NULL"), index=True
    )
    request: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(50))
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    plans: Mapped[list] = mapped_column(JSON, default=list)
    provider_calls: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_digest: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=now)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("search_id", "offer_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    search_id: Mapped[str] = mapped_column(
        ForeignKey("searches.id", ondelete="CASCADE"), index=True
    )
    offer_id: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSON)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(default=now)


class TripPass(Base):
    __tablename__ = "trip_passes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    checkout_session_id: Mapped[str] = mapped_column(String(150), unique=True)
    checkout_expires_at: Mapped[datetime] = mapped_column()
    payment_intent: Mapped[str | None] = mapped_column(String(150), unique=True)
    price_id: Mapped[str] = mapped_column(String(150))
    search_limit: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(default=now)
    paid_at: Mapped[datetime | None] = mapped_column()


class RateEvent(Base):
    __tablename__ = "rate_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)


def database(url: str, initialize=False):
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    kwargs = (
        {"connect_args": {"check_same_thread": False, "timeout": 15}}
        if url.startswith("sqlite")
        else {"pool_pre_ping": True}
    )
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    if initialize:
        Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
