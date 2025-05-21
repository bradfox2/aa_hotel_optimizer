import argparse
import concurrent.futures  # Added import
import json
import logging
import re  # Added for cURL parsing
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from typing import (  # Changed callable to Callable
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

import requests
from tqdm import tqdm

# Configure root logger for general logs (stderr)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# Configure a dedicated logger for results (stdout)
results_logger = logging.getLogger("results")
results_logger.setLevel(logging.INFO)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(logging.Formatter("%(message)s"))
results_logger.addHandler(stdout_handler)
results_logger.propagate = (
    False  # Prevent results_logger messages from going to root logger
)

# Constants for API interaction
PLACES_API_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/places"
SEARCH_API_BASE_URL = (
    "https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest"
)
RESULTS_API_BASE_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/search"


def parse_curl_command(curl_command: str) -> Tuple[Optional[str], Dict[str, str]]:
    """
    Parses a cURL command string (typically copied from browser developer tools)
    and extracts the URL and headers.

    Args:
        curl_command: The cURL command string.

    Returns:
        A tuple containing:
        - The URL string (or None if not found).
        - A dictionary of headers.
    """
    headers: Dict[str, str] = {}
    url: Optional[str] = None

    url_match = re.search(r"curl\s+'([^']*)'", curl_command)
    if not url_match:
        url_match = re.search(r'curl\s+"([^"]*)"', curl_command)
    if url_match:
        url = url_match.group(1)

    header_matches = re.findall(r"-H\s+'([^']*)'", curl_command)
    for header_str in header_matches:
        if ":" in header_str:
            name, value = header_str.split(":", 1)
            headers[name.strip()] = value.strip()

    cookie_match = re.search(r"-b\s+'([^']*)'", curl_command)
    if not cookie_match:
        cookie_match = re.search(r'-b\s+"([^"]*)"', curl_command)

    if cookie_match:
        cookie_string = cookie_match.group(1)
        if "Cookie" in headers:
            logging.warning("Cookie header already found, -b will overwrite it.")
        headers["Cookie"] = cookie_string.strip()

    return url, headers


def discover_place_ids(
    query: str, session_headers: Optional[Dict[str, str]] = None
) -> List[Tuple[str, str]]:
    """
    Discovers place IDs (primarily AGODA_CITY type) for a given query string.
    Returns a list of (name, place_id) tuples.
    """
    discovered_places: Dict[str, str] = {}
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
        request_headers.update(session_headers)

    response = None
    try:
        logging.info(f"Discovering place IDs for query: '{query}'...")
        response = requests.get(
            PLACES_API_URL, params=params, headers=request_headers, timeout=10
        )
        response.raise_for_status()
        places_data = response.json()

        if not isinstance(places_data, list):
            logging.warning(
                f"Places API did not return a list for query '{query}'. Response: {places_data}"
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

                        if (
                            place_id not in discovered_places
                            or current_name_len < len_to_compare
                        ):
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
            logging.warning(
                f"No suitable place IDs found for query '{query}' in the API response."
            )

    except requests.exceptions.RequestException as e:
        logging.error(f"Error during place ID discovery for '{query}': {e}")
    except json.JSONDecodeError:
        response_text_content = (
            response.text
            if response is not None and hasattr(response, "text")
            else "N/A"
        )
        logging.error(
            f"Error decoding JSON from places API for '{query}'. Response: {response_text_content}"
        )
    return [(name, place_id) for place_id, name in discovered_places.items()]


def search_aadvantage_hotels(
    check_in_date: str,
    check_out_date: str,
    location: str,
    place_id: str,
    adults: int = 1,
    children: int = 0,
    rooms: int = 1,
    session_headers: Optional[Dict[str, str]] = None,
) -> Optional[str]:
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
        request_headers.update(session_headers)
    response_obj = None
    search_uuid = None
    try:
        response_obj = requests.get(url, headers=request_headers, timeout=15)
        response_obj.raise_for_status()
        data = response_obj.json()
        search_uuid = data.get("uuid")
        if not search_uuid:
            logging.error(
                f"Error initiating search for {location} ({check_in_date}-{check_out_date}): 'uuid' not found. Response: {data}"
            )
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during search initiation for {location}: {e}")
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from search initiation for {location}")
    return search_uuid


def get_hotel_results(
    search_id: str,
    location_name: str,
    check_in_date: str,
    page_size: int = 45,
    page_number: int = 1,
    session_headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
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
        request_headers.update(session_headers)
    response = None
    try:
        response = requests.get(full_url, headers=request_headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error getting hotel results for search ID {search_id}: {e}")
    except json.JSONDecodeError:
        logging.error(
            f"Error decoding JSON from hotel results for search ID {search_id}"
        )
    return None


def analyze_hotel_data(
    search_results_data: Dict[str, Any],
    location_name: str,
    check_in_date_str: str,
    aa_card_bonus: bool = False,
    aa_card_miles_rate: int = 1,  # Added parameter
    miles_value_rate: float = 0.015,  # New parameter
) -> List[Dict[str, Any]]:
    hotels_value: List[Dict[str, Any]] = []
    # MILES_VALUE_RATE = 0.015  # Replaced by parameter

    if not search_results_data or "results" not in search_results_data:
        return hotels_value
    results = search_results_data["results"]
    if not isinstance(results, list):
        return hotels_value

    for hotel_data_item in results:
        hotel_details = hotel_data_item.get("hotel", {})
        hotel_name = hotel_details.get("name", "Unknown Hotel")
        total_price = hotel_data_item.get(
            "grandTotalPublishedPriceInclusiveWithFees", {}
        ).get("amount", 0.0)
        api_points_earned = hotel_data_item.get("rewards", 0)

        card_lp_bonus_points = 0
        card_miles_bonus_from_spend = 0
        actual_card_miles_rate_applied = 0

        if aa_card_bonus and total_price > 0:
            card_lp_bonus_points = int(round(total_price * 1))  # 1x LP on spend
            card_miles_bonus_from_spend = int(
                round(total_price * aa_card_miles_rate)
            )  # 1x or 10x miles on spend
            actual_card_miles_rate_applied = aa_card_miles_rate

        points_earned_initial = api_points_earned + card_lp_bonus_points
        points_per_dollar_initial = (
            points_earned_initial / total_price if total_price > 0 else 0.0
        )

        # Miles calculation: base miles (same as api_points_earned) + miles from card spend
        initial_miles_earned = api_points_earned + card_miles_bonus_from_spend
        initial_miles_value = initial_miles_earned * miles_value_rate  # Use parameter

        hotels_value.append(
            {
                "name": hotel_name,
                "location": location_name,
                "check_in_date": check_in_date_str,
                "total_price": total_price,
                "api_points_earned": api_points_earned,
                "card_bonus_points": card_lp_bonus_points,  # LP from card
                "points_earned": points_earned_initial,  # Total LP before status
                "points_per_dollar": points_per_dollar_initial,
                "status_bonus_points": 0,
                "points_earned_final_for_itinerary": points_earned_initial,  # Placeholder, recalc with status
                "points_per_dollar_final_for_itinerary": points_per_dollar_initial,  # Placeholder
                "aa_card_bonus_applied_to_stay": aa_card_bonus,
                "aa_card_miles_rate_on_spend": actual_card_miles_rate_applied,
                "miles_earned": initial_miles_earned,  # Total miles before status
                "miles_value": initial_miles_value,  # Value of miles before status
                "refundability": hotel_data_item.get("refundability", "UNKNOWN"),
                "star_rating": hotel_details.get("stars", 0.0),
                "user_rating": hotel_details.get("rating", 0.0),
            }
        )
    return hotels_value


def print_hotel_values_summary(hotels_value: List[Dict[str, Any]], limit: int = 20):
    if not hotels_value:
        results_logger.info("No hotel values to display.")
        return
    hotels_value.sort(
        key=lambda x: (
            x.get(
                "points_per_dollar_final_for_itinerary", x.get("points_per_dollar", 0)
            ),
            -x["total_price"],
        ),
        reverse=True,
    )
    results_logger.info(
        "\n===== Top AAdvantage Points Value Hotels (Based on LP PPD) ====="
    )
    header = f"{'Hotel Name':<35} {'Loc':<15} {'Date':<10} {'Price':<8} {'LP':<8} {'LP PPD':<7} {'Miles':<8} {'Val($)':<7} {'Refund':<8}"
    results_logger.info(header)
    results_logger.info("=" * len(header))
    for i, hotel in enumerate(hotels_value):
        if i >= limit:
            break
        final_lp = hotel.get(
            "points_earned_final_for_itinerary", hotel.get("points_earned")
        )
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


def generate_date_range(start_date: date, end_date: date) -> List[date]:
    dates: List[date] = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    return dates


def _apply_status_bonus_and_recalculate(
    stay: Dict[str, Any], projected_lp_before_stay: int, miles_value_rate: float = 0.015
) -> Dict[str, Any]:  # Added miles_value_rate
    current_stay = stay.copy()
    # MILES_VALUE_RATE = 0.015 # Replaced by parameter
    status_bonus_percentage = 0
    if projected_lp_before_stay >= 100000:
        status_bonus_percentage = 0.30
    elif projected_lp_before_stay >= 60000:
        status_bonus_percentage = 0.20

    base_hotel_points = current_stay["api_points_earned"]
    status_bonus_points = int(round(base_hotel_points * status_bonus_percentage))

    current_stay["status_bonus_points"] = status_bonus_points
    base_lp_for_final_calc = current_stay["points_earned"]
    current_stay["points_earned_final_for_itinerary"] = (
        base_lp_for_final_calc + status_bonus_points
    )

    if current_stay["total_price"] > 0:
        current_stay["points_per_dollar_final_for_itinerary"] = (
            current_stay["points_earned_final_for_itinerary"]
            / current_stay["total_price"]
        )
    else:
        current_stay["points_per_dollar_final_for_itinerary"] = 0

    # Initial miles (base + card spend miles) are already in current_stay["miles_earned"]
    # Status bonus LPs also count as miles
    final_miles_earned_for_stay = current_stay["miles_earned"] + status_bonus_points

    current_stay["miles_earned"] = (
        final_miles_earned_for_stay  # This now includes status bonus
    )
    current_stay["miles_value"] = (
        final_miles_earned_for_stay * miles_value_rate
    )  # Use parameter

    return current_stay


def select_optimal_stays_ppd(
    all_stays: List[Dict[str, Any]],
    target_points: int,
    current_lp_balance: int = 0,
    miles_value_rate: float = 0.015,  # New parameter
) -> Tuple[List[Dict[str, Any]], float, int]:
    candidate_stays_orig = [s for s in all_stays if s.get("api_points_earned", 0) > 0]
    if not candidate_stays_orig:
        return [], 0.0, 0

    sorted_initial_candidates = sorted(
        candidate_stays_orig,
        key=lambda x: (
            x.get("points_per_dollar", 0),
            -x.get("total_price", float("inf")),
        ),
        reverse=True,
    )

    selected_itinerary: List[Dict[str, Any]] = []
    projected_cumulative_lp = current_lp_balance
    current_total_cost = 0.0
    booked_dates: set[str] = set()

    for stay_data in sorted_initial_candidates:
        if projected_cumulative_lp >= target_points:
            break
        check_in_str = stay_data["check_in_date"]
        if check_in_str in booked_dates:
            continue
        current_stay_with_bonus = _apply_status_bonus_and_recalculate(
            stay_data, projected_cumulative_lp, miles_value_rate
        )
        selected_itinerary.append(current_stay_with_bonus)
        projected_cumulative_lp += current_stay_with_bonus[
            "points_earned_final_for_itinerary"
        ]
        current_total_cost += current_stay_with_bonus["total_price"]
        booked_dates.add(check_in_str)

    final_achieved_points = sum(
        s["points_earned_final_for_itinerary"] for s in selected_itinerary
    )
    selected_itinerary.sort(
        key=lambda x: datetime.strptime(x["check_in_date"], "%m/%d/%Y")
    )
    return selected_itinerary, current_total_cost, final_achieved_points


def select_cheapest_stays_for_target_lp(
    all_stays: List[Dict[str, Any]],
    target_points: int,
    current_lp_balance: int = 0,
    miles_value_rate: float = 0.015,  # New parameter
) -> Tuple[List[Dict[str, Any]], float, int]:
    candidate_stays_orig = [
        s
        for s in all_stays
        if s.get("api_points_earned", 0) > 0 and s.get("total_price", 0) > 0
    ]
    if not candidate_stays_orig:
        return [], 0.0, 0

    sorted_initial_candidates = sorted(
        candidate_stays_orig,
        key=lambda x: (
            x["total_price"],
            -x.get("points_earned", 0),
            x["check_in_date"],
        ),
    )

    selected_itinerary: List[Dict[str, Any]] = []
    projected_cumulative_lp = current_lp_balance
    current_total_cost = 0.0
    booked_dates: set[str] = set()

    for stay_data in sorted_initial_candidates:
        if projected_cumulative_lp >= target_points:
            break
        check_in_str = stay_data["check_in_date"]
        if check_in_str in booked_dates:
            continue
        current_stay_with_bonus = _apply_status_bonus_and_recalculate(
            stay_data, projected_cumulative_lp, miles_value_rate
        )
        selected_itinerary.append(current_stay_with_bonus)
        projected_cumulative_lp += current_stay_with_bonus[
            "points_earned_final_for_itinerary"
        ]
        current_total_cost += current_stay_with_bonus["total_price"]
        booked_dates.add(check_in_str)

    final_achieved_points = sum(
        s["points_earned_final_for_itinerary"] for s in selected_itinerary
    )
    selected_itinerary.sort(
        key=lambda x: datetime.strptime(x["check_in_date"], "%m/%d/%Y")
    )
    if final_achieved_points < target_points:
        logging.warning(
            f"Greedy cheapest stays could not meet target {target_points} LP. Achieved {final_achieved_points} LP."
        )
    return selected_itinerary, current_total_cost, final_achieved_points


def select_fastest_calendar_time_lp(
    all_stays: List[Dict[str, Any]],
    target_points: int,
    current_lp_balance: int = 0,
    max_overlaps: Optional[int] = None,
    miles_value_rate: float = 0.015,  # New parameter
) -> Tuple[List[Dict[str, Any]], float, int]:
    """
    Selects stays to meet the target LP by the earliest possible calendar date.
    Stays can overlap up to 'max_overlaps' per day.
    Status bonus for each stay is calculated based on initial current_lp_balance.
    """
    if not all_stays:
        return [], 0.0, current_lp_balance

    candidate_stays_with_initial_bonus: List[Dict[str, Any]] = []
    for stay_orig in all_stays:
        if stay_orig.get("api_points_earned", 0) <= 0:
            continue
        stay_eval = _apply_status_bonus_and_recalculate(
            stay_orig, current_lp_balance, miles_value_rate
        )
        candidate_stays_with_initial_bonus.append(stay_eval)

    if not candidate_stays_with_initial_bonus:
        return [], 0.0, current_lp_balance

    unique_checkout_dates: List[date] = sorted(
        list(
            set(
                datetime.strptime(s["check_in_date"], "%m/%d/%Y").date()
                + timedelta(days=1)
                for s in candidate_stays_with_initial_bonus
            )
        )
    )

    for potential_completion_date in unique_checkout_dates:
        stays_ending_by_date = [
            s
            for s in candidate_stays_with_initial_bonus
            if datetime.strptime(s["check_in_date"], "%m/%d/%Y").date()
            < potential_completion_date
        ]

        if not stays_ending_by_date:
            continue

        stays_ending_by_date.sort(
            key=lambda x: (
                x.get("points_earned_final_for_itinerary", 0),
                -x.get("total_price", float("inf")),
            ),
            reverse=True,
        )

        selected_itinerary: List[Dict[str, Any]] = []
        current_total_cost = 0.0
        # Relative LP needed from new stays
        relative_lp_needed = target_points - current_lp_balance
        if relative_lp_needed <= 0:  # Already met or exceeded target
            return [], 0.0, current_lp_balance

        accumulated_lp_from_new_stays = 0

        for stay_to_consider in stays_ending_by_date:
            if accumulated_lp_from_new_stays >= relative_lp_needed:
                break

            can_add_stay = True
            if max_overlaps is not None and max_overlaps > 0:
                num_existing_overlaps_for_this_date = 0
                stay_check_in_date_obj = datetime.strptime(
                    stay_to_consider["check_in_date"], "%m/%d/%Y"
                ).date()

                for existing_stay_in_itinerary in selected_itinerary:
                    existing_stay_check_in_date_obj = datetime.strptime(
                        existing_stay_in_itinerary["check_in_date"], "%m/%d/%Y"
                    ).date()
                    if existing_stay_check_in_date_obj == stay_check_in_date_obj:
                        num_existing_overlaps_for_this_date += 1

                if num_existing_overlaps_for_this_date >= max_overlaps:
                    can_add_stay = False

            if not can_add_stay:
                continue  # Skip this stay as it would exceed max_overlaps

            selected_itinerary.append(stay_to_consider)
            current_total_cost += stay_to_consider["total_price"]
            accumulated_lp_from_new_stays += stay_to_consider[
                "points_earned_final_for_itinerary"
            ]

        if accumulated_lp_from_new_stays >= relative_lp_needed:
            selected_itinerary.sort(
                key=lambda x: (
                    datetime.strptime(x["check_in_date"], "%m/%d/%Y"),
                    x.get("name"),
                )
            )
            final_achieved_lp_overall = (
                current_lp_balance + accumulated_lp_from_new_stays
            )
            return selected_itinerary, current_total_cost, final_achieved_lp_overall

    logging.warning(
        f"Fastest Calendar Time strategy could not meet target {target_points} LP with available options."
    )
    return [], 0.0, current_lp_balance


def select_optimal_stays_dp(
    all_stays: List[Dict[str, Any]],
    target_points: int,
    current_lp_balance: int = 0,
    miles_value_rate: float = 0.015,  # New parameter
) -> Tuple[List[Dict[str, Any]], float, int]:
    if not all_stays or target_points <= 0:
        return [], 0.0, current_lp_balance if target_points <= 0 else 0

    best_initial_stay_per_date: Dict[str, Dict[str, Any]] = {}
    for s_orig in all_stays:
        stay = s_orig.copy()
        if stay.get("points_earned", 0) <= 0 or stay.get("total_price", 0) <= 0:
            continue
        date_str = stay["check_in_date"]
        if (
            date_str not in best_initial_stay_per_date
            or stay["points_earned"]
            > best_initial_stay_per_date[date_str]["points_earned"]
            or (
                stay["points_earned"]
                == best_initial_stay_per_date[date_str]["points_earned"]
                and stay["total_price"]
                < best_initial_stay_per_date[date_str]["total_price"]
            )
        ):
            best_initial_stay_per_date[date_str] = stay

    candidate_stays_for_dp = list(best_initial_stay_per_date.values())

    if not candidate_stays_for_dp:
        logging.info("No candidate stays for DP after filtering.")
        return [], 0.0, current_lp_balance

    relative_target_points = max(0, target_points - current_lp_balance)
    if relative_target_points == 0:
        return [], 0.0, current_lp_balance

    max_initial_points_for_dp_range = max(
        (s.get("points_earned", 0) for s in candidate_stays_for_dp), default=0
    )
    buffer_points = max(
        max_initial_points_for_dp_range, int(relative_target_points * 0.2), 1000
    )
    max_dp_points_range = relative_target_points + buffer_points
    if max_dp_points_range <= 0:
        max_dp_points_range = relative_target_points

    dp_min_cost = [float("inf")] * (max_dp_points_range + 1)
    dp_itinerary_indices = [[] for _ in range(max_dp_points_range + 1)]
    dp_min_cost[0] = 0.0

    for idx, stay_dp_data in enumerate(candidate_stays_for_dp):
        s_cost = stay_dp_data["total_price"]
        s_points = stay_dp_data["points_earned"]
        if s_points <= 0:
            continue

        for p in range(max_dp_points_range, s_points - 1, -1):
            if dp_min_cost[p - s_points] != float("inf"):
                cost_if_taken = dp_min_cost[p - s_points] + s_cost
                if cost_if_taken < dp_min_cost[p]:
                    dp_min_cost[p] = cost_if_taken
                    dp_itinerary_indices[p] = list(
                        dp_itinerary_indices[p - s_points]
                    ) + [idx]
                elif cost_if_taken == dp_min_cost[p] and len(
                    dp_itinerary_indices[p - s_points]
                ) + 1 < len(dp_itinerary_indices[p]):
                    dp_itinerary_indices[p] = list(
                        dp_itinerary_indices[p - s_points]
                    ) + [idx]

    best_itinerary_indices_from_dp = []
    min_total_cost_from_dp = float("inf")

    for p_relative in range(relative_target_points, max_dp_points_range + 1):
        if dp_min_cost[p_relative] < min_total_cost_from_dp:
            min_total_cost_from_dp = dp_min_cost[p_relative]
            best_itinerary_indices_from_dp = dp_itinerary_indices[p_relative]
        elif dp_min_cost[p_relative] == min_total_cost_from_dp:
            current_path_points = sum(
                candidate_stays_for_dp[i]["points_earned"]
                for i in dp_itinerary_indices[p_relative]
            )
            best_path_points = (
                sum(
                    candidate_stays_for_dp[i]["points_earned"]
                    for i in best_itinerary_indices_from_dp
                )
                if best_itinerary_indices_from_dp
                else 0
            )
            if current_path_points > best_path_points:
                best_itinerary_indices_from_dp = dp_itinerary_indices[p_relative]

    if min_total_cost_from_dp == float("inf"):
        logging.info(
            f"DP could not achieve relative target of {relative_target_points} LP."
        )
        return [], 0.0, current_lp_balance

    temp_selected_stays = [
        candidate_stays_for_dp[i] for i in best_itinerary_indices_from_dp
    ]
    temp_selected_stays.sort(
        key=lambda x: datetime.strptime(x["check_in_date"], "%m/%d/%Y")
    )

    final_itinerary_with_status_bonus: List[Dict[str, Any]] = []
    projected_cumulative_lp_for_final_calc = current_lp_balance
    final_total_cost = 0.0

    for stay_data in temp_selected_stays:
        current_stay_with_bonus = _apply_status_bonus_and_recalculate(
            stay_data, projected_cumulative_lp_for_final_calc, miles_value_rate
        )
        final_itinerary_with_status_bonus.append(current_stay_with_bonus)
        projected_cumulative_lp_for_final_calc += current_stay_with_bonus[
            "points_earned_final_for_itinerary"
        ]
        final_total_cost += current_stay_with_bonus["total_price"]

    final_achieved_total_lp = projected_cumulative_lp_for_final_calc

    if final_achieved_total_lp < target_points:
        logging.warning(
            f"DP strategy with status bonus adjustment did not meet target {target_points} LP. Achieved {final_achieved_total_lp} LP."
        )

    return final_itinerary_with_status_bonus, final_total_cost, final_achieved_total_lp


def fetch_data_for_date(
    current_date: date,
    actual_location_name_used: str,
    target_place_id: str,
    session_headers: Dict[str, str],
    aa_card_bonus: bool = False,
    aa_card_miles_rate: int = 1,  # Added parameter
    miles_value_rate: float = 0.015,  # New parameter
) -> List[Dict[str, Any]]:
    check_in_date_str = current_date.strftime("%m/%d/%Y")
    check_out_date_str = (current_date + timedelta(days=1)).strftime("%m/%d/%Y")
    hotel_stays_on_date: List[Dict[str, Any]] = []

    search_uuid = search_aadvantage_hotels(
        check_in_date_str,
        check_out_date_str,
        actual_location_name_used,
        target_place_id,
        session_headers=session_headers,
    )

    if search_uuid:
        results_data = get_hotel_results(
            search_uuid,
            actual_location_name_used,
            check_in_date_str,
            session_headers=session_headers,
        )
        if results_data:
            hotel_stays_on_date = analyze_hotel_data(
                results_data,
                actual_location_name_used,
                check_in_date_str,
                aa_card_bonus=aa_card_bonus,
                aa_card_miles_rate=aa_card_miles_rate,  # Pass down
                miles_value_rate=miles_value_rate,  # Pass down
            )
        else:
            logging.warning(
                f"Failed to get hotel results for {actual_location_name_used} on {check_in_date_str} (Search ID: {search_uuid})"
            )
    else:
        logging.warning(
            f"Failed to initiate search for {actual_location_name_used} on {check_in_date_str}"
        )
    return hotel_stays_on_date


def find_best_hotel_deals(
    city_queries: List[str],
    start_date: date,
    end_date: date,
    session_headers: Dict[str, str],
    target_loyalty_points: int,
    progress_callback: Optional[Callable] = None,  # Changed to Callable
    aa_card_bonus: bool = False,
    aa_card_miles_rate: int = 1,  # Added default value
    optimization_strategy: str = "points_per_dollar",
    iterative_search_for_lp_target: bool = False,
    max_search_days_iterative: int = 180,
    current_lp_balance: int = 0,
    max_overlaps: Optional[int] = None,  # New parameter
    miles_value_rate: float = 0.015,  # New parameter
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, int]:
    all_hotel_options_global: List[Dict[str, Any]] = []
    final_itinerary: List[Dict[str, Any]] = []
    total_cost: float = 0.0
    running_total_lp_achieved = current_lp_balance

    current_search_pass_start_date = start_date
    current_search_pass_end_date = end_date

    max_iterations_passes = 12
    current_iteration_pass = 0
    absolute_max_end_date_for_search = start_date + timedelta(
        days=max_search_days_iterative
    )

    while True:
        current_iteration_pass += 1
        if (
            iterative_search_for_lp_target
            and current_iteration_pass > max_iterations_passes
        ):
            logging.warning(
                f"Iterative search reached max passes ({max_iterations_passes}). Stopping."
            )
            break
        if (
            iterative_search_for_lp_target
            and current_search_pass_start_date > absolute_max_end_date_for_search
        ):
            logging.warning(
                f"Iterative search reached max search horizon ({absolute_max_end_date_for_search.strftime('%m/%d/%Y')}). Stopping."
            )
            break

        hotel_options_this_pass: List[Dict[str, Any]] = []
        date_range_chunk_for_pass = generate_date_range(
            current_search_pass_start_date, current_search_pass_end_date
        )

        if not date_range_chunk_for_pass:
            if (
                not iterative_search_for_lp_target
                or current_search_pass_start_date > current_search_pass_end_date
            ):
                logging.info("No more valid dates in the current or initial window.")
                break

        logging.info(
            f"\n--- Iteration Pass {current_iteration_pass}: Searching Date Window "
            f"{current_search_pass_start_date.strftime('%m/%d/%Y')} to "
            f"{current_search_pass_end_date.strftime('%m/%d/%Y')} ---"
        )

        for city_idx, current_city_query in enumerate(city_queries):
            logging.info(
                f"\nProcessing city {city_idx + 1}/{len(city_queries)}: '{current_city_query}' for current date window..."
            )

            discovered_locations = discover_place_ids(
                query=current_city_query, session_headers=session_headers
            )
            target_place_id: Optional[str] = None
            actual_location_name_used_for_city = current_city_query

            if discovered_locations:
                best_city_match: Optional[Tuple[str, str]] = None
                for name, place_id_val in discovered_locations:
                    if "AGODA_CITY" in place_id_val.upper():
                        if current_city_query.lower() in name.lower():
                            if best_city_match is None or len(name) < len(
                                best_city_match[0]
                            ):
                                best_city_match = (name, place_id_val)
                        elif best_city_match is None:
                            best_city_match = (name, place_id_val)

                if best_city_match:
                    actual_location_name_used_for_city, target_place_id = (
                        best_city_match
                    )
                    logging.info(
                        f"Selected place ID for '{actual_location_name_used_for_city}': {target_place_id}"
                    )
                elif discovered_locations:
                    actual_location_name_used_for_city, target_place_id = (
                        discovered_locations[0]
                    )
                    logging.warning(
                        f"Using first discovered place ID as fallback for '{current_city_query}': {target_place_id} ({actual_location_name_used_for_city})"
                    )

            if not target_place_id:
                logging.error(
                    f"Could not discover a suitable place ID for query '{current_city_query}'. Skipping this city."
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
                        status_message="Place ID not found",
                    )
                continue

            if not date_range_chunk_for_pass:
                logging.warning(
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

            logging.info(
                f"Searching Hotels in {actual_location_name_used_for_city} (Place ID: {target_place_id}) for dates {current_search_pass_start_date.strftime('%m/%d/%Y')} to {current_search_pass_end_date.strftime('%m/%d/%Y')}"
            )

            num_workers = min(10, len(date_range_chunk_for_pass))
            if num_workers == 0:
                num_workers = 1

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=num_workers
            ) as executor:
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
                        logging.error(
                            f"Error fetching data for a date in {actual_location_name_used_for_city}: {exc}"
                        )
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
                                is_final_city_in_pass=(
                                    city_idx + 1 == len(city_queries)
                                ),
                            )

        if hotel_options_this_pass:
            existing_hotel_ids_dates = {
                (h.get("name", ""), h.get("check_in_date", ""))
                for h in all_hotel_options_global
            }
            newly_added_count = 0
            for h_new in hotel_options_this_pass:
                hotel_key = (
                    h_new.get("name", "UnknownHotel"),
                    h_new.get("location", "UnknownLocation"),
                    h_new.get("check_in_date", "UnknownDate"),
                    h_new.get("total_price", 0.0),
                )
                is_duplicate = False
                for existing_h in all_hotel_options_global:
                    existing_key = (
                        existing_h.get("name", "UnknownHotel"),
                        existing_h.get("location", "UnknownLocation"),
                        existing_h.get("check_in_date", "UnknownDate"),
                        existing_h.get("total_price", 0.0),
                    )
                    if hotel_key == existing_key:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    all_hotel_options_global.append(h_new)
                    newly_added_count += 1
            if newly_added_count > 0:
                logging.info(
                    f"Pass {current_iteration_pass}: Added {newly_added_count} new unique hotel options. Total unique options so far: {len(all_hotel_options_global)}"
                )
            else:
                logging.info(
                    f"Pass {current_iteration_pass}: No new unique hotel options found in this pass. Total unique options: {len(all_hotel_options_global)}"
                )
        else:
            logging.info(
                f"Pass {current_iteration_pass}: No hotel options found in this date window across all cities searched in this pass."
            )

        if all_hotel_options_global:
            temp_itinerary, temp_cost, temp_total_lp = [], 0.0, current_lp_balance
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
            logging.info(
                f"Target LP of {target_loyalty_points} met or exceeded ({running_total_lp_achieved}). Stopping iterative search."
            )
            break

        current_search_pass_start_date = current_search_pass_end_date + timedelta(
            days=1
        )
        current_search_pass_end_date = min(
            current_search_pass_start_date + timedelta(days=29),
            absolute_max_end_date_for_search,
        )

        if current_search_pass_start_date > current_search_pass_end_date:
            logging.warning(
                "Iterative search: No more valid future dates to search within limits. Stopping."
            )
            break
        if not date_range_chunk_for_pass and not iterative_search_for_lp_target:
            logging.warning(
                "Initial date range was empty and iterative search is not enabled. Stopping."
            )
            break

        logging.info(
            f"Target LP not yet met ({running_total_lp_achieved}/{target_loyalty_points}). Extending search. Next pass window: {current_search_pass_start_date.strftime('%m/%d/%Y')} to {current_search_pass_end_date.strftime('%m/%d/%Y')}"
        )

    if not all_hotel_options_global:
        logging.info("No hotel options found after all search attempts.")
        return [], [], 0.0, current_lp_balance

    logging.info(
        f"Performing final optimization on {len(all_hotel_options_global)} collected hotel options."
    )
    if optimization_strategy == "minimize_cost_for_target_lp":
        final_itinerary, total_cost, total_points_earned = (
            select_cheapest_stays_for_target_lp(
                all_hotel_options_global,
                target_loyalty_points,
                current_lp_balance,
                miles_value_rate,
            )
        )
    elif optimization_strategy == "dp_minimize_cost":
        final_itinerary, total_cost, total_points_earned = select_optimal_stays_dp(
            all_hotel_options_global,
            target_loyalty_points,
            current_lp_balance,
            miles_value_rate,
        )
    elif optimization_strategy == "fastest_calendar_time_lp":
        final_itinerary, total_cost, total_points_earned = (
            select_fastest_calendar_time_lp(
                all_hotel_options_global,
                target_loyalty_points,
                current_lp_balance,
                max_overlaps=max_overlaps,  # And here for the final call
                miles_value_rate=miles_value_rate,
            )
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
    parser = argparse.ArgumentParser(
        description="Scrape AAdvantage Hotels for high points-per-dollar stays."
    )
    parser.add_argument(
        "city", type=str, help="The city to search for hotels (e.g., 'Phoenix')"
    )
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

    final_session_headers: Dict[str, str] = {}
    if args.headers_file:
        try:
            with open(args.headers_file, "r") as f:
                final_session_headers = json.load(f)
            logging.info(f"Using session headers from: {args.headers_file}")
        except FileNotFoundError:
            logging.error(f"Headers file not found: {args.headers_file}.")
        except json.JSONDecodeError:
            logging.error(
                f"Error decoding JSON from headers file: {args.headers_file}."
            )
        except Exception as e:
            logging.error(f"Error loading headers from {args.headers_file}: {e}.")

    if not final_session_headers:
        logging.warning(
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
        logging.info(f"\nCollected {len(all_hotel_options_main)} hotel options.")
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
    logging.info("\n--- Search Complete ---")


if __name__ == "__main__":
    main()
