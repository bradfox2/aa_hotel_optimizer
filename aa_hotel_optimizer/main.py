import argparse
import json
import logging
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

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
results_logger.propagate = False # Prevent results_logger messages from going to root logger

# Constants for API interaction
PLACES_API_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/places"
SEARCH_API_BASE_URL = (
    "https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest"
)
RESULTS_API_BASE_URL = "https://www.aadvantagehotels.com/rest/aadvantage-hotels/search"

# Define common Phoenix metro area keywords to help filter results from places API
PHOENIX_METRO_KEYWORDS = [
    "phoenix",
    "scottsdale",
    "tempe",
    "mesa",
    "chandler",
    "glendale",
    "gilbert",
    "peoria",
    "surprise",
    "avondale",
    "goodyear",
]


def discover_phoenix_metro_place_ids(
    query: str = "Phoenix", session_headers: Optional[Dict[str, str]] = None
) -> List[Tuple[str, str]]:
    """
    Discover place IDs for Phoenix metro areas using the places API.
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

            if not (
                place_id and name and place_type == "AGODA_CITY"
            ):  # Ensure it's a city-level ID
                # For area-specific queries like "Old Town Scottsdale", we might get AGODA_AREA
                if place_type == "AGODA_AREA" and query.lower() in name.lower():
                    if place_id not in discovered_places or len(name) < len(
                        discovered_places[place_id]
                    ):
                        discovered_places[place_id] = (
                            name  # Accept area if it matches query
                        )
                continue

            is_relevant_location = False
            if query.lower() in name.lower() or query.lower() in description:
                is_relevant_location = True
            elif "united states" in description and (
                "arizona" in description or "az" in description
            ):
                for keyword in PHOENIX_METRO_KEYWORDS:
                    if keyword in name.lower() or keyword in description:
                        is_relevant_location = True
                        break

            if is_relevant_location:
                if place_id not in discovered_places or len(name) < len(
                    discovered_places[place_id]
                ):
                    discovered_places[place_id] = name

        if not discovered_places and query in PHOENIX_METRO_KEYWORDS:
            for place in (
                places_data
            ):  # Fallback for primary keywords if no specific match found
                if (
                    place.get("id")
                    and place.get("type") == "AGODA_CITY"
                    and query.lower() in place.get("name", "").lower()
                ):
                    discovered_places[place["id"]] = place["name"]
                    logging.info(
                        f"Using general city place ID for '{query}': {place['id']} - {place['name']}"
                    )
                    break

    except requests.exceptions.RequestException as e:
        logging.error(f"Error discovering place IDs for '{query}': {e}")
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
        "numberOfChildren": children,  # Assuming place_id is city/area
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
    search_results_data: Dict[str, Any], location_name: str, check_in_date_str: str
) -> List[Dict[str, Any]]:
    hotels_value: List[Dict[str, Any]] = []
    if not search_results_data or "results" not in search_results_data:
        return hotels_value
    results = search_results_data["results"]
    if not isinstance(results, list):
        return hotels_value

    for hotel_data_item in results:
        hotel_details = hotel_data_item.get("hotel", {})
        hotel_name = hotel_details.get("name", "Unknown Hotel")
        # Use the total price including taxes and fees for points per dollar calculation
        total_price = hotel_data_item.get(
            "grandTotalPublishedPriceInclusiveWithFees", {}
        ).get("amount", 0.0)
        points_earned = hotel_data_item.get("rewards", 0)

        # Debug log for the specific test case
        if (
            "old town scottsdale" in location_name.lower()
            and check_in_date_str == "05/31/2025"
        ):
            logging.debug( # Use the root logger for debug messages
                f"\nDEBUG: Raw data for '{hotel_name}' in '{location_name}' on {check_in_date_str}:"
            )
            logging.debug(f"  Raw hotel_data_item: {json.dumps(hotel_data_item, indent=2)}")
            logging.debug(f"  Extracted points_earned (from 'rewards'): {points_earned}")
            logging.debug(f"  Price: {total_price}")
            logging.debug(f"  rewardsBeforeBoost: {hotel_data_item.get('rewardsBeforeBoost')}")
            logging.debug(f"  boostedRewards: {hotel_data_item.get('boostedRewards')}")
            logging.debug(f"  promotionRewards: {hotel_data_item.get('promotionRewards')}")
            logging.debug(f"  originalRewards: {hotel_data_item.get('originalRewards')}")

        refundability = hotel_data_item.get("refundability", "UNKNOWN")
        points_per_dollar = points_earned / total_price if total_price > 0 else 0.0
        hotels_value.append(
            {
                "name": hotel_name,
                "location": location_name,
                "check_in_date": check_in_date_str,
                "total_price": total_price,
                "points_earned": points_earned,
                "points_per_dollar": points_per_dollar,
                "refundability": refundability,
                "star_rating": hotel_details.get("stars", 0.0),
                "user_rating": hotel_details.get("rating", 0.0),
            }
        )
    return hotels_value


def print_hotel_values_summary(hotels_value: List[Dict[str, Any]], limit: int = 20):
    if not hotels_value:
        results_logger.info("No hotel values to display.") # Use results_logger
        return
    hotels_value.sort(
        key=lambda x: (x["points_per_dollar"], -x["total_price"]), reverse=True
    )
    results_logger.info("\n===== Top AAdvantage Points Value Hotels =====") # Use results_logger
    header = f"{'Hotel Name':<40} {'Location':<20} {'Date':<12} {'Price ($)':<10} {'Points':<10} {'Points/$':<10} {'Refundable':<12}"
    results_logger.info(header) # Use results_logger
    results_logger.info("=" * len(header)) # Use results_logger
    for i, hotel in enumerate(hotels_value):
        if i >= limit:
            break
        results_logger.info( # Use results_logger
            f"{hotel['name']:<40} {hotel['location']:<20} {hotel['check_in_date']:<12} "
            f"${hotel['total_price']:<9.2f} {hotel['points_earned']:<10} "
            f"{hotel['points_per_dollar']:<9.2f} {hotel['refundability'] == 'REFUNDABLE':<12}"
        )
    if hotels_value:
        best_overall_value = hotels_value[0]
        results_logger.info("\n🏆 OVERALL BEST SINGLE STAY VALUE (from this batch):") # Use results_logger
        results_logger.info( # Use results_logger
            f"{best_overall_value['name']} in {best_overall_value['location']} on {best_overall_value['check_in_date']} "
            f"offers {best_overall_value['points_per_dollar']:.2f} points per dollar."
        )
        results_logger.info( # Use results_logger
            f"Pay ${best_overall_value['total_price']:.2f} and earn {best_overall_value['points_earned']} AAdvantage points."
        )


def generate_date_range(start_date: date, end_date: date) -> List[date]:
    dates: List[date] = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    return dates


def select_optimal_stays(
    all_stays: List[Dict[str, Any]], target_points: int
) -> Tuple[List[Dict[str, Any]], float, int]:
    sorted_stays = sorted(
        all_stays,
        key=lambda x: (x["points_per_dollar"], -x["total_price"], x["check_in_date"]),
        reverse=True,
    )
    selected_itinerary: List[Dict[str, Any]] = []
    current_total_points = 0
    current_total_cost = 0.0
    booked_dates: set[str] = set()
    for stay in sorted_stays:
        if current_total_points >= target_points:
            break
        check_in_str = stay["check_in_date"]
        if check_in_str not in booked_dates:
            selected_itinerary.append(stay)
            current_total_points += stay["points_earned"]
            current_total_cost += stay["total_price"]
            booked_dates.add(check_in_str)
    return selected_itinerary, current_total_cost, current_total_points


def find_best_hotel_deals(
    city_query: str,
    start_date: date,
    end_date: date,
    session_headers: Dict[str, str],
    target_loyalty_points: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, int]:
    """
    Finds the best hotel deals for a given city and date range.

    Args:
        city_query: The city to search for (e.g., "Phoenix").
        start_date: The start date for the search.
        end_date: The end date for the search.
        session_headers: Headers for authenticated requests.
        target_loyalty_points: The target number of loyalty points for optimization.

    Returns:
        A tuple containing:
        - all_hotel_options: List of all found hotel stays.
        - final_itinerary: List of stays in the optimized itinerary.
        - total_cost: Total cost of the optimized itinerary.
        - total_points_earned: Total points earned from the optimized itinerary.
    """
    location_display_name = city_query # Use the provided city name as the display name for now
    date_range = generate_date_range(start_date, end_date)

    logging.info(f"\n--- Searching for Hotels in {location_display_name} ---")
    logging.info(f"Dates: {start_date.strftime('%m/%d/%Y')} to {end_date.strftime('%m/%d/%Y')}")

    # Discover place ID for the specified location
    discovered_locations = discover_phoenix_metro_place_ids(
        query=city_query, session_headers=session_headers
    )

    target_place_id: Optional[str] = None
    actual_location_name_used = location_display_name

    if discovered_locations:
        # Prefer a city-level ID that matches the query
        for name, place_id in discovered_locations:
            if city_query.lower() in name.lower() and "city" in place_id.lower(): # Simple check
                 target_place_id = place_id
                 actual_location_name_used = name
                 logging.info(f"Found city place ID for '{name}': {place_id}")
                 break
        if not target_place_id and discovered_locations:
             # If no city match, use the first discovered place ID as a fallback
             target_place_id = discovered_locations[0][1]
             actual_location_name_used = discovered_locations[0][0]
             logging.warning(f"No specific city ID found for '{city_query}'. Using first discovered ID: {target_place_id} ({actual_location_name_used}) as fallback.")
    else:
        logging.error(f"Could not discover any place IDs for '{city_query}'.")
        return [], [], 0.0, 0 # Return empty if no place ID

    all_hotel_options: List[Dict[str, Any]] = []

    if not target_place_id:
        logging.error(f"Critical error: target_place_id not set before search loop for {city_query}.")
        return [], [], 0.0, 0

    logging.info(
        f"Searching with Place ID: {target_place_id} for location: {actual_location_name_used}"
    )

    # Iterate through the date range
    for current_date in tqdm(date_range, desc="Searching dates", file=sys.stderr):
        check_in_date_str = current_date.strftime("%m/%d/%Y")
        check_out_date_str = (current_date + timedelta(days=1)).strftime("%m/%d/%Y")

        search_uuid = search_aadvantage_hotels(
            check_in_date=check_in_date_str,
            check_out_date=check_out_date_str,
            location=actual_location_name_used,
            place_id=target_place_id,
            session_headers=session_headers,
        )

        if search_uuid:
            results_data = get_hotel_results(
                search_id=search_uuid,
                location_name=actual_location_name_used,
                check_in_date=check_in_date_str,
                session_headers=session_headers,
            )
            if results_data:
                hotel_stays_on_date = analyze_hotel_data(
                    results_data, actual_location_name_used, check_in_date_str
                )
                all_hotel_options.extend(hotel_stays_on_date)
            else:
                logging.warning(
                    f"Failed to get hotel results for {actual_location_name_used} on {check_in_date_str} (Search ID: {search_uuid})"
                )
        else:
            logging.warning(
                f"Failed to initiate search for {actual_location_name_used} on {check_in_date_str}"
            )

    if not all_hotel_options:
        logging.info("\nNo hotel options found for the specified location and date range.")
        return [], [], 0.0, 0

    logging.info(f"\nCollected {len(all_hotel_options)} hotel options.")

    final_itinerary, total_cost, total_points_earned = select_optimal_stays(
        all_hotel_options, target_loyalty_points
    )
    return all_hotel_options, final_itinerary, total_cost, total_points_earned


def main():
    TARGET_LOYALTY_POINTS = 250000 # Default target

    parser = argparse.ArgumentParser(
        description="Scrape AAdvantage Hotels for high points-per-dollar stays. Can also be used as a library."
    )
    parser.add_argument(
        "city", type=str, help="The city to search for hotels (e.g., 'Phoenix')"
    )
    parser.add_argument(
        "--start-date", # Changed to an optional argument
        type=lambda s: datetime.strptime(s, "%m/%d/%Y").date(),
        default=date.today(),
        help="The start date for the search (MM/DD/YYYY), defaults to today.",
    )
    parser.add_argument(
        "--end-date", # Changed to an optional argument
        type=lambda s: datetime.strptime(s, "%m/%d/%Y").date(),
        default=date.today() + timedelta(days=1),
        help="The end date for the search (MM/DD/YYYY), defaults to tomorrow.",
    )
    parser.add_argument(
        "--headers-file",
        type=str,
        help="Path to a JSON file containing session headers (e.g., cookies, tokens).",
    )
    args = parser.parse_args()

    final_session_headers: Dict[str, str] = {}
    if args.headers_file:
        try:
            with open(args.headers_file, "r") as f:
                final_session_headers = json.load(f)
            logging.info(f"Using session headers from: {args.headers_file}")
        except FileNotFoundError:
            logging.error(f"Headers file not found: {args.headers_file}. Proceeding with unauthenticated requests.")
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from headers file: {args.headers_file}. Proceeding with unauthenticated requests.")
        except Exception as e:
            logging.error(f"An unexpected error occurred while loading headers from {args.headers_file}: {e}. Proceeding with unauthenticated requests.")

    if not final_session_headers:
        logging.warning("No headers file provided or headers could not be loaded. Making unauthenticated requests.")
        logging.warning("You may not see personalized offers or high-value points without valid session headers.")


    location_query = args.city
    # Use the provided city name as the display name for now, can refine later
    location_display_name = args.city

    # Define a date range for the search using provided arguments
    start_date = args.start_date
    end_date = args.end_date
    date_range = generate_date_range(start_date, end_date)

    logging.info(f"\n--- Searching for Hotels in {location_display_name} ---")
    logging.info(f"Dates: {start_date.strftime('%m/%d/%Y')} to {end_date.strftime('%m/%d/%Y')}")

    # Discover place ID for the specified location
    discovered_locations = discover_phoenix_metro_place_ids(
        query=location_query, session_headers=final_session_headers
    )

    target_place_id: Optional[str] = None
    actual_location_name_used = location_display_name

    if discovered_locations:
        # Prefer a city-level ID that matches the query
        for name, place_id in discovered_locations:
            if location_query.lower() in name.lower() and "city" in place_id.lower():
                 target_place_id = place_id
                 actual_location_name_used = name
                 logging.info(f"Found city place ID for '{name}': {place_id}")
                 break
        if not target_place_id and discovered_locations:
             # If no city match, use the first discovered place ID as a fallback
             target_place_id = discovered_locations[0][1]
             actual_location_name_used = discovered_locations[0][0]
             logging.warning(f"No specific city ID found for '{location_query}'. Using first discovered ID: {target_place_id} ({actual_location_name_used}) as fallback.")
    else:
        logging.error(f"Could not discover any place IDs for '{location_query}'. Exiting.")
        return # Exit if no place ID is found

    all_hotel_options: List[Dict[str, Any]] = []

    if not target_place_id: # Should be caught by earlier return, but as a safeguard.
        logging.error(f"Critical error: target_place_id not set before search loop for {location_query}. Exiting.")
        return

    logging.info(
        f"Searching with Place ID: {target_place_id} for location: {actual_location_name_used}"
    )

    # Iterate through the date range
    for current_date in tqdm(date_range, desc="Searching dates", file=sys.stderr): # Ensure tqdm writes to stderr
        check_in_date_str = current_date.strftime("%m/%d/%Y")
        check_out_date_str = (current_date + timedelta(days=1)).strftime("%m/%d/%Y")

        # Perform search for the current date
        search_uuid = search_aadvantage_hotels(
            check_in_date=check_in_date_str,
            check_out_date=check_out_date_str,
            location=actual_location_name_used,
            place_id=target_place_id,
            session_headers=final_session_headers,
        )

        if search_uuid:
            results_data = get_hotel_results(
                search_id=search_uuid,
                location_name=actual_location_name_used,
                check_in_date=check_in_date_str,
                session_headers=final_session_headers,
            )
            if results_data:
                hotel_stays_on_date = analyze_hotel_data(
                    results_data, actual_location_name_used, check_in_date_str
                )
                all_hotel_options.extend(hotel_stays_on_date)
            else:
                logging.warning(
                    f"Failed to get hotel results for {actual_location_name_used} on {check_in_date_str} (Search ID: {search_uuid})"
                )
        else:
            logging.warning(
                f"Failed to initiate search for {actual_location_name_used} on {check_in_date_str}"
            )

        # This block is after the date loop

    if not all_hotel_options:
        logging.info("\nNo hotel options found for the specified location and date range.") # To stderr
        results_logger.info("No hotel values to display.") # To stdout
    else:
        logging.info(f"\nCollected {len(all_hotel_options)} hotel options.") # To stderr
        print_hotel_values_summary(all_hotel_options) # To stdout via results_logger

        # Optimization logic
        logging.info(
            f"\nOptimizing for {TARGET_LOYALTY_POINTS} loyalty points..."
        ) # To stderr
        final_itinerary, total_cost, total_points_earned = select_optimal_stays(
            all_hotel_options, TARGET_LOYALTY_POINTS
        )
        if final_itinerary:
            logging.info("\n===== Optimal Loyalty Points Strategy (Details below on stdout) =====") # To stderr
            results_logger.info("\n===== Optimal Loyalty Points Strategy =====") # To stdout
            results_logger.info(f"Target Loyalty Points: {TARGET_LOYALTY_POINTS}")
            results_logger.info(f"Achieved Loyalty Points: {total_points_earned}")
            results_logger.info(f"Total Cost: ${total_cost:.2f}")
            if total_cost > 0:
                results_logger.info(
                    f"Overall Points per Dollar: {total_points_earned / total_cost:.2f}"
                )
            else:
                results_logger.info("Overall Points per Dollar: N/A (no cost)")
            results_logger.info("\nItinerary Details:")
            header = f"{'Hotel Name':<40} {'Location':<20} {'Date':<12} {'Price ($)':<10} {'Points':<10} {'Points/$':<10}"
            results_logger.info(header)
            results_logger.info("=" * len(header))
            for stay in final_itinerary:
                results_logger.info(
                    f"{stay['name']:<40} {stay['location']:<20} {stay['check_in_date']:<12} "
                    f"${stay['total_price']:<9.2f} {stay['points_earned']:<10} "
                    f"{stay['points_per_dollar']:<9.2f}"
                )
        else:
            logging.info( # To stderr
                f"Could not form an itinerary from the results to meet target {TARGET_LOYALTY_POINTS} points."
            )
            results_logger.info( # To stdout
                f"Could not form an itinerary from the results to meet target {TARGET_LOYALTY_POINTS} points."
            )

    logging.info("\n--- Search Complete ---") # To stderr


if __name__ == "__main__":
    main()
