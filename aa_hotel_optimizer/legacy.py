"""Compatibility adapters for the original Streamlit and CLI workflows."""

from __future__ import annotations

import shlex
from datetime import datetime, timedelta

from .domain import Offer, RewardPolicy, SearchRequest, normalize_offer, plan_for
from .solver import status_plans


def parse_curl_command(command):
    headers, url = {}, None
    tokens = iter(shlex.split(command.replace("\\\n", " ")))
    for token in tokens:
        if token in ("-H", "--header"):
            value = next(tokens, "")
            if ":" in value:
                key, content = value.split(":", 1)
                if "\n" in content or "\r" in content:
                    raise ValueError("Header values cannot contain line breaks.")
                headers[key.strip().lower()] = content.strip()
        elif token in ("-b", "--cookie"):
            headers["cookie"] = next(tokens, "").strip()
        elif token.startswith(("https://", "http://")) and url is None:
            url = token
    allowed = {"cookie", "x-xsrf-token", "user-agent", "accept", "accept-language"}
    result = {("Cookie" if k == "cookie" else k): v for k, v in headers.items() if k in allowed}
    if any("\n" in v or "\r" in v for v in result.values()):
        raise ValueError("Header values cannot contain line breaks.")
    return url, result


def _policy(stay):
    return RewardPolicy.model_validate(stay.get("reward_policy") or {})


def analyze_hotel_data(
    search_results_data,
    location_name,
    check_in_date_str,
    aa_card_bonus=False,
    aa_card_miles_rate=1,
    miles_value_rate=0.015,
):
    if not isinstance(search_results_data, dict) or not isinstance(
        search_results_data.get("results"), list
    ):
        return []
    start = datetime.strptime(check_in_date_str, "%m/%d/%Y").date()
    rows = []
    for raw in search_results_data["results"]:
        quote = normalize_offer(raw, location_name, start, start + timedelta(days=1))
        if quote is None:
            continue
        card_lp = quote.price_cents // 100 if aa_card_bonus else 0
        card_miles = quote.price_cents * aa_card_miles_rate // 100 if aa_card_bonus else 0
        price = quote.price_cents / 100
        lp, miles = quote.base_lp + card_lp, quote.base_miles + card_miles
        rows.append(
            dict(
                id=quote.id,
                property_id=quote.property_id,
                rate_id=quote.rate_id,
                name=quote.name,
                location=location_name,
                check_in_date=check_in_date_str,
                check_out_date=quote.check_out.strftime("%m/%d/%Y"),
                total_price=price,
                api_points_earned=quote.base_lp,
                card_bonus_points=card_lp,
                points_earned=lp,
                points_per_dollar=lp / price,
                status_bonus_points=0,
                points_earned_final_for_itinerary=lp,
                points_per_dollar_final_for_itinerary=lp / price,
                aa_card_bonus_applied_to_stay=aa_card_bonus,
                aa_card_miles_rate_on_spend=aa_card_miles_rate if aa_card_bonus else 0,
                miles_earned=miles,
                miles_value=miles * miles_value_rate,
                refundability=raw.get("refundability", "UNKNOWN"),
                star_rating=quote.stars or 0,
                user_rating=quote.rating or 0,
                currency="USD",
                observed_at=quote.observed_at.isoformat(),
            )
        )
    return rows


def _quote(stay):
    start = datetime.strptime(stay["check_in_date"], "%m/%d/%Y").date()
    return Offer(
        id=str(stay.get("id") or f"{stay['name']}|{start}|{stay['total_price']}"),
        property_id=str(stay.get("property_id") or stay["name"]),
        name=stay["name"],
        city=stay.get("location", "Unknown"),
        check_in=start,
        check_out=start + timedelta(days=1),
        price_cents=round(stay["total_price"] * 100),
        base_lp=stay["api_points_earned"] + stay.get("card_bonus_points", 0),
        base_miles=stay["api_points_earned"],
    )


def _apply_status_bonus_and_recalculate(stay, projected_lp_before_stay, miles_value_rate=0.015):
    current = stay.copy()
    # Explicit, active promotion eligibility replaces inferred balance thresholds.
    policy = _policy(stay)
    quote = _quote(stay)
    bonus = min(
        policy.bonus_remaining,
        policy.bonus_for(quote.model_copy(update={"base_lp": stay["api_points_earned"]})),
    )
    current["status_bonus_points"] = bonus
    current["points_earned_final_for_itinerary"] = stay["points_earned"] + bonus
    current["points_per_dollar_final_for_itinerary"] = (
        current["points_earned_final_for_itinerary"] / stay["total_price"]
    )
    current["miles_earned"] = stay["api_points_earned"] + (
        round(stay["total_price"] * 100) * stay.get("aa_card_miles_rate_on_spend", 0) // 100
    )
    current["miles_value"] = current["miles_earned"] * miles_value_rate
    return current


def _select(stays, target, current, miles_value, objective, overlaps=1):
    if target - current > 500000:
        raise ValueError("Search for at most 500,000 additional LP at a time.")
    if current >= target:
        return [], 0.0, current
    valid = [s for s in stays if s.get("api_points_earned", 0) > 0 and s.get("total_price", 0) > 0]
    if not valid:
        return [], 0.0, current
    quotes = [_quote(s) for s in valid]
    lookup = {q.id: s for q, s in zip(quotes, valid, strict=True)}
    policy = _policy(valid[0])
    # _quote includes the precomputed card LP. Eligible hotel LP is handled below.
    adjusted = []
    for q in quotes:
        original = lookup[q.id]
        adjusted.append(q.model_copy(update={"base_lp": original["api_points_earned"]}))
    card_rate = 1 if valid[0].get("aa_card_bonus_applied_to_stay") else 0
    policy = policy.model_copy(update={"card_lp_per_dollar": card_rate})
    request = SearchRequest.model_construct(
        mode="status",
        cities=[quotes[0].city],
        check_in=min(q.check_in for q in quotes),
        check_out=max(q.check_out for q in quotes),
        starting_lp=current,
        target_lp=target,
        objective="value" if objective == "cheap" else objective,
        max_bookings=180,
        max_overlaps=max(1, min(overlaps or 5, 20)),
        policy=policy,
    )
    if objective == "cheap":
        picked, used = [], set()
        for q in sorted(adjusted, key=lambda q: (q.price_cents, -q.base_lp, q.id)):
            if plan_for(picked, request).target_met:
                break
            if q.check_in not in used:
                picked.append(q)
                used.add(q.check_in)
        plans = [plan_for(picked, request)]
    else:
        plans = status_plans(adjusted, request)
    if not plans:
        return [], 0.0, current
    rows, remaining = [], policy.bonus_remaining
    for q in plans[0].offers:
        source = dict(
            lookup[q.id],
            reward_policy=policy.model_copy(update={"bonus_remaining": remaining}).model_dump(
                mode="json"
            ),
        )
        calculated = _apply_status_bonus_and_recalculate(source, current, miles_value)
        remaining -= calculated["status_bonus_points"]
        rows.append(calculated)
    return (
        rows,
        sum(s["total_price"] for s in rows),
        current + sum(s["points_earned_final_for_itinerary"] for s in rows),
    )


def select_optimal_stays_ppd(
    all_stays, target_points, current_lp_balance=0, miles_value_rate=0.015
):
    return _select(all_stays, target_points, current_lp_balance, miles_value_rate, "value")


def select_cheapest_stays_for_target_lp(
    all_stays, target_points, current_lp_balance=0, miles_value_rate=0.015
):
    return _select(all_stays, target_points, current_lp_balance, miles_value_rate, "cheap")


def select_optimal_stays_dp(all_stays, target_points, current_lp_balance=0, miles_value_rate=0.015):
    return _select(all_stays, target_points, current_lp_balance, miles_value_rate, "cost")


def select_fastest_calendar_time_lp(
    all_stays, target_points, current_lp_balance=0, max_overlaps=None, miles_value_rate=0.015
):
    return _select(
        all_stays, target_points, current_lp_balance, miles_value_rate, "fastest", max_overlaps
    )
