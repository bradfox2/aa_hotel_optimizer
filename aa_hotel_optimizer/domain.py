"""Validated quotes and explicit reward eligibility shared by every client."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RewardPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_lp_per_dollar: Literal[0, 1] = 0
    card_miles_per_dollar: Literal[0, 1, 2, 3, 4, 5, 10] = 0
    partner_bonus_percent: Literal[0, 20, 25, 30] = 0
    bonus_start: date | None = None
    bonus_end: date | None = None
    bonus_remaining: int = Field(default=25000, ge=0, le=500000)
    miles_value_cents: float = Field(default=1.5, ge=0, le=10, allow_inf_nan=False)
    rules_version: Literal["2026-03-01"] = "2026-03-01"

    @model_validator(mode="after")
    def eligibility(self):
        if self.partner_bonus_percent == 25 and self.bonus_remaining > 25000:
            raise ValueError("The 25% promotion has a maximum allowance of 25,000 additional LP.")
        if self.partner_bonus_percent:
            if not self.bonus_start or not self.bonus_end:
                raise ValueError("Enter the active promotion dates shown in your AA account.")
            if not 0 <= (self.bonus_end - self.bonus_start).days <= 185:
                raise ValueError("Promotion dates must describe a window of at most 185 days.")
        return self

    def bonus_for(self, quote: Offer) -> int:
        # No future threshold crossing is inferred from a proposed itinerary.
        if (
            not self.partner_bonus_percent
            or not self.bonus_start
            or not self.bonus_end
            or not self.bonus_start <= quote.check_in <= self.bonus_end
        ):
            return 0
        return quote.base_lp * self.partner_bonus_percent // 100


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    property_id: str = Field(min_length=1, max_length=150)
    rate_id: str = Field(default="", max_length=150)
    name: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=150)
    check_in: date
    check_out: date
    price_cents: int = Field(gt=0, le=100_000_000)
    currency: Literal["USD"] = "USD"
    base_lp: int = Field(ge=0, le=100000)
    base_miles: int = Field(ge=0, le=100000)
    bonus_miles: int = Field(default=0, ge=0, le=100000)
    refundable: bool | None = None
    stars: float | None = Field(default=None, ge=0, le=5, allow_inf_nan=False)
    rating: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    room: str = Field(default="", max_length=300)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reward_basis: Literal["provider_base", "provider_rewards", "sample"] = "provider_rewards"

    @model_validator(mode="after")
    def dates(self):
        if not 1 <= (self.check_out - self.check_in).days <= 30:
            raise ValueError("A quote must cover between 1 and 30 nights.")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["trip", "status"] = "trip"
    cities: list[str] = Field(min_length=1, max_length=26)
    check_in: date
    check_out: date
    adults: int = Field(default=1, ge=1, le=8)
    rooms: int = Field(default=1, ge=1, le=4)
    starting_lp: int = Field(default=0, ge=0, le=5_000_000)
    target_lp: int = Field(default=200000, ge=0, le=5_000_000)
    budget_cents: int | None = Field(default=None, ge=100, le=10_000_000)
    objective: Literal["value", "points", "cost", "fastest"] = "value"
    split_bookings: bool = True
    include_multi_night: bool = True
    max_bookings: int = Field(default=14, ge=1, le=30)
    max_hotel_changes: int = Field(default=0, ge=0, le=10)
    max_overlaps: int = Field(default=1, ge=1, le=5)
    refundable_only: bool = False
    min_stars: int = Field(default=0, ge=0, le=5)
    policy: RewardPolicy = Field(default_factory=RewardPolicy)

    @model_validator(mode="after")
    def limits(self):
        self.cities = list(dict.fromkeys(x.strip() for x in self.cities if x.strip()))
        if not self.cities or any(len(x) > 100 for x in self.cities):
            raise ValueError("Choose at least one city, using names shorter than 100 characters.")
        nights = (self.check_out - self.check_in).days
        if not 1 <= nights <= (14 if self.mode == "trip" else 60):
            raise ValueError("Use up to 14 nights for a trip or 60 nights for a status search.")
        if self.mode == "trip" and len(self.cities) != 1:
            raise ValueError("Choose one city for a trip; use status search for multiple cities.")
        if self.mode == "status":
            last_night = self.check_out - timedelta(days=1)
            year_start = self.check_in.year - int(self.check_in.month < 3)
            last_year = last_night.year - int(last_night.month < 3)
            if year_start != last_year:
                raise ValueError(
                    "Status searches must stay within one March–February qualification year."
                )
        if self.target_lp - self.starting_lp > 500000:
            raise ValueError("Search for at most 500,000 additional LP at a time.")
        if len(self.intervals()) * len(self.cities) > 400:
            raise ValueError("Reduce the cities or date window to at most 400 date combinations.")
        return self

    def intervals(self) -> list[tuple[date, date]]:
        nights = (self.check_out - self.check_in).days
        if not self.split_bookings and self.mode == "trip":
            return [(self.check_in, self.check_out)]
        if self.mode == "trip" and self.include_multi_night:
            return [
                (self.check_in + timedelta(days=i), self.check_in + timedelta(days=j))
                for i in range(nights)
                for j in range(i + 1, nights + 1)
            ]
        return [
            (self.check_in + timedelta(days=i), self.check_in + timedelta(days=i + 1))
            for i in range(nights)
        ]


class Plan(BaseModel):
    id: str
    offers: list[Offer]
    cost_cents: int
    hotel_lp: int
    card_lp: int
    partner_bonus_lp: int
    earned_lp: int
    starting_lp: int
    projected_lp: int
    miles: int
    lp_per_dollar: float
    booking_count: int
    hotel_changes: int
    target_met: bool
    shortfall_lp: int
    complete_trip: bool


def plan_for(offers: list[Offer], request: SearchRequest) -> Plan:
    ordered = sorted(offers, key=lambda q: (q.check_in, q.check_out, q.id))
    price = sum(q.price_cents for q in ordered)
    hotel_lp = sum(q.base_lp for q in ordered)
    card_lp = sum(q.price_cents * request.policy.card_lp_per_dollar // 100 for q in ordered)
    bonus = min(request.policy.bonus_remaining, sum(request.policy.bonus_for(q) for q in ordered))
    earned = hotel_lp + card_lp + bonus
    miles = sum(
        q.base_miles + q.bonus_miles + q.price_cents * request.policy.card_miles_per_dollar // 100
        for q in ordered
    )
    cursor, complete = request.check_in, False
    for q in ordered:
        if q.check_in != cursor:
            break
        cursor = q.check_out
    else:
        complete = cursor == request.check_out
    return Plan(
        id=hashlib.sha256("|".join(q.id for q in ordered).encode()).hexdigest()[:20],
        offers=ordered,
        cost_cents=price,
        hotel_lp=hotel_lp,
        card_lp=card_lp,
        partner_bonus_lp=bonus,
        earned_lp=earned,
        starting_lp=request.starting_lp,
        projected_lp=request.starting_lp + earned,
        miles=miles,
        lp_per_dollar=round(earned * 100 / price, 2) if price else 0,
        booking_count=len(ordered),
        hotel_changes=sum(
            a.property_id != b.property_id for a, b in zip(ordered, ordered[1:], strict=False)
        ),
        target_met=request.starting_lp + earned >= request.target_lp,
        shortfall_lp=max(0, request.target_lp - request.starting_lp - earned),
        complete_trip=complete,
    )


def normalize_offer(row: dict, city: str, start: date, end: date) -> Offer | None:
    """Quarantine invalid offers. Never turn an absent price into a free room."""
    try:
        hotel = row["hotel"]
        money = row["grandTotalPublishedPriceInclusiveWithFees"]
        if not isinstance(hotel, dict) or money.get("currency", "USD") != "USD":
            return None
        amount = Decimal(str(money["amount"]))
        if not amount.is_finite():
            return None
        price = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rewards = row["rewards"]
        if isinstance(rewards, bool) or not isinstance(rewards, (int, float)):
            return None
        if not math.isfinite(rewards) or rewards != int(rewards):
            return None
        name = str(hotel["name"])
        # Fallback is explicit until the provider supplies a stable identifier.
        property_id = str(
            hotel.get("id")
            or hotel.get("hotelId")
            or row.get("hotelId")
            or hashlib.sha256(f"{city}:{name}".encode()).hexdigest()[:20]
        )
        rate_id = str(row.get("id") or row.get("rateId") or "")
        refund = row.get("refundability")
        identity = f"{property_id}|{rate_id}|{start}|{end}|{price}|{rewards}|{refund}|{row.get('description', '')}"

        def number(value, high):
            return (
                float(value)
                if isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= high
                else None
            )

        return Offer(
            id=hashlib.sha256(identity.encode()).hexdigest()[:32],
            property_id=property_id,
            rate_id=rate_id[:150],
            name=name,
            city=city,
            check_in=start,
            check_out=end,
            price_cents=price,
            base_lp=int(rewards),
            base_miles=int(rewards),
            refundable=True
            if refund == "REFUNDABLE"
            else False
            if refund == "NON_REFUNDABLE"
            else None,
            stars=number(hotel.get("stars"), 5),
            rating=number(hotel.get("rating"), 10),
            room=str(row.get("description") or "")[:300],
        )
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation, OverflowError):
        return None
