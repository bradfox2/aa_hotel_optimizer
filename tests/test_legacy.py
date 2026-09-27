from datetime import date

from aa_hotel_optimizer import main
from aa_hotel_optimizer.legacy import (
    analyze_hotel_data,
    parse_curl_command,
    select_optimal_stays_ppd,
)


def raw_offer(id, price=100, points=1000):
    return {
        "id": id,
        "hotel": {"id": id, "name": "Test Hotel"},
        "rewards": points,
        "grandTotalPublishedPriceInclusiveWithFees": {"amount": price, "currency": "USD"},
    }


def test_legacy_contract_and_malformed_quote_quarantine():
    rows = analyze_hotel_data(
        {"results": [raw_offer("good"), {}, raw_offer("bad", price=0)]}, "Phoenix", "10/10/2026"
    )
    assert len(rows) == 1
    itinerary, cost, balance = select_optimal_stays_ppd(rows, 1500, 500)
    assert len(itinerary) == 1 and cost == 100 and balance == 1500


def test_both_browser_curl_styles_are_parsed_without_execution():
    url, headers = parse_curl_command(
        'curl "https://www.aadvantagehotels.com/rest/test" -H "X-XSRF-TOKEN: example" -b "SESSION=example" -H "Host: evil.example"'
    )
    assert url.startswith("https://www.aadvantagehotels.com/")
    assert headers["Cookie"] == "SESSION=example" and "Host" not in headers


def test_legacy_pagination_and_initial_horizon(monkeypatch):
    pages = []
    monkeypatch.setattr(main, "search_aadvantage_hotels", lambda *args, **kwargs: "uuid")

    def get(*args, **kwargs):
        page = kwargs["page_number"]
        pages.append(page)
        return {
            "results": [raw_offer(str(i)) for i in range(45)] if page == 1 else [raw_offer("last")]
        }

    monkeypatch.setattr(main, "get_hotel_results", get)
    assert len(main.fetch_data_for_date(date(2026, 10, 10), "Phoenix", "id", {})) == 46
    assert pages == [1, 2]
    dates = []
    monkeypatch.setattr(
        main, "discover_place_ids", lambda *args, **kwargs: [("Phoenix", "AGODA_CITY_1")]
    )
    monkeypatch.setattr(main, "fetch_data_for_date", lambda day, *args: dates.append(day) or [])
    main.find_best_hotel_deals(
        ["Phoenix"],
        date(2026, 10, 10),
        date(2026, 11, 10),
        {},
        1000,
        iterative_search_for_lp_target=True,
        max_search_days_iterative=2,
    )
    assert sorted(dates) == [date(2026, 10, 10), date(2026, 10, 11)]
