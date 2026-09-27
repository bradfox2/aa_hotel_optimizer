import itertools
import random
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from aa_hotel_optimizer.domain import Offer, RewardPolicy, SearchRequest, normalize_offer, plan_for
from aa_hotel_optimizer.solver import optimize

START = date(2026, 10, 10)


def quote(id="a", day=0, nights=1, price=10000, points=1000, hotel="one"):
    return Offer(
        id=id,
        property_id=hotel,
        name=hotel,
        city="Phoenix",
        check_in=START + timedelta(days=day),
        check_out=START + timedelta(days=day + nights),
        price_cents=price,
        base_lp=points,
        base_miles=points,
        stars=4,
    )


def request(**kwargs):
    return SearchRequest(
        **(
            {
                "mode": "status",
                "cities": ["Phoenix"],
                "check_in": START,
                "check_out": START + timedelta(days=4),
                "target_lp": 1000,
                "objective": "cost",
            }
            | kwargs
        )
    )


def test_cheaper_offer_on_same_date_is_retained():
    result = optimize([quote(), quote("expensive", price=100000, points=1100)], request())[0]
    assert result.cost_cents == 10000
    assert result.earned_lp == 1000


def test_balance_consistency_and_already_qualified():
    result = optimize([quote()], request(starting_lp=500, target_lp=1500))[0]
    assert result.earned_lp == 1000
    assert result.projected_lp == 1500
    assert optimize([quote()], request(starting_lp=1500, target_lp=1500))[0].offers == []


def test_active_bonus_is_dated_capped_and_not_redeemable_miles():
    policy = RewardPolicy(
        partner_bonus_percent=25,
        bonus_start=START,
        bonus_end=START,
        bonus_remaining=200,
        card_lp_per_dollar=1,
        card_miles_per_dollar=2,
    )
    plan = plan_for([quote(), quote("next", day=1)], request(policy=policy))
    assert plan.partner_bonus_lp == 200
    assert plan.card_lp == 200
    assert plan.miles == 2400
    assert plan.earned_lp == 2400
    assert plan_for([quote()], request(starting_lp=100000)).partner_bonus_lp == 0


def test_bonus_can_make_target_feasible():
    policy = RewardPolicy(partner_bonus_percent=25, bonus_start=START, bonus_end=START)
    assert optimize([quote()], request(target_lp=1250, policy=policy))[0].target_met


def test_exact_cost_matches_exhaustive_small_searches():
    rng = random.Random(481)
    for case in range(45):
        groups = [
            [
                quote(
                    f"{case}-{day}-{i}",
                    day=day,
                    price=rng.randrange(50, 300) * 100,
                    points=rng.randrange(3, 20) * 100,
                )
                for i in range(3)
            ]
            for day in range(4)
        ]
        policy = RewardPolicy(
            partner_bonus_percent=25,
            bonus_start=START,
            bonus_end=START + timedelta(days=2),
            bonus_remaining=rng.randrange(1, 10) * 100,
        )
        req = request(target_lp=rng.randrange(10, 40) * 100, max_bookings=3, policy=policy)
        possible = []
        for combination in itertools.product(*[[None] + group for group in groups]):
            picked = [q for q in combination if q]
            if len(picked) <= req.max_bookings:
                plan = plan_for(picked, req)
                if plan.target_met:
                    possible.append(plan.cost_cents)
        actual = optimize([q for group in groups for q in group], req)
        if possible:
            assert actual[0].target_met
            assert actual[0].cost_cents == min(possible)
        elif actual:
            assert not actual[0].target_met


def test_trip_covers_every_night_and_compares_split_to_full_stay():
    req = request(mode="trip", check_out=START + timedelta(days=3), objective="points")
    offers = [quote("full", nights=3, price=25000, points=1800)] + [
        quote(str(day), day=day) for day in range(3)
    ]
    best = optimize(offers, req)[0]
    assert best.booking_count == 3 and best.complete_trip and best.earned_lp == 3000
    assert optimize(offers, req.model_copy(update={"split_bookings": False}))[0].booking_count == 1
    assert not optimize(
        offers[:1] + offers[2:], req.model_copy(update={"include_multi_night": False})
    )


def test_hotel_changes_and_budget_are_constraints():
    req = request(mode="trip", check_out=START + timedelta(days=2), objective="points")
    offers = [quote("first"), quote("second", day=1, hotel="two")]
    assert not optimize(offers, req)
    assert optimize(offers, req.model_copy(update={"max_hotel_changes": 1}))[0].hotel_changes == 1
    assert not optimize(
        offers, req.model_copy(update={"max_hotel_changes": 1, "budget_cents": 15000})
    )


@pytest.mark.parametrize("amount", [None, 0, -1, "NaN", "Infinity", "invalid"])
def test_invalid_quotes_never_become_free_rooms(amount):
    row = {
        "hotel": {"id": "1", "name": "Test"},
        "rewards": 1000,
        "grandTotalPublishedPriceInclusiveWithFees": {"amount": amount},
    }
    assert normalize_offer(row, "Phoenix", START, START + timedelta(days=1)) is None


def test_input_bounds():
    with pytest.raises(ValidationError):
        request(target_lp=500001)
    with pytest.raises(ValidationError):
        request(mode="trip", check_out=START + timedelta(days=15))
    with pytest.raises(ValidationError):
        RewardPolicy(partner_bonus_percent=25)
    with pytest.raises(ValidationError, match="qualification year"):
        request(check_in=date(2027, 2, 25), check_out=date(2027, 3, 5))
