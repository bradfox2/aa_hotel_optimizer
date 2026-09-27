"""Bounded exact cost selection and complete-trip interval comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .domain import Offer, Plan, SearchRequest, plan_for

MAX_STATES = 30000


class SearchTooComplex(ValueError):
    pass


@dataclass(frozen=True)
class State:
    cost: int = 0
    base: int = 0
    bonus: int = 0
    path: tuple[Offer, ...] = ()

    @property
    def points(self):
        return self.base + self.bonus


def advance(state: State, quote: Offer, request: SearchRequest) -> State:
    return State(
        state.cost + quote.price_cents,
        state.base + quote.base_lp + quote.price_cents * request.policy.card_lp_per_dollar // 100,
        min(request.policy.bonus_remaining, state.bonus + request.policy.bonus_for(quote)),
        state.path + (quote,),
    )


def frontier(states: list[State]) -> list[State]:
    """Discard only cost/base/bonus dominated states, in O(n log n).

    Bonus must be tracked separately: a state that has consumed the promotion
    cap can otherwise incorrectly dominate one with more bonus capacity left.
    """
    ranked = sorted(states, key=lambda s: (-s.base, -s.bonus, s.cost, len(s.path)))
    bonuses = {b: i + 1 for i, b in enumerate(sorted({s.bonus for s in ranked}, reverse=True))}
    bit = [float("inf")] * (len(bonuses) + 1)
    kept = []
    for state in ranked:
        index = bonuses[state.bonus]
        cursor, best = index, float("inf")
        while cursor:
            best = min(best, bit[cursor])
            cursor -= cursor & -cursor
        if best <= state.cost:
            continue
        kept.append(state)
        while index < len(bit):
            bit[index] = min(bit[index], state.cost)
            index += index & -index
    if len(kept) > MAX_STATES:
        raise SearchTooComplex("Too many booking combinations. Narrow the dates or budget.")
    return kept


def eligible(offers: list[Offer], request: SearchRequest) -> list[Offer]:
    intervals = set(request.intervals())
    return list(
        {
            q.id: q
            for q in offers
            if request.check_in <= q.check_in < q.check_out <= request.check_out
            and (q.check_in, q.check_out) in intervals
            and (not request.refundable_only or q.refundable is True)
            and (q.stars or 0) >= request.min_stars
            and (not request.budget_cents or q.price_cents <= request.budget_cents)
        }.values()
    )


def status_plans(offers: list[Offer], request: SearchRequest) -> list[Plan]:
    if request.starting_lp >= request.target_lp:
        return [plan_for([], request)]
    candidates = eligible(offers, request)
    if not candidates:
        return []
    by_day = defaultdict(list)
    for q in candidates:
        by_day[q.check_in].append(q)
    target = request.target_lp - request.starting_lp
    if request.objective == "cost" and request.max_overlaps == 1:
        states = [State()]
        best_cost = request.budget_cents or float("inf")
        for day in sorted(by_day):
            # Booking count affects future feasibility; never prune across counts.
            buckets = defaultdict(list)
            for state in states:
                buckets[len(state.path)].append(state)
                if state.points >= target or len(state.path) >= request.max_bookings:
                    continue
                for q in by_day[day]:
                    new = advance(state, q, request)
                    if new.cost <= best_cost:
                        buckets[len(new.path)].append(new)
                        if new.points >= target:
                            best_cost = min(best_cost, new.cost)
            states = [
                s for group in buckets.values() for s in frontier(group) if s.cost <= best_cost
            ]
            if len(states) > MAX_STATES:
                raise SearchTooComplex("Narrow the date window or target LP for a cost search.")
        feasible = [s for s in states if s.points >= target]
        chosen = sorted(feasible, key=lambda s: (s.cost, len(s.path), -s.points))[:3]
        if not chosen:
            chosen = sorted(states, key=lambda s: (-s.points, s.cost))[:1]
        return [plan_for(list(s.path), request) for s in chosen if s.path]

    def value(q):
        s = advance(State(), q, request)
        return s.points / s.cost

    if request.objective == "fastest":
        ordered = sorted(
            candidates,
            key=lambda q: (q.check_out, -advance(State(), q, request).points, q.price_cents, q.id),
        )
    elif request.objective == "points":
        ordered = sorted(
            candidates, key=lambda q: (-advance(State(), q, request).points, q.price_cents, q.id)
        )
    else:
        ordered = sorted(candidates, key=lambda q: (-value(q), q.price_cents, q.check_in, q.id))
    state, dates = State(), defaultdict(int)
    for q in ordered:
        if state.points >= target or len(state.path) >= request.max_bookings:
            break
        if dates[q.check_in] >= request.max_overlaps:
            continue
        if request.budget_cents and state.cost + q.price_cents > request.budget_cents:
            continue
        state = advance(state, q, request)
        dates[q.check_in] += 1
    return [plan_for(list(state.path), request)] if state.path else []


def trip_plans(offers: list[Offer], request: SearchRequest) -> list[Plan]:
    by_start = defaultdict(list)
    for quote in eligible(offers, request):
        by_start[quote.check_in].append(quote)
    states = {request.check_in: {(None, 0, 0): [State()]}}
    for day in sorted(by_start):
        if day not in states:
            continue
        for (last_hotel, changes, count), paths in list(states[day].items()):
            if count >= request.max_bookings:
                continue
            for quote in by_start[day]:
                new_changes = changes + int(
                    last_hotel is not None and last_hotel != quote.property_id
                )
                if new_changes > request.max_hotel_changes:
                    continue
                bucket = states.setdefault(quote.check_out, {}).setdefault(
                    (quote.property_id, new_changes, count + 1), []
                )
                for state in paths:
                    new = advance(state, quote, request)
                    if not request.budget_cents or new.cost <= request.budget_cents:
                        bucket.append(new)
                if len(bucket) > 1000:
                    bucket[:] = frontier(bucket)
        # Prune only within states that have the same future choices.
        for future_day, groups in states.items():
            if future_day > day:
                for key, group in groups.items():
                    groups[key] = frontier(group)
                if sum(map(len, groups.values())) > MAX_STATES:
                    raise SearchTooComplex(
                        "Narrow the trip preferences to compare fewer combinations."
                    )
    plans = [
        plan_for(list(s.path), request)
        for group in states.get(request.check_out, {}).values()
        for s in group
    ]

    def key(plan):
        if request.objective == "cost":
            return (plan.cost_cents, -plan.earned_lp, plan.booking_count)
        if request.objective == "points":
            return (-plan.earned_lp, plan.cost_cents, plan.booking_count)
        return (-plan.earned_lp / plan.cost_cents, plan.cost_cents, plan.booking_count)

    unique = {p.id: p for p in plans}
    return sorted(unique.values(), key=key)[:5]


def optimize(offers: list[Offer], request: SearchRequest) -> list[Plan]:
    return trip_plans(offers, request) if request.mode == "trip" else status_plans(offers, request)
