"""Search allowances follow the purchase that funded each search."""

from sqlalchemy import func, select

from .db import Search, TripPass, now
from .security import paid


def counted():
    return (Search.status.not_in(("failed", "cancelled"))) | (
        (Search.status == "cancelled") & (Search.provider_calls > 0)
    )


def usage(config, db, user):
    query = select(func.count()).select_from(Search).where(Search.user_id == user.id, counted())
    free_used = db.scalar(query.where(Search.allowance == "free"))
    free_remaining = max(0, config.free_searches - free_used)
    membership = paid(user)
    monthly_used = db.scalar(
        query.where(
            Search.allowance == "membership",
            Search.created_at >= now().replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        )
    )
    monthly_limit = config.paid_searches_per_month if membership else 0
    monthly_remaining = max(0, monthly_limit - monthly_used) if membership else 0
    passes = db.scalars(
        select(TripPass)
        .where(TripPass.user_id == user.id, TripPass.status == "paid")
        .order_by(TripPass.created_at, TripPass.id)
    ).all()
    pass_limit, pass_remaining, next_pass = 0, 0, None
    for item in passes:
        used = db.scalar(query.where(Search.trip_pass_id == item.id))
        remaining = max(0, item.search_limit - used)
        pass_limit += item.search_limit
        pass_remaining += remaining
        if remaining and next_pass is None:
            next_pass = item.id
    remaining = free_remaining + monthly_remaining + pass_remaining
    limit = config.free_searches + monthly_limit + pass_limit
    return {
        "used": limit - remaining,
        "limit": limit,
        "remaining": remaining,
        "period": "month" if membership else "trip_pass" if pass_remaining else "trial",
        "free_remaining": free_remaining,
        "monthly_remaining": monthly_remaining,
        "trip_pass_remaining": pass_remaining,
        "next_pass": next_pass,
    }


def allocate(allowance):
    # Use expiring monthly searches before non-expiring passes.
    if allowance["free_remaining"]:
        return {"allowance": "free"}
    if allowance["monthly_remaining"]:
        return {"allowance": "membership"}
    return {"allowance": "trip_pass", "trip_pass_id": allowance["next_pass"]}
