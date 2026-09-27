"""LP Optimizer, with lazy compatibility exports for the original library API."""

from importlib import import_module

__all__ = [
    "analyze_hotel_data",
    "discover_place_ids",
    "find_best_hotel_deals",
    "generate_date_range",
    "get_hotel_results",
    "parse_curl_command",
    "print_hotel_values_summary",
    "search_aadvantage_hotels",
]


def __getattr__(name):
    if name in __all__:
        return getattr(import_module(".main", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
