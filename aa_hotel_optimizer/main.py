import argparse
import concurrent.futures  # Added import
import json
import logging
import sys
import urllib.parse
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import (  # Changed callable to Callable
    Any,
)

import requests
from tqdm import tqdm

from aa_hotel_optimizer.legacy import (
    _apply_status_bonus_and_recalculate as _apply_status_bonus_and_recalculate,
)
from aa_hotel_optimizer.legacy import (
    analyze_hotel_data,
    select_cheapest_stays_for_target_lp,
    select_fastest_calendar_time_lp,
    select_optimal_stays_dp,
    select_optimal_stays_ppd,
)
from aa_hotel_optimizer.legacy import parse_curl_command as parse_curl_command

results_logger = logging.getLogger("aa_hotel_optimizer.results")
logger = logging.getLogger(__name__)

# Constants for API interaction
PLACES_API_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/places"
SEARCH_API_BASE_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest"
RESULTS_API_BASE_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/search"


def _safe_headers(headers):
    allowed = {"cookie", "x-xsrf-token", "accept", "accept-language", "user-agent"}
    safe = {}
    for name, value in headers.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("Invalid request headers.")
        if name.lower() in allowed:
            safe[name] = value
    return safe


def discover_place_ids(
    query: str, session_headers: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """
    Discovers place IDs (primarily AGODA_CITY type) for a given query string.
    Returns a list of (name, place_id) tuples.
    """
    discovered_places: dict[str, str] = {}
    params = {
        "query": query,
        "source": "AGODA",
        "language": "en",
        "includeHotelNames": "true",
    }
    request_headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    if session_headers:
        request_headers.update(_safe_headers(session_headers))

    response = None
    try:
        logger.info(f"Discovering place IDs for query: '{query}'...")
        response = requests.get(
            PLACES_API_URL,
            params=params,
            headers=request_headers,
            allow_redirects=False,
            timeout=10,
        )
        response.raise_for_status()
        places_data = response.json()

        if not isinstance(places_data, list):
            logger.warning(
                f"Places API did not return a list for query '{query}'. Unexpected response format."
            )
            return []

        for place in places_data:
            place_id = place.get("id")
            name = place.get("name")
            description = place.get("description", "").lower()
            place_type = place.get("type")

            if place_id and name:  # name is guaranteed to be a string here
                if place_type == "AGODA_CITY":
                    if query.lower() in name.lower() or query.lower() in description:
                        # Ensure the value from discovered_places.get is also treated as string for len
                        existing_name_in_dict = discovered_places.get(place_id)
                        default_comparison_len = (
                            len(name * 2) if name else 0
                        )  # Should not happen due to 'if name'

                        current_name_len = len(name) if name else 0

                        len_to_compare = (
                            len(existing_name_in_dict)
                            if existing_name_in_dict is not None
                            else default_comparison_len
                        )

                        if place_id not in discovered_places or current_name_len < len_to_compare:
                            discovered_places[place_id] = name
                elif place_type == "AGODA_AREA" and query.lower() in name.lower():
                    existing_name_in_dict_area = discovered_places.get(place_id)
                    current_name_len_area = len(name) if name else 0

                    len_to_compare_area = (
                        len(existing_name_in_dict_area)
                        if existing_name_in_dict_area is not None
                        else (current_name_len_area + 1)
                    )  # ensure it's greater if not present

                    if place_id not in discovered_places or (
                        place_id in discovered_places
                        and current_name_len_area < len_to_compare_area
                        and "AGODA_CITY" not in place_id
                    ):
                        discovered_places[place_id] = name

        if not discovered_places:
            logger.warning(f"No suitable place IDs found for query '{query}' in the API response.")

    except requests.exceptions.RequestException as e:
        logger.error(f"Error during place ID discovery for '{query}': {type(e).__name__}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from places API for '{query}'. Invalid JSON response.")
    return [(name, place_id) for place_id, name in discovered_places.items()]


def search_aadvantage_hotels(
    check_in_date: str,
    check_out_date: str,
    location: str,
    place_id: str,
    adults: int = 1,
    children: int = 0,
    rooms: int = 1,
    session_headers: dict[str, str] | None = None,
) -> str | None:
    params = {
        "adults": adults,
        "checkIn": check_in_date,
        "checkOut": check_out_date,
        "children": children,
        "currency": "USD",
        "language": "en",
        "locationType": "CITY",
        "mode": "earn",
        "numberOfChildren": children,
        "placeId": place_id,
        "program": "aadvantage",
        "promotion": "",
        "query": location,
        "rooms": rooms,
        "source": "AGODA",
    }
    encoded_params = urllib.parse.urlencode(params)
    url = f"{SEARCH_API_BASE_URL}?{encoded_params}"
    request_headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    if session_headers:
        request_headers.update(_safe_headers(session_headers))
    response_obj = None
    search_uuid = None
    try:
        response_obj = requests.get(url, headers=request_headers, allow_redirects=False, timeout=15)
        response_obj.raise_for_status()
        data = response_obj.json()
        search_uuid = data.get("uuid")
        if not search_uuid:
            logger.error(
                f"Error initiating search for {location} ({check_in_date}-{check_out_date}): 'uuid' not found. Unexpected response format."
            )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during search initiation for {location}: {type(e).__name__}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from search initiation for {location}")
    return search_uuid


def get_hotel_results(
    search_id: str,
    location_name: str,
    check_in_date: str,
    page_size: int = 45,
    page_number: int = 1,
    session_headers: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    url = f"{RESULTS_API_BASE_URL}/{search_id}"
    params = {
        "hotelImageHeight": 368,
        "hotelImageWidth": 704,
        "pageSize": page_size,
        "pageNumber": page_number,
    }
    encoded_params = urllib.parse.urlencode(params)
    full_url = f"{url}?{encoded_params}"
    request_headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    if session_headers:
        request_headers.update(_safe_headers(session_headers))
    response = None
    try:
        response = requests.get(
            full_url, headers=request_headers, allow_redirects=False, timeout=20
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting hotel results for search ID {search_id}: {type(e).__name__}")
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from hotel results for search ID {search_id}")
    return None


def print_hotel_values_summary(hotels_value: list[dict[str, Any]], limit: int = 20):
    if not hotels_value:
        results_logger.info("No hotel values to display.")
        return
    hotels_value.sort(
        key=lambda x: (
            x.get("points_per_dollar_final_for_itinerary", x.get("points_per_dollar", 0)),
            -x["total_price"],
        ),
        reverse=True,
    )
    results_logger.info("\n===== Top AAdvantage Points Value Hotels (Based on LP PPD) =====")
    header = f"{'Hotel Name':<35} {'Loc':<15} {'Date':<10} {'Price':<8} {'LP':<8} {'LP PPD':<7} {'Miles':<8} {'Val($)':<7} {'Refund':<8}"
    results_logger.info(header)
    results_logger.info("=" * len(header))
    for i, hotel in enumerate(hotels_value):
        if i >= limit:
            break
        final_lp = hotel.get("points_earned_final_for_itinerary", hotel.get("points_earned"))
        final_lp_ppd = hotel.get(
            "points_per_dollar_final_for_itinerary", hotel.get("points_per_dollar")
        )
        miles_earned_display = hotel.get("miles_earned", 0)
        miles_value_display = hotel.get("miles_value", 0.0)
        results_logger.info(
            f"{hotel['name']:<35.35} {hotel['location']:<15.15} {hotel['check_in_date']:<10} "
            f"${hotel['total_price']:<7.2f} {final_lp:<8} "
            f"{final_lp_ppd:<7.2f} {miles_earned_display:<8} ${miles_value_display:<6.2f} "
            f"{hotel['refundability'] == 'REFUNDABLE'!s:<8}"
        )
    if hotels_value:
        best_overall_value = hotels_value[0]
        final_lp_best = best_overall_value.get(
            "points_earned_final_for_itinerary", best_overall_value.get("points_earned")
        )
        final_lp_ppd_best = best_overall_value.get(
            "points_per_dollar_final_for_itinerary",
            best_overall_value.get("points_per_dollar"),
        )
        miles_earned_best = best_overall_value.get("miles_earned", 0)
        miles_value_best = best_overall_value.get("miles_value", 0.0)

        results_logger.info(
            "\n🏆 OVERALL BEST SINGLE STAY VALUE (from this batch, considering all bonuses):"
        )
        results_logger.info(
            f"{best_overall_value['name']} in {best_overall_value['location']} on {best_overall_value['check_in_date']}"
        )
        results_logger.info(
            f"  Offers {final_lp_ppd_best:.2f} LP per dollar. Pay ${best_overall_value['total_price']:.2f}, earn {final_lp_best} LP."
        )
        results_logger.info(
            f"  Also earns {miles_earned_best} miles, valued at ${miles_value_best:.2f}."
        )


def generate_date_range(start_date: date, end_date: date) -> list[date]:
    dates: list[date] = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    return dates


def fetch_data_for_date(
    current_date: date,
    actual_location_name_used: str,
    target_place_id: str,
    session_headers: dict[str, str],
    aa_card_bonus: bool = False,
    aa_card_miles_rate: int = 1,  # Added parameter
    miles_value_rate: float = 0.015,  # New parameter
) -> list[dict[str, Any]]:
    check_in_date_str = current_date.strftime("%m/%d/%Y")
    check_out_date_str = (current_date + timedelta(days=1)).strftime("%m/%d/%Y")
    hotel_stays_on_date: list[dict[str, Any]] = []

    search_uuid = search_aadvantage_hotels(
        check_in_date_str,
        check_out_date_str,
        actual_location_name_used,
        target_place_id,
        session_headers=session_headers,
    )

    if search_uuid:
        seen = set()
        for page in range(1, 21):
            results_data = get_hotel_results(
                search_uuid,
                actual_location_name_used,
                check_in_date_str,
                page_number=page,
                session_headers=session_headers,
            )
            if not results_data or not isinstance(results_data.get("results"), list):
                raise ValueError("Hotel results were unavailable. Try the search again.")
            if results_data.get("complete") is False:
                raise ValueError("Hotel results are still pending. Try the search again.")
            rows = analyze_hotel_data(
                results_data,
                actual_location_name_used,
                check_in_date_str,
                aa_card_bonus=aa_card_bonus,
                aa_card_miles_rate=aa_card_miles_rate,
                miles_value_rate=miles_value_rate,
            )
            new = [row for row in rows if row["id"] not in seen]
            hotel_stays_on_date.extend(new)
            seen.update(row["id"] for row in new)
            if len(results_data["results"]) < 45:
                break
            if not new or page == 20:
                raise ValueError("Could not verify all hotel result pages. Narrow the search.")
    else:
        raise ValueError("Hotel search could not be started. Check your session and try again.")
    return hotel_stays_on_date


def find_best_hotel_deals(
    city_queries: list[str],
    start_date: date,
    end_date: date,
    session_headers: dict[str, str],
    target_loyalty_points: int,
    progress_callback: Callable | None = None,  # Changed to Callable
    aa_card_bonus: bool = False,
    aa_card_miles_rate: int = 1,  # Added default value
    optimization_strategy: str = "points_per_dollar",
    iterative_search_for_lp_target: bool = False,
    max_search_days_iterative: int = 180,
    current_lp_balance: int = 0,
    max_overlaps: int | None = None,  # New parameter
    miles_value_rate: float = 0.015,  # New parameter
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float, int]:
    if not city_queries or len(city_queries) > 26:
        raise ValueError("Choose between 1 and 26 cities.")
    if not 0 <= target_loyalty_points - current_lp_balance <= 500000:
        if current_lp_balance >= target_loyalty_points:
            return [], [], 0.0, current_lp_balance
        raise ValueError("Search for at most 500,000 additional LP.")
    if end_date < start_date or not 1 <= max_search_days_iterative <= 180:
        raise ValueError("Choose a valid date window and a horizon of 1–180 days.")
    horizon = (
        max_search_days_iterative
        if iterative_search_for_lp_target
        else (end_date - start_date).days + 1
    )
    if horizon > 180 or horizon * len(city_queries) > 400:
        raise ValueError("Limit the search to 180 days and 400 city/date combinations.")
    if iterative_search_for_lp_target:
        end_date = min(end_date, start_date + timedelta(days=max_search_days_iterative - 1))
    all_hotel_options_global: list[dict[str, Any]] = []
    final_itinerary: list[dict[str, Any]] = []
    total_cost: float = 0.0
    running_total_lp_achieved = current_lp_balance

    current_search_pass_start_date = start_date
    current_search_pass_end_date = end_date

    max_iterations_passes = 12
    current_iteration_pass = 0
    absolute_max_end_date_for_search = start_date + timedelta(days=max_search_days_iterative - 1)

    while True:
        current_iteration_pass += 1
        if iterative_search_for_lp_target and current_iteration_pass > max_iterations_passes:
            logger.warning(
                f"Iterative search reached max passes ({max_iterations_passes}). Stopping."
            )
            break
        if (
            iterative_search_for_lp_target
            and current_search_pass_start_date > absolute_max_end_date_for_search
        ):
            logger.warning(
                f"Iterative search reached max search horizon ({absolute_max_end_date_for_search.strftime('%m/%d/%Y')}). Stopping."
            )
            break

        hotel_options_this_pass: list[dict[str, Any]] = []
        date_range_chunk_for_pass = generate_date_range(
            current_search_pass_start_date, current_search_pass_end_date
        )

        if not date_range_chunk_for_pass:
            if (
                not iterative_search_for_lp_target
                or current_search_pass_start_date > current_search_pass_end_date
            ):
                logger.info("No more valid dates in the current or initial window.")
                break

        logger.info(
            f"\n--- Iteration Pass {current_iteration_pass}: Searching Date Window "
            f"{current_search_pass_start_date.strftime('%m/%d/%Y')} to "
            f"{current_search_pass_end_date.strftime('%m/%d/%Y')} ---"
        )

        for city_idx, current_city_query in enumerate(city_queries):
            logger.info(
                f"\nProcessing city {city_idx + 1}/{len(city_queries)}: '{current_city_query}' for current date window..."
            )

            discovered_locations = discover_place_ids(
                query=current_city_query, session_headers=session_headers
            )
            target_place_id: str | None = None
            actual_location_name_used_for_city = current_city_query

            if discovered_locations:
                best_city_match: tuple[str, str] | None = None
                for name, place_id_val in discovered_locations:
                    if "AGODA_CITY" in place_id_val.upper():
                        if current_city_query.lower() in name.lower():
                            if best_city_match is None or len(name) < len(best_city_match[0]):
                                best_city_match = (name, place_id_val)
                        elif best_city_match is None:
                            best_city_match = (name, place_id_val)

                if best_city_match:
                    actual_location_name_used_for_city, target_place_id = best_city_match
                    logger.info(
                        f"Selected place ID for '{actual_location_name_used_for_city}': {target_place_id}"
                    )
                elif discovered_locations:
                    actual_location_name_used_for_city, target_place_id = discovered_locations[0]
                    logger.warning(
                        f"Using first discovered place ID as fallback for '{current_city_query}': {target_place_id} ({actual_location_name_used_for_city})"
                    )

            if not target_place_id:
                raise ValueError("A city could not be resolved. Use a more specific city name.")

            if not date_range_chunk_for_pass:
                logger.warning(
                    f"No dates to process for {actual_location_name_used_for_city}. Skipping."
                )
                if progress_callback:
                    progress_callback(
                        0,
                        0,
                        current_iteration_pass,
                        current_search_pass_end_date.strftime("%m/%d/%Y"),
                        city_idx + 1,
                        len(city_queries),
                        current_city_query,
                        is_final_city_in_pass=(city_idx + 1 == len(city_queries)),
                        status_message="No dates in range",
                    )
                continue

            logger.info(
                f"Searching Hotels in {actual_location_name_used_for_city} (Place ID: {target_place_id}) for dates {current_search_pass_start_date.strftime('%m/%d/%Y')} to {current_search_pass_end_date.strftime('%m/%d/%Y')}"
            )

            num_workers = min(3, len(date_range_chunk_for_pass))
            if num_workers == 0:
                num_workers = 1

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                future_to_date = {
                    executor.submit(
                        fetch_data_for_date,
                        current_date_in_chunk,
                        actual_location_name_used_for_city,
                        target_place_id,
                        session_headers,
                        aa_card_bonus,
                        aa_card_miles_rate,  # Pass down
                        miles_value_rate,  # Pass down
                    ): current_date_in_chunk
                    for current_date_in_chunk in date_range_chunk_for_pass
                }

                completed_dates_for_city = 0
                total_dates_for_city = len(date_range_chunk_for_pass)

                for future in tqdm(
                    concurrent.futures.as_completed(future_to_date),
                    total=total_dates_for_city,
                    desc=f"Pass {current_iteration_pass}, City {city_idx + 1}/{len(city_queries)} ({actual_location_name_used_for_city})",
                    file=sys.stderr,
                    disable=(progress_callback is not None),
                ):
                    try:
                        stays_on_date = future.result()
                        if stays_on_date:
                            hotel_options_this_pass.extend(stays_on_date)
                    except Exception as exc:
                        for pending in future_to_date:
                            pending.cancel()
                        logger.error("Search incomplete: %s", type(exc).__name__)
                        raise RuntimeError(
                            "Some dates could not be fetched. Start a fresh search."
                        ) from None
                    finally:
                        completed_dates_for_city += 1
                        if progress_callback:
                            progress_callback(
                                completed_dates_for_city,
                                total_dates_for_city,
                                current_iteration_pass,
                                current_search_pass_end_date.strftime("%m/%d/%Y"),
                                city_idx + 1,
                                len(city_queries),
                                actual_location_name_used_for_city,
                                is_final_city_in_pass=(city_idx + 1 == len(city_queries)),
                            )

        if hotel_options_this_pass:

            def hotel_key(row):
                return row.get("id") or (
                    row.get("name"),
                    row.get("location"),
                    row.get("check_in_date"),
                    row.get("total_price"),
                    row.get("api_points_earned"),
                    row.get("refundability"),
                )

            seen = {hotel_key(row) for row in all_hotel_options_global}
            newly_added_count = 0
            for row in hotel_options_this_pass:
                key = hotel_key(row)
                if key not in seen:
                    seen.add(key)
                    all_hotel_options_global.append(row)
                    newly_added_count += 1
            if newly_added_count > 0:
                logger.info(
                    f"Pass {current_iteration_pass}: Added {newly_added_count} new unique hotel options. Total unique options so far: {len(all_hotel_options_global)}"
                )
            else:
                logger.info(
                    f"Pass {current_iteration_pass}: No new unique hotel options found in this pass. Total unique options: {len(all_hotel_options_global)}"
                )
        else:
            logger.info(
                f"Pass {current_iteration_pass}: No hotel options found in this date window across all cities searched in this pass."
            )

        if all_hotel_options_global:
            temp_total_lp = current_lp_balance
            if optimization_strategy == "minimize_cost_for_target_lp":
                _, _, temp_total_lp = select_cheapest_stays_for_target_lp(
                    all_hotel_options_global,
                    target_loyalty_points,
                    current_lp_balance,
                    miles_value_rate,
                )
            elif optimization_strategy == "dp_minimize_cost":
                _, _, temp_total_lp = select_optimal_stays_dp(
                    all_hotel_options_global,
                    target_loyalty_points,
                    current_lp_balance,
                    miles_value_rate,
                )
            elif optimization_strategy == "fastest_calendar_time_lp":
                _, _, temp_total_lp = select_fastest_calendar_time_lp(
                    all_hotel_options_global,
                    target_loyalty_points,
                    current_lp_balance,
                    max_overlaps=max_overlaps,  # Pass it here
                    miles_value_rate=miles_value_rate,
                )
            else:  # Default to points_per_dollar
                _, _, temp_total_lp = select_optimal_stays_ppd(
                    all_hotel_options_global,
                    target_loyalty_points,
                    current_lp_balance,
                    miles_value_rate,
                )
            running_total_lp_achieved = temp_total_lp

        if not iterative_search_for_lp_target:
            break

        if running_total_lp_achieved >= target_loyalty_points:
            logger.info(
                f"Target LP of {target_loyalty_points} met or exceeded ({running_total_lp_achieved}). Stopping iterative search."
            )
            break

        current_search_pass_start_date = current_search_pass_end_date + timedelta(days=1)
        current_search_pass_end_date = min(
            current_search_pass_start_date + timedelta(days=29),
            absolute_max_end_date_for_search,
        )

        if current_search_pass_start_date > current_search_pass_end_date:
            logger.warning(
                "Iterative search: No more valid future dates to search within limits. Stopping."
            )
            break
        if not date_range_chunk_for_pass and not iterative_search_for_lp_target:
            logger.warning(
                "Initial date range was empty and iterative search is not enabled. Stopping."
            )
            break

        logger.info(
            f"Target LP not yet met ({running_total_lp_achieved}/{target_loyalty_points}). Extending search. Next pass window: {current_search_pass_start_date.strftime('%m/%d/%Y')} to {current_search_pass_end_date.strftime('%m/%d/%Y')}"
        )

    if not all_hotel_options_global:
        logger.info("No hotel options found after all search attempts.")
        return [], [], 0.0, current_lp_balance

    logger.info(
        f"Performing final optimization on {len(all_hotel_options_global)} collected hotel options."
    )
    if optimization_strategy == "minimize_cost_for_target_lp":
        final_itinerary, total_cost, total_points_earned = select_cheapest_stays_for_target_lp(
            all_hotel_options_global,
            target_loyalty_points,
            current_lp_balance,
            miles_value_rate,
        )
    elif optimization_strategy == "dp_minimize_cost":
        final_itinerary, total_cost, total_points_earned = select_optimal_stays_dp(
            all_hotel_options_global,
            target_loyalty_points,
            current_lp_balance,
            miles_value_rate,
        )
    elif optimization_strategy == "fastest_calendar_time_lp":
        final_itinerary, total_cost, total_points_earned = select_fastest_calendar_time_lp(
            all_hotel_options_global,
            target_loyalty_points,
            current_lp_balance,
            max_overlaps=max_overlaps,  # And here for the final call
            miles_value_rate=miles_value_rate,
        )
    else:  # Default to points_per_dollar
        final_itinerary, total_cost, total_points_earned = select_optimal_stays_ppd(
            all_hotel_options_global,
            target_loyalty_points,
            current_lp_balance,
            miles_value_rate,
        )

    return all_hotel_options_global, final_itinerary, total_cost, total_points_earned


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Scrape AAdvantage Hotels for high points-per-dollar stays."
    )
    parser.add_argument("city", type=str, help="The city to search for hotels (e.g., 'Phoenix')")
    parser.add_argument(
        "--target-lp",
        type=int,
        default=125000,
        help="Target AAdvantage Loyalty Points (LP). Default: 125000.",
    )
    parser.add_argument(
        "--start-date",
        type=lambda s: datetime.strptime(s, "%m/%d/%Y").date(),
        default=date.today(),
        help="Start date (MM/DD/YYYY), defaults to today.",
    )
    parser.add_argument(
        "--end-date",
        type=lambda s: datetime.strptime(s, "%m/%d/%Y").date(),
        default=date.today() + timedelta(days=1),
        help="End date (MM/DD/YYYY), defaults to tomorrow.",
    )
    parser.add_argument(
        "--headers-file",
        type=str,
        help="Path to a JSON file containing session headers.",
    )
    parser.add_argument(
        "--aa-card-bonus",
        action="store_true",
        help="Apply AA credit card benefits (1x LP on spend, and miles as per --aa-card-miles-rate).",
    )
    parser.add_argument(
        "--aa-card-miles-rate",
        type=int,
        default=1,
        choices=[1, 10],
        help="Rate of miles earned per dollar with AA credit card (1 or 10). Effective if --aa-card-bonus is set. Default: 1.",
    )
    parser.add_argument(
        "--optimization-strategy",
        type=str,
        default="points_per_dollar",
        choices=[
            "points_per_dollar",
            "minimize_cost_for_target_lp",
            "dp_minimize_cost",
            "fastest_calendar_time_lp",
        ],
        help="The optimization strategy to use. Default: points_per_dollar.",
    )
    parser.add_argument(
        "--search-until-lp-target",
        action="store_true",
        help="Enable iterative search until LP target is met.",
    )
    parser.add_argument(
        "--max-search-days",
        type=int,
        default=180,
        help="Max days to search ahead in iterative mode. Default: 180.",
    )
    parser.add_argument(
        "--current-lp",
        type=int,
        default=0,
        help="User's current Loyalty Points balance. Default: 0.",
    )
    parser.add_argument(
        "--max-overlaps",
        type=int,
        default=None,
        help="Maximum concurrent overlaps for 'fastest_calendar_time_lp' strategy. Default: None (unlimited).",
    )
    parser.add_argument(
        "--miles-value-rate",
        type=float,
        default=0.015,
        help="Value of one mile in USD (e.g., 0.015 for 1.5 cents). Default: 0.015.",
    )
    args = parser.parse_args()

    final_session_headers: dict[str, str] = {}
    if args.headers_file:
        try:
            with open(args.headers_file) as f:
                final_session_headers = json.load(f)
            logger.info(f"Using session headers from: {args.headers_file}")
        except FileNotFoundError:
            logger.error(f"Headers file not found: {args.headers_file}.")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from headers file: {args.headers_file}.")
        except Exception as e:
            logger.error(f"Error loading headers from {args.headers_file}: {type(e).__name__}.")

    if not final_session_headers:
        logger.warning(
            "No/invalid headers file. Making unauthenticated requests. Results may be limited."
        )

    (
        all_hotel_options_main,
        final_itinerary_main,
        total_cost_main,
        total_points_earned_main,
    ) = find_best_hotel_deals(
        city_queries=[args.city],
        start_date=args.start_date,
        end_date=args.end_date,
        session_headers=final_session_headers,
        target_loyalty_points=args.target_lp,
        progress_callback=None,
        aa_card_bonus=args.aa_card_bonus,
        aa_card_miles_rate=args.aa_card_miles_rate,
        optimization_strategy=args.optimization_strategy,
        iterative_search_for_lp_target=args.search_until_lp_target,
        max_search_days_iterative=args.max_search_days,
        current_lp_balance=args.current_lp,
        max_overlaps=args.max_overlaps,
        miles_value_rate=args.miles_value_rate,
    )

    if not all_hotel_options_main:
        results_logger.info("No hotel values to display.")
    else:
        logger.info(f"\nCollected {len(all_hotel_options_main)} hotel options.")
        print_hotel_values_summary(all_hotel_options_main)

        if final_itinerary_main:
            results_logger.info("\n===== Optimal Loyalty Points Strategy =====")
            results_logger.info(f"Target Loyalty Points: {args.target_lp}")
            results_logger.info(
                f"Achieved Loyalty Points (including starting balance): {total_points_earned_main}"
            )
            results_logger.info(
                f"Net New Loyalty Points from Itinerary: {total_points_earned_main - args.current_lp}"
            )
            results_logger.info(f"Total Cost: ${total_cost_main:.2f}")

            net_new_points = total_points_earned_main - args.current_lp
            if total_cost_main > 0 and net_new_points > 0:
                results_logger.info(
                    f"Overall Points per Dollar (for new points): {net_new_points / total_cost_main:.2f}"
                )
            else:
                results_logger.info("Overall Points per Dollar (for new points): N/A")

            results_logger.info("\nItinerary Details:")
            header = f"{'Hotel Name':<35} {'Loc':<15} {'Date':<10} {'Price':<8} {'LP':<8} {'LP PPD':<7} {'Miles':<8} {'Val($)':<7}"
            results_logger.info(header)
            results_logger.info("=" * len(header))
            for stay in final_itinerary_main:
                stay_net_lp = stay.get(
                    "points_earned_final_for_itinerary", stay.get("points_earned", 0)
                )
                stay_final_lp_ppd = stay.get(
                    "points_per_dollar_final_for_itinerary",
                    stay.get("points_per_dollar", 0.0),
                )
                stay_miles = stay.get("miles_earned", 0)
                stay_miles_value = stay.get("miles_value", 0.0)
                results_logger.info(
                    f"{stay['name']:<35.35} {stay['location']:<15.15} {stay['check_in_date']:<10} "
                    f"${stay['total_price']:<7.2f} {stay_net_lp:<8} "
                    f"{stay_final_lp_ppd:<7.2f} {stay_miles:<8} ${stay_miles_value:<6.2f}"
                )
        else:
            results_logger.info(
                f"Could not form an itinerary to meet target {args.target_lp} points."
            )
    logger.info("\n--- Search Complete ---")


if __name__ == "__main__":
    main()
