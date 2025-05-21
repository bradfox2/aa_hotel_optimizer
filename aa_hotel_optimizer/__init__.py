# This file makes aa_hotel_optimizer a Python package.

# This file makes aa_hotel_optimizer a Python package.

from .main import (
    analyze_hotel_data,
    discover_place_ids,  # Renamed from discover_phoenix_metro_place_ids
    find_best_hotel_deals,
    generate_date_range,
    get_hotel_results,
    parse_curl_command,  # Added for completeness if used externally
    # select_optimal_stays, # This function was refactored into specific strategies
    # Individual strategy functions (select_optimal_stays_ppd, etc.) are not exported by default
    print_hotel_values_summary,
    search_aadvantage_hotels,
)

__all__ = [
    "find_best_hotel_deals",
    "print_hotel_values_summary",
    # "select_optimal_stays", # Removed as it was refactored
    "discover_place_ids", # Updated name
    "search_aadvantage_hotels",
    "get_hotel_results",
    "parse_curl_command", # Added
    "analyze_hotel_data",
    "generate_date_range",
]
