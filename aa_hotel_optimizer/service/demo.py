"""Clearly labeled fictional quotes, using the same optimizer as live searches."""

from ..domain import Offer, SearchRequest


def sample_offers(request: SearchRequest):
    quotes = []
    hotels = [
        ("The Juniper", 16800, 5700, 4),
        ("Parkside House", 12400, 3100, 3),
        ("Meridian Grand", 21900, 6400, 5),
    ]
    for city_index, city in enumerate(request.cities):
        for start, end in request.intervals():
            nights = (end - start).days
            day = (start - request.check_in).days
            for index, (name, price, points, stars) in enumerate(hotels):
                # Multi-night promotions can be less generous than separate bookings.
                cost = (price + (day % 3) * 800 + city_index * 100) * nights
                rewards = int(points * (nights if nights == 1 else 0.72 * nights))
                quotes.append(
                    Offer(
                        id=f"sample-{city_index}-{index}-{start}-{end}",
                        property_id=f"sample-{city_index}-{index}",
                        name=name,
                        city=city,
                        check_in=start,
                        check_out=end,
                        price_cents=cost,
                        base_lp=rewards,
                        base_miles=rewards,
                        refundable=index != 0,
                        stars=stars,
                        rating=8.7 + index / 10,
                        room="Example king room",
                        reward_basis="sample",
                    )
                )
    return quotes
