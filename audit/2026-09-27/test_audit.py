"""Offline evidence for the 2026-09-27 audit; production code is unmodified.

Run from the repository root:
    python audit/2026-09-27/test_audit.py

Expected-failure cases state the desired invariant and reproduce a known defect
or an explicitly identified product gap. Unexpected successes signal that the
audit should be updated. All outbound Requests traffic is blocked. Only
synthetic offers and credentials are used; no AA account or booking is touched.
"""

import importlib
import json
import logging
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
m = importlib.import_module("aa_hotel_optimizer.main")


def offer(name="Hotel", price=100, points=1000, day="10/01/2026", city="Phoenix"):
    return m.analyze_hotel_data(
        {"results": [raw_offer(name, price, points)]}, city, day
    )[0]


def raw_offer(name="Hotel", price=100, points=1000):
    return {
        "hotel": {"name": name, "stars": 4, "rating": 8.5},
        "grandTotalPublishedPriceInclusiveWithFees": {"amount": price},
        "rewards": points,
        "refundability": "REFUNDABLE",
    }


def fake_fetch(day, location, *_args):
    return [offer(day=day.strftime("%m/%d/%Y"), city=location)]


def search(**overrides):
    args = dict(
        city_queries=["Phoenix"],
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        session_headers={},
        target_loyalty_points=1000,
        progress_callback=lambda *_args, **_kwargs: None,
    )
    args.update(overrides)
    with patch.object(
        m, "discover_place_ids", side_effect=lambda query, **_: [(query, "AGODA_CITY:1")]
    ), patch.object(m, "fetch_data_for_date", side_effect=fake_fetch) as fetch:
        result = m.find_best_hotel_deals(**args)
        return result, fetch.call_args_list


class Baseline(unittest.TestCase):
    def test_bash_curl_headers_parse_without_execution(self):
        url, headers = m.parse_curl_command(
            "curl 'https://www.aadvantagehotels.com/test' "
            "-H 'accept: application/json' -b 'session=synthetic-only'"
        )
        self.assertEqual(url, "https://www.aadvantagehotels.com/test")
        self.assertEqual(headers["Cookie"], "session=synthetic-only")

    def test_card_lp_and_card_miles_are_separate_before_status(self):
        stay = m.analyze_hotel_data(
            {"results": [raw_offer()]}, "Phoenix", "10/01/2026",
            aa_card_bonus=True, aa_card_miles_rate=10,
        )[0]
        self.assertEqual(stay["points_earned"], 1100)
        self.assertEqual(stay["miles_earned"], 2000)

    def test_backend_actually_processes_multiple_cities(self):
        result, calls = search(city_queries=["Phoenix", "Tucson"])
        self.assertEqual({s["location"] for s in result[0]}, {"Phoenix", "Tucson"})
        self.assertEqual(len(calls), 2)

    def test_all_python_files_parse(self):
        import ast
        for p in [ROOT / "streamlit_app.py", *sorted((ROOT / "aa_hotel_optimizer").glob("*.py")),
                  *sorted((ROOT / "pages").glob("*.py"))]:
            ast.parse(p.read_text())


class CalculationDefects(unittest.TestCase):
    @unittest.expectedFailure
    def test_F02_active_2026_partner_bonus_is_25_percent(self):
        # Scenario assumes the customer registered and is inside their window/cap.
        result = m._apply_status_bonus_and_recalculate(offer(), 60000)
        self.assertEqual(result["status_bonus_points"], 250)

    @unittest.expectedFailure
    def test_F03_partner_lp_bonus_does_not_create_redeemable_miles(self):
        result = m._apply_status_bonus_and_recalculate(offer(), 60000)
        self.assertEqual(result["miles_earned"], 1000)

    @unittest.expectedFailure
    def test_F04_ppd_returns_balance_including_starting_lp(self):
        _, _, points = m.select_optimal_stays_ppd([offer()], 51000, 50000)
        self.assertEqual(points, 51000)

    @unittest.expectedFailure
    def test_F04_cheapest_returns_balance_including_starting_lp(self):
        _, _, points = m.select_cheapest_stays_for_target_lp([offer()], 51000, 50000)
        self.assertEqual(points, 51000)

    def chronological_case(self, strategy):
        stays = [offer("Earlier", 100, 10000, "10/01/2026"),
                 offer("Later", 10, 2000, "10/02/2026")]
        itinerary, _, _ = strategy(stays, 73000, 59000)
        # Check internal consistency even under the app's legacy rules.
        running = 59000
        for chosen in itinerary:
            original = next(s for s in stays if s["name"] == chosen["name"])
            calculated = m._apply_status_bonus_and_recalculate(original, running)
            self.assertEqual(chosen["status_bonus_points"], calculated["status_bonus_points"])
            running += calculated["points_earned_final_for_itinerary"]

    @unittest.expectedFailure
    def test_F05_ppd_bonus_respects_chronological_order(self):
        self.chronological_case(m.select_optimal_stays_ppd)

    @unittest.expectedFailure
    def test_F05_cheapest_bonus_respects_chronological_order(self):
        self.chronological_case(m.select_cheapest_stays_for_target_lp)

    @unittest.expectedFailure
    def test_F06_dp_does_not_discard_a_cheaper_sufficient_offer(self):
        stays = [offer("Sufficient", 100, 1000), offer("Expensive", 1000, 1100)]
        _, cost, _ = m.select_optimal_stays_dp(stays, 1000)
        self.assertEqual(cost, 100)

    @unittest.expectedFailure
    def test_F07_dp_recognizes_an_attainable_target_with_bonus(self):
        itinerary, _, _ = m.select_optimal_stays_dp([offer()], 61200, 60000)
        self.assertEqual(len(itinerary), 1)

    @unittest.expectedFailure
    def test_F04_iterative_search_stops_when_overall_target_is_met(self):
        _, calls = search(
            target_loyalty_points=51000, current_lp_balance=50000,
            iterative_search_for_lp_target=True, max_search_days_iterative=3,
        )
        self.assertEqual(len(calls), 1)


class FixedTripProductGaps(unittest.TestCase):
    @unittest.expectedFailure
    def test_F01_a_weeklong_trip_covers_every_night(self):
        result, _ = search(end_date=date(2026, 10, 7))
        actual = {s["check_in_date"] for s in result[1]}
        expected = {(date(2026, 10, 1) + timedelta(days=i)).strftime("%m/%d/%Y") for i in range(7)}
        self.assertEqual(actual, expected)

    @unittest.expectedFailure
    def test_F01_checkout_date_is_exclusive_for_a_trip(self):
        # Current UI calls this "End Date": this case records a NEW trip contract,
        # not a claim that its existing inclusive search-window contract is broken.
        _, calls = search(end_date=date(2026, 10, 8))
        self.assertEqual(len(calls), 7)

    @unittest.expectedFailure
    def test_F01_search_also_prices_the_continuous_stay(self):
        with patch.object(m, "discover_place_ids", return_value=[("Phoenix", "AGODA_CITY:1")]), \
             patch.object(m, "search_aadvantage_hotels", return_value="synthetic") as start, \
             patch.object(m, "get_hotel_results", return_value={"results": [raw_offer()]}):
            m.find_best_hotel_deals(
                ["Phoenix"], date(2026, 10, 1), date(2026, 10, 4), {}, 1000,
                progress_callback=lambda *_args, **_kwargs: None,
            )
        intervals = {(c.args[0], c.args[1]) for c in start.call_args_list}
        self.assertIn(("10/01/2026", "10/04/2026"), intervals)


class DataAndSecurityDefects(unittest.TestCase):
    @unittest.expectedFailure
    def test_F08_result_fetch_visits_more_than_first_page(self):
        # Synthetic paged provider response; real pagination fields need fixtures.
        response = {"results": [raw_offer(str(i)) for i in range(45)], "totalResults": 90}
        with patch.object(m, "search_aadvantage_hotels", return_value="synthetic"), \
             patch.object(m, "get_hotel_results", return_value=response) as get:
            m.fetch_data_for_date(date(2026, 10, 1), "Phoenix", "AGODA_CITY:1", {})
        self.assertGreater(get.call_count, 1)

    @unittest.expectedFailure
    def test_F09_malformed_offer_does_not_discard_valid_offers(self):
        rows = m.analyze_hotel_data(
            {"results": [raw_offer(), {"hotel": None}]}, "Phoenix", "10/01/2026"
        )
        self.assertEqual(len(rows), 1)

    @unittest.expectedFailure
    def test_F09_unknown_price_is_not_a_free_stay(self):
        row = raw_offer()
        del row["grandTotalPublishedPriceInclusiveWithFees"]
        stays = m.analyze_hotel_data({"results": [row]}, "Phoenix", "10/01/2026")
        itinerary, _, _ = m.select_optimal_stays_ppd(stays, 1000)
        self.assertEqual(itinerary, [])

    @unittest.expectedFailure
    def test_F10_double_quoted_curl_preserves_headers(self):
        _, headers = m.parse_curl_command(
            'curl "https://www.aadvantagehotels.com/test" -H "Cookie: session=synthetic"'
        )
        self.assertEqual(headers.get("Cookie"), "session=synthetic")

    @unittest.expectedFailure
    def test_F11_invalid_header_error_does_not_log_secret(self):
        secret = "synthetic-audit-secret-not-a-real-token"
        with self.assertLogs(level="ERROR") as logs:
            m.search_aadvantage_hotels(
                "10/01/2026", "10/02/2026", "Phoenix", "AGODA_CITY:1",
                session_headers={"Cookie": " " + secret},
            )
        self.assertNotIn(secret, "\n".join(logs.output))

    @unittest.expectedFailure
    def test_F12_initial_window_respects_configured_search_horizon(self):
        _, calls = search(
            end_date=date(2026, 10, 11), max_search_days_iterative=2,
            iterative_search_for_lp_target=True,
        )
        self.assertLessEqual(len(calls), 3)


class StreamlitBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from streamlit.testing.v1 import AppTest
        cls.AppTest = AppTest

    def app(self):
        return self.AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=15).run()

    def test_initial_app_and_secondary_pages_render(self):
        self.assertFalse(self.app().exception)
        for p in (ROOT / "pages").glob("*.py"):
            self.assertFalse(self.AppTest.from_file(str(p)).run().exception)

    @unittest.expectedFailure
    def test_F13_results_survive_a_widget_rerun(self):
        app = self.app()
        stay = offer()
        with patch.object(m, "find_best_hotel_deals", return_value=([stay], [stay], 100, 1000)):
            app.sidebar.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 6)
            app.sidebar.number_input(key="miles_value_cents_input").set_value(2.0).run()
        self.assertEqual(len(app.metric), 6)

    @unittest.expectedFailure
    def test_F14_missing_credentials_stops_personalized_search(self):
        app = self.app()
        with patch.object(m, "find_best_hotel_deals", return_value=([], [], 0, 0)) as backend:
            app.sidebar.button[0].click().run()
        backend.assert_not_called()

    @unittest.expectedFailure
    def test_F15_incomplete_itinerary_has_an_explicit_shortfall(self):
        app = self.app()
        stay = offer()
        with patch.object(m, "find_best_hotel_deals", return_value=([stay], [stay], 100, 1000)):
            app.sidebar.button[0].click().run()
        messages = [x.value for kind in ("warning", "error", "info") for x in app.get(kind)]
        self.assertTrue(any("shortfall" in v.lower() or "target not met" in v.lower() for v in messages))


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.CRITICAL)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    with patch("requests.sessions.Session.send", side_effect=AssertionError("Network is forbidden in audit tests")):
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "tests_run": result.testsRun,
        "passed": result.testsRun - len(result.expectedFailures) - len(result.failures) - len(result.errors) - len(result.unexpectedSuccesses) - len(result.skipped),
        "known_invariant_failures": [
            {"test": t.id(), "failure": trace.strip().splitlines()[-1]}
            for t, trace in result.expectedFailures
        ],
        "unexpected_failures": [t.id() for t, _ in result.failures],
        "unexpected_errors": [t.id() for t, _ in result.errors],
        "unexpected_successes": [t.id() for t in result.unexpectedSuccesses],
        "all_network_requests_blocked": True,
        "synthetic_credentials_only": True,
    }
    Path(__file__).with_name("test-results.json").write_text(json.dumps(summary, indent=2) + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
