import json
import os  # Add os import
import sys  # Add sys import
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import altair as alt

    altair_available = True
except ImportError:
    altair_available = False
    alt = None  # Ensure alt is defined even if import fails
    # This warning will appear in the sidebar if altair is not installed.
    # Consider moving this st.sidebar.warning to a place where sidebar is already defined,
    # or ensure it's called only when the main app flow starts.
    # For now, placing it here and it will be displayed if altair is missing when script runs.
    # A better place might be right after st.sidebar.header if Streamlit initializes sidebar early.
    # However, to avoid conditional execution complexities, we'll show it if altair is missing.
    # This might result in a warning appearing before the sidebar is fully rendered by user's code.
    # A simple print to console or logging might be less intrusive if direct st call is problematic here.
    # For now, let's assume st.sidebar.warning can be called here.
    # If not, this should be moved into the main app body or a setup function.
    # Let's try to display it later, when we are sure sidebar exists.

# Add the project root to sys.path to ensure aa_hotel_optimizer is discoverable
# This assumes streamlit_app.py is in the project root.
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Page config must be the first Streamlit command
st.set_page_config(
    layout="wide",
    page_title="AAdvantage Hotel Optimizer",
    page_icon="🏨",  # Hotel emoji, can be changed to ✈️ or other
)

# Initialize session state for potentially persisted items
if "session_headers_from_file" not in st.session_state:
    st.session_state.session_headers_from_file = {}
# Initialize auth_method_key if it's not already set (e.g., first run)
# This ensures st.session_state.auth_method_key exists before the radio button might rely on it or update it.
# The radio button's `index=0` implies "cURL Command" is the default if the key is absent.
if "auth_method_key" not in st.session_state:
    st.session_state.auth_method_key = "cURL Command"


# Initialize to None or default values before try-except
PREDEFINED_CITY_LISTS: Dict[str, list[str]] = {}
parse_curl_command: Optional[Callable[[str], Tuple[Optional[str], Dict[str, str]]]] = (
    None
)
find_best_hotel_deals: Optional[
    Callable[..., Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, int]]
] = None

# Attempt to import from the local package
try:
    from aa_hotel_optimizer.locations import PREDEFINED_CITY_LISTS as imported_lists
    from aa_hotel_optimizer.main import (
        find_best_hotel_deals as imported_find_deals,
    )
    from aa_hotel_optimizer.main import (
        parse_curl_command as imported_parse_curl,
    )

    # Assign successfully imported items
    PREDEFINED_CITY_LISTS = imported_lists
    find_best_hotel_deals = imported_find_deals
    parse_curl_command = imported_parse_curl

except ImportError as e:
    st.error(
        f"Failed to import necessary modules: {e}. Ensure 'aa_hotel_optimizer' is correctly structured and all dependencies are installed. "
        "If running from the project root, this should work if the package structure is correct."
    )
    # Fallbacks or further error handling
    if find_best_hotel_deals is None:
        st.error(
            "Core function 'find_best_hotel_deals' is missing. App cannot function."
        )
        st.stop()
    if parse_curl_command is None:
        st.warning(
            "Function 'parse_curl_command' is missing. cURL input will not work."
        )
    # If PREDEFINED_CITY_LISTS is still its initial empty value after an import error,
    # it means it wasn't successfully imported from aa_hotel_optimizer.locations.
    # We check 'imported_lists' not in locals() to be sure we are in the except block due to its import failing.
    if not PREDEFINED_CITY_LISTS and "imported_lists" not in locals():
        PREDEFINED_CITY_LISTS = {"Error": ["Could not load city lists"]}  # Fallback
        st.warning("Predefined city lists are not available.")


# Default target points, can be overridden by user input
DEFAULT_TARGET_POINTS = 200000

# Display Altair warning in sidebar if it's not available
if not altair_available:
    st.sidebar.warning(
        "Altair library not found. Some charts may use fallbacks. Install with: pip install altair"
    )

st.title("AAdvantage Hotel Optimizer")

with st.expander("How to Use This App & Important Notes", expanded=False):
    st.markdown(
        """
        ### Instructions for Obtaining cURL Command from AA Hotels Website:

        To use the "cURL Command" authentication method, you'll need to copy a network request from your browser after performing a hotel search on the [American Airlines Hotels website](https://www.aadvantagehotels.com/).

        1.  **Open Developer Tools:** In your web browser (e.g., Chrome, Firefox, Edge), navigate to the AA Hotels website. Before or after initiating a search, open your browser's developer tools. This is usually done by right-clicking on the page and selecting "Inspect" or "Inspect Element," then navigating to the "Network" tab. You can also typically use a keyboard shortcut like `F12` or `Ctrl+Shift+I` (Windows/Linux) or `Cmd+Opt+I` (Mac).

        2.  **Perform a Hotel Search:** On the AA Hotels website, enter your desired search criteria (destination, dates, etc.) and click the search button.

        3.  **Find the Search Request:** In the "Network" tab of your developer tools, you'll see a list of requests. Look for a request that starts with `searchRequest?...` or similar, which corresponds to the hotel search API call. It will likely be an `XHR` (XMLHttpRequest) or `fetch` type request.
        You can filter the requests by typing "search" or "searchRequest" into the filter box in the Network tab to help locate it.
        """
    )
    st.image(
        os.path.join(current_dir, "assets", "curl1.png"),
        caption="Example: Finding the searchRequest in browser developer tools.",
    )
    st.image(
        os.path.join(current_dir, "assets", "curl.png"),
        caption="Example: Finding the searchRequest in browser developer tools.",
    )
    st.markdown(
        """
        4.  **Copy as cURL:**
            *   **Chrome/Edge:** Right-click on the `searchRequest` (or equivalent) network call. Navigate to `Copy` > `Copy as cURL (bash)` or `Copy as cURL (cmd)` if on Windows.
            *   **Firefox:** Right-click on the request. Navigate to `Copy Value` > `Copy as cURL`.

        5.  **Paste into App:** Paste the copied cURL command into the "Paste cURL Command" text area in the sidebar of this application when the "cURL Command" authentication method is selected.

        ### Important Warning:

        *   **Use Responsibly:** This tool interacts with the American Airlines Hotels booking platform. Excessive, rapid, or unusual search patterns could potentially be flagged by American Airlines.
        *   **Uncertainty of Consequences:** The consequences of such flagging are unknown and could range from temporary IP blocks to account-related actions. Use this tool at your own discretion and avoid overly frequent or very broad searches if concerned.
        *   **No Guarantees:** This tool is provided as-is, without any guarantees regarding its continued functionality or any liabilities arising from its use.
        """
    )


st.sidebar.header("Search Parameters")

# --- Search Type Selection ---
search_type = st.sidebar.radio(
    "Search Type:",
    ("Specific Location(s)", "Broad Points Optimization"),
    key="search_type_selector",
    help="Choose 'Specific Location(s)' to search one or more particular cities. Choose 'Broad Points Optimization' to scan predefined regions or many custom cities for general point earning.",
)

# --- Conditional City/Region Inputs ---
city_query_for_backend = ""  # This will hold the city string passed to the backend
cities_to_process_log = []  # For logging/displaying what will be searched

if search_type == "Specific Location(s)":
    specific_city_input = st.sidebar.text_input(
        "City to Search:",
        "Las Vegas",
        help="Enter the city you want to search.",
        key="specific_city_input",
    )
    if specific_city_input:
        cities_to_process_log = [specific_city_input.strip()]
        city_query_for_backend = cities_to_process_log[
            0
        ]  # Backend currently takes one city

elif search_type == "Broad Points Optimization":
    selected_region_names = st.sidebar.multiselect(
        "Select Regions/City Lists:",
        options=list(PREDEFINED_CITY_LISTS.keys()),
        help="Select one or more predefined lists of cities to search.",
        key="selected_region_names",
    )
    custom_cities_input = st.sidebar.text_area(
        "Or, add custom cities (comma-separated):",
        help="Enter additional city names, separated by commas.",
        key="custom_cities_input",
    )

    temp_cities_list = []
    if selected_region_names:
        for region_name in selected_region_names:
            if region_name in PREDEFINED_CITY_LISTS:
                temp_cities_list.extend(PREDEFINED_CITY_LISTS[region_name])

    if custom_cities_input:
        custom_cities = [
            city.strip() for city in custom_cities_input.split(",") if city.strip()
        ]
        temp_cities_list.extend(custom_cities)

    if temp_cities_list:
        cities_to_process_log = sorted(
            list(set(temp_cities_list))
        )  # Unique, sorted list
        # For now, backend only takes one city. We'll pass the first one.
        # This will be updated when backend handles List[str].
        city_query_for_backend = cities_to_process_log[0]
        st.sidebar.caption(
            f"Will process {len(cities_to_process_log)} cities (currently sending first to backend: {city_query_for_backend}). Full list display below search button soon."
        )
    else:
        st.sidebar.warning(
            "Please select a region or enter custom cities for broad optimization."
        )

# --- Common Search Parameters ---
default_start_date = date.today()
default_end_date = default_start_date + timedelta(days=1)

start_date_input = st.sidebar.date_input(
    "Start Date", default_start_date, key="start_date_picker"
)
end_date_input = st.sidebar.date_input(
    "End Date", default_end_date, key="end_date_picker"
)

aa_card_bonus_checkbox = st.sidebar.checkbox(
    "AA Credit Card Bonus (10 miles/$)",
    value=True,
    help="Select if you are using an AAdvantage credit card for an extra 10 miles per dollar spent.",
    key="aa_card_bonus_checkbox",
)

aa_card_miles_rate_input = 1  # Default if checkbox is off
if aa_card_bonus_checkbox:
    aa_card_miles_rate_input = st.sidebar.radio(
        "AA Card Miles Rate on Spend:",
        options=[1, 10],
        index=0,  # Default to 1x
        format_func=lambda x: f"{x}x miles per dollar",
        key="aa_card_miles_rate_selector",
        help="Select the miles earning rate on card spend (1x or 10x). Effective only if AA Card Bonus is checked.",
    )

current_lp_balance_input = st.sidebar.number_input(
    "Current Loyalty Points Balance",
    min_value=0,
    value=0,
    step=100,
    help="Enter your current AAdvantage Loyalty Points balance to factor in status bonuses.",
    key="current_lp_balance_input",
)

if st.sidebar.button("Search for Hotel Deals"):
    # --- BEGIN: Fetch/Calculate all necessary values from st.session_state ---
    auth_method_on_click = st.session_state.get("auth_method_key", "cURL Command")
    curl_content_on_click = st.session_state.get("curl_command_value", "")

    local_session_headers_for_search: Dict[str, str] = {}

    if auth_method_on_click == "cURL Command" and curl_content_on_click:
        try:
            if callable(parse_curl_command):
                parsed_url, parsed_headers_from_curl = parse_curl_command(
                    curl_content_on_click
                )
                if parsed_headers_from_curl:
                    local_session_headers_for_search = parsed_headers_from_curl
                    st.sidebar.success(
                        "cURL command parsed successfully for this search."
                    )
                    if "Cookie" not in local_session_headers_for_search:
                        st.sidebar.warning(
                            "Cookie not found in cURL command. Requests might fail."
                        )
                else:
                    st.sidebar.error(
                        "Could not parse headers from cURL command for this search."
                    )
            else:
                st.sidebar.error("cURL parsing function is not available.")
        except Exception as e:
            st.sidebar.error(f"Error parsing cURL command for this search: {e}")
            # local_session_headers_for_search remains {}
    elif auth_method_on_click == "Manual Cookie/XSRF":
        cookie_val = st.session_state.get("cookie_input_value", "")
        xsrf_val = st.session_state.get("xsrf_token_input_value", "")
        if cookie_val:
            local_session_headers_for_search["Cookie"] = cookie_val.strip()
        if xsrf_val:
            local_session_headers_for_search["X-XSRF-TOKEN"] = xsrf_val.strip()
    elif auth_method_on_click == "JSON File":
        if (
            "session_headers_from_file" in st.session_state
            and st.session_state.session_headers_from_file
        ):
            local_session_headers_for_search = (
                st.session_state.session_headers_from_file
            )
            # st.sidebar.info("Using stored JSON headers for this search.") # Optional: can be verbose

    # Define optimization_strategy_options locally or ensure it's defined globally before this block
    # For this refactor, defining locally to ensure self-containment if UI order changes.
    # However, if this dict is large or used elsewhere, global definition before button is better.
    # Given it's already defined globally later, we can rely on that, but for robustness if UI order changes:
    optimization_strategy_options_config = {
        "Maximize Points per Dollar (Greedy PPD)": "points_per_dollar",
        "Minimize Cost for Target LP (Greedy Cheapest Stays)": "minimize_cost_for_target_lp",
        "Minimize Cost for Target LP (Dynamic Programming)": "dp_minimize_cost",
        "Fastest Calendar Time to Target LP (Overlaps OK)": "fastest_calendar_time_lp",
    }
    selected_strategy_key_on_click = st.session_state.get(
        "selected_strategy_display_key",
        list(optimization_strategy_options_config.keys())[0],
    )
    optimization_strategy_on_click = optimization_strategy_options_config[
        selected_strategy_key_on_click
    ]

    max_overlaps_on_click = 5  # Default
    if optimization_strategy_on_click == "fastest_calendar_time_lp":
        max_overlaps_on_click = st.session_state.get("max_concurrent_overlaps_input", 5)

    iterative_search_on_click = st.session_state.get("iterative_search_checkbox", False)

    miles_cents_on_click = st.session_state.get("miles_value_cents_input", 1.5)
    miles_rate_on_click = miles_cents_on_click / 100.0
    # --- END: Fetch/Calculate all necessary values from st.session_state ---

    # Validation for city input (uses globally defined city_query_for_backend, start_date_input, etc.)
    if not city_query_for_backend:
        if search_type == "Specific Location(s)":
            st.error("Please enter a city for 'Specific Location(s)' search.")
        elif search_type == "Broad Points Optimization":
            st.error(
                "Please select a region or enter custom cities for 'Broad Points Optimization'."
            )
        st.stop()
    elif start_date_input > end_date_input:
        st.error("Start date cannot be after end date.")
        st.stop()
    else:
        progress_bar_placeholder = st.empty()
        status_text_placeholder = st.empty()

        # Updated progress callback for multi-city and iterative search feedback
        # It now uses iterative_search_on_click
        def streamlit_progress_callback(
            completed_dates_in_city: int,
            total_dates_in_city: int,
            current_pass: Optional[int] = None,
            pass_end_date: Optional[str] = None,
            current_city_idx: Optional[int] = None,
            total_cities: Optional[int] = None,
            current_city_name: Optional[str] = None,
            is_final_city_in_pass: bool = False,
            status_message: Optional[str] = None,
        ):
            progress = 0.0
            if total_dates_in_city > 0:
                progress = completed_dates_in_city / total_dates_in_city
            progress_bar_placeholder.progress(progress)
            msg_parts = []
            if current_pass is not None:
                msg_parts.append(f"Pass {current_pass}")
            if (
                total_cities
                and total_cities > 1
                and current_city_idx is not None
                and current_city_name
            ):
                msg_parts.append(
                    f"City {current_city_idx}/{total_cities} ('{current_city_name}')"
                )
            if total_dates_in_city > 0:
                msg_parts.append(
                    f"Processed {completed_dates_in_city}/{total_dates_in_city} dates"
                )
            if pass_end_date:
                msg_parts.append(f"(window up to {pass_end_date})")
            if status_message:
                msg_parts.append(f"- {status_message}")
            elif iterative_search_on_click and is_final_city_in_pass:
                msg_parts.append("Pass complete.")
            elif iterative_search_on_click:
                msg_parts.append("Searching...")
            status_text_placeholder.text(" | ".join(msg_parts))

        def style_ppd_column(df, column_name="points_per_dollar"):
            if (
                column_name in df.columns
                and pd.api.types.is_numeric_dtype(df[column_name])
                and not df[column_name].empty
            ):
                if df[column_name].count() > 0:
                    return df.style.background_gradient(
                        subset=[column_name], cmap="Greens", low=0.1, high=1.0
                    )
            return df

        status_text_placeholder.text(
            f"Initiating search for: {city_query_for_backend}..."
        )
        if (
            search_type == "Broad Points Optimization"
            and len(cities_to_process_log) > 1
        ):
            status_text_placeholder.text(
                f"Initiating search for {city_query_for_backend} (first of {len(cities_to_process_log)} cities). Full multi-city backend processing is pending."
            )

        try:
            progress_bar_placeholder.progress(0)
            if not callable(find_best_hotel_deals):
                st.error(
                    "Core search function 'find_best_hotel_deals' is not available. App cannot proceed."
                )
                st.stop()

            all_hotel_options, final_itinerary, total_cost, total_points_earned = (
                find_best_hotel_deals(
                    city_queries=cities_to_process_log,
                    start_date=start_date_input,
                    end_date=end_date_input,
                    session_headers=local_session_headers_for_search,  # Use locally prepared headers
                    target_loyalty_points=st.session_state.get(
                        "target_loyalty_points_input", DEFAULT_TARGET_POINTS
                    ),
                    progress_callback=streamlit_progress_callback,
                    aa_card_bonus=aa_card_bonus_checkbox,
                    aa_card_miles_rate=aa_card_miles_rate_input,
                    optimization_strategy=optimization_strategy_on_click,  # Use fetched value
                    iterative_search_for_lp_target=iterative_search_on_click,  # Use fetched value
                    current_lp_balance=current_lp_balance_input,
                    max_overlaps=(
                        max_overlaps_on_click  # Use fetched value
                        if optimization_strategy_on_click == "fastest_calendar_time_lp"
                        else None
                    ),
                    miles_value_rate=miles_rate_on_click,  # Use fetched value
                )
            )

            progress_bar_placeholder.empty()
            status_text_placeholder.empty()

            st.subheader("Optimal Loyalty Points Strategy")
            if final_itinerary:
                total_miles_earned_itinerary = sum(
                    s.get("miles_earned", 0) for s in final_itinerary
                )
                total_miles_value_itinerary = sum(
                    s.get("miles_value", 0.0) for s in final_itinerary
                )
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                col1.metric(
                    "Target LP",
                    f"{st.session_state.get('target_loyalty_points_input', DEFAULT_TARGET_POINTS):,}",
                )
                col2.metric("Achieved LP", f"{total_points_earned:,}")
                col3.metric("Total Cost", f"${total_cost:,.2f}")
                net_new_lp_from_itinerary = (
                    total_points_earned - current_lp_balance_input
                )
                overall_ppd = (
                    (net_new_lp_from_itinerary / total_cost)
                    if total_cost > 0 and net_new_lp_from_itinerary > 0
                    else 0
                )
                col4.metric("Overall LP PPD", f"{overall_ppd:.2f}")
                col5.metric("Total Miles Earned", f"{total_miles_earned_itinerary:,}")
                col6.metric("Total Miles Value", f"${total_miles_value_itinerary:,.2f}")

                st.markdown("---")
                st.write("Itinerary Details:")
                df_itinerary = pd.DataFrame(final_itinerary)
                display_cols_itinerary = [
                    "name",
                    "location",
                    "check_in_date",
                    "total_price",
                    "api_points_earned",
                    "card_bonus_points",
                    "status_bonus_points",
                    "points_earned_final_for_itinerary",
                    "points_per_dollar_final_for_itinerary",
                    "miles_earned",
                    "miles_value",
                ]
                df_itinerary_display = df_itinerary[
                    [
                        col
                        for col in display_cols_itinerary
                        if col in df_itinerary.columns
                    ]
                ].copy()
                column_config_itinerary = {
                    "name": st.column_config.TextColumn("Hotel Name", width="large"),
                    "location": "Location",
                    "check_in_date": "Check-in",
                    "total_price": st.column_config.NumberColumn(
                        "Price", format="$%.2f"
                    ),
                    "api_points_earned": st.column_config.NumberColumn(
                        "API Points",
                        format="%d",
                        help="Base points from the hotel booking.",
                    ),
                    "card_bonus_points": st.column_config.NumberColumn(
                        "Card Bonus",
                        format="%d",
                        help="Points from AA credit card (10 miles/$).",
                    ),
                    "status_bonus_points": st.column_config.NumberColumn(
                        "Status Bonus",
                        format="%d",
                        help="Points from AAdvantage status bonus.",
                    ),
                    "points_earned_final_for_itinerary": st.column_config.NumberColumn(
                        "Total Stay LP",
                        format="%d",
                        help="Total Loyalty Points for this stay (API + Card + Status).",
                    ),
                    "points_per_dollar_final_for_itinerary": st.column_config.NumberColumn(
                        "Stay LP PPD",
                        format="%.2f",
                        help="Total Loyalty Points / Price for this stay.",
                    ),
                    "miles_earned": st.column_config.NumberColumn(
                        "Miles Earned",
                        format="%d",
                        help="Total miles earned for this stay (LPs + spend miles if card used).",
                    ),
                    "miles_value": st.column_config.NumberColumn(
                        "Miles Value ($)",
                        format="$%.2f",
                        help="Value of miles earned for this stay (at $0.015/mile).",
                    ),
                }
                active_column_config_itinerary = {
                    k: v
                    for k, v in column_config_itinerary.items()
                    if k in df_itinerary_display.columns
                }
                styled_df_itinerary = style_ppd_column(
                    df_itinerary_display,
                    column_name="points_per_dollar_final_for_itinerary",
                )
                st.dataframe(
                    styled_df_itinerary, column_config=active_column_config_itinerary
                )
            else:
                st.write(
                    f"Could not form an itinerary to meet the target of {st.session_state.get('target_loyalty_points_input', DEFAULT_TARGET_POINTS)} points from the found options."
                )

            st.subheader("All Hotel Options Found")
            if all_hotel_options:
                df_all_options = pd.DataFrame(all_hotel_options)
                display_cols_all = [
                    "name",
                    "location",
                    "check_in_date",
                    "total_price",
                    "api_points_earned",
                    "card_bonus_points",
                    "points_earned",
                    "points_per_dollar",
                    "miles_earned",
                    "miles_value",
                    "refundability",
                    "star_rating",
                    "user_rating",
                ]
                df_all_options_display = df_all_options[
                    [col for col in display_cols_all if col in df_all_options.columns]
                ].copy()
                if "refundability" in df_all_options_display.columns:
                    df_all_options_display.loc[:, "refundability"] = (
                        df_all_options_display["refundability"].apply(
                            lambda x: "✅ Refundable"
                            if x == "REFUNDABLE"
                            else (
                                "❌ Non-Refundable"
                                if x == "NON_REFUNDABLE"
                                else "❓ Unknown"
                            )
                        )
                    )
                if "star_rating" in df_all_options_display.columns:
                    df_all_options_display.loc[:, "star_rating_display"] = (
                        df_all_options_display["star_rating"].apply(
                            lambda x: f"{x:.1f} ⭐" if pd.notna(x) and x > 0 else "N/A"
                        )
                    )
                    display_cols_all = [
                        col if col != "star_rating" else "star_rating_display"
                        for col in display_cols_all
                    ]
                final_display_cols_all = [
                    col
                    for col in display_cols_all
                    if col in df_all_options_display.columns
                ]
                if (
                    "points_per_dollar" in df_all_options_display.columns
                    and pd.api.types.is_numeric_dtype(
                        df_all_options_display["points_per_dollar"]
                    )
                ):
                    df_all_options_display = df_all_options_display.sort_values(
                        by=["points_per_dollar"], ascending=False
                    )

                column_config_all = {
                    "name": st.column_config.TextColumn("Hotel Name", width="large"),
                    "location": "Location",
                    "check_in_date": "Check-in",
                    "total_price": st.column_config.NumberColumn(
                        "Price", format="$%.2f"
                    ),
                    "api_points_earned": st.column_config.NumberColumn(
                        "API Points",
                        format="%d",
                        help="Base points from the hotel booking.",
                    ),
                    "card_bonus_points": st.column_config.NumberColumn(
                        "Card Bonus",
                        format="%d",
                        help="Points from AA credit card (10 miles/$).",
                    ),
                    "points_earned": st.column_config.NumberColumn(
                        "Base+Card LP",
                        format="%d",
                        help="API Points + Card Bonus. Status bonus is applied during itinerary selection.",
                    ),
                    "points_per_dollar": st.column_config.NumberColumn(
                        "Base+Card LP PPD",
                        format="%.2f",
                        help="PPD based on API Points + Card Bonus (LPs only).",
                    ),
                    "miles_earned": st.column_config.NumberColumn(
                        "Miles Earned (Stay)",
                        format="%d",
                        help="Total miles for this stay (LPs + spend miles if card used), reflects final calculation.",
                    ),
                    "miles_value": st.column_config.NumberColumn(
                        "Miles Value (Stay, $)",
                        format="$%.2f",
                        help="Value of miles for this stay (at $0.015/mile), reflects final calculation.",
                    ),
                    "refundability": "Refundable",
                    "star_rating_display": st.column_config.TextColumn("Stars"),
                    "user_rating": st.column_config.NumberColumn(
                        "Rating", format="%.1f"
                    ),
                }
                active_column_config_all = {
                    k: v
                    for k, v in column_config_all.items()
                    if k in final_display_cols_all
                }
                styled_df_all_options = style_ppd_column(
                    df_all_options_display[final_display_cols_all]
                )
                st.dataframe(
                    styled_df_all_options, column_config=active_column_config_all
                )

                st.markdown("---")
                st.subheader("Visualizations for All Hotel Options")
                col1, col2 = st.columns(2)
                with col1:
                    if (
                        "points_per_dollar" in df_all_options_display.columns
                        and not df_all_options_display["points_per_dollar"].empty
                    ):
                        st.write("Distribution of Points per Dollar")
                        st.bar_chart(
                            df_all_options_display["points_per_dollar"]
                            .value_counts()
                            .sort_index()
                        )
                    else:
                        st.write("Points per Dollar data not available for histogram.")
                with col2:
                    if (
                        "total_price" in df_all_options_display.columns
                        and "points_per_dollar" in df_all_options_display.columns
                        and not df_all_options_display[
                            ["total_price", "points_per_dollar"]
                        ].empty
                    ):
                        st.write("Price vs. Points per Dollar (PPD)")
                        scatter_df = df_all_options_display[
                            ["total_price", "points_per_dollar"]
                        ].copy()
                        scatter_df.columns = ["Total Price ($)", "Base+Card PPD"]
                        st.scatter_chart(
                            scatter_df, x="Total Price ($)", y="Base+Card PPD"
                        )
                    else:
                        st.write("Price/PPD data not available for scatter plot.")
                st.markdown("---")

                st.subheader("Additional Data Distributions")

                def plot_histogram(
                    df_plot, col_name, chart_title, x_label, altair_is_available_param
                ):  # Renamed altair_is_available to avoid conflict
                    if (
                        col_name in df_plot.columns
                        and not df_plot[col_name].empty
                        and df_plot[col_name].count() > 0
                    ):
                        st.write(chart_title)
                        data_for_plot = df_plot[[col_name]].dropna()
                        if data_for_plot.empty:
                            st.write(
                                f"No valid data for {chart_title} after dropping NaNs."
                            )
                            return
                        if (
                            altair_is_available_param and alt is not None
                        ):  # Use the parameter
                            try:
                                hist_chart = (
                                    alt.Chart(data_for_plot)
                                    .mark_bar()
                                    .encode(
                                        alt.X(
                                            f"{col_name}:Q",
                                            bin=alt.Bin(maxbins=20),
                                            title=x_label,
                                        ),
                                        alt.Y("count()", title="Number of Hotels"),
                                    )
                                    .properties()
                                )
                                st.altair_chart(hist_chart, use_container_width=True)
                            except Exception as ex:
                                st.write(
                                    f"Could not generate Altair chart for {chart_title}: {ex}. Falling back."
                                )
                                value_counts_data = (
                                    data_for_plot[col_name].value_counts().sort_index()
                                )
                                if not value_counts_data.empty:
                                    st.bar_chart(value_counts_data)
                                else:
                                    st.write(
                                        f"No data to plot with fallback for {chart_title}."
                                    )
                        else:
                            value_counts_data = (
                                data_for_plot[col_name].value_counts().sort_index()
                            )
                            if not value_counts_data.empty:
                                st.bar_chart(value_counts_data)
                            else:
                                st.write(
                                    f"No data to plot with st.bar_chart for {chart_title}."
                                )
                    else:
                        st.write(
                            f"{chart_title} data not available or empty in the dataset."
                        )

                viz_col1, viz_col2, viz_col3 = st.columns(3)
                with viz_col1:
                    plot_histogram(
                        df_all_options_display,
                        "total_price",
                        "Distribution of Total Price",
                        "Total Price ($)",
                        altair_available,
                    )  # Pass global altair_available
                with viz_col2:
                    temp_df_ratings = df_all_options_display.copy()
                    if "user_rating" in temp_df_ratings.columns:
                        temp_df_ratings["user_rating_numeric"] = pd.to_numeric(
                            temp_df_ratings["user_rating"], errors="coerce"
                        )
                        plot_histogram(
                            temp_df_ratings,
                            "user_rating_numeric",
                            "Distribution of User Rating",
                            "User Rating",
                            altair_available,
                        )  # Pass global altair_available
                    else:
                        st.write("User Rating data not available.")
                with viz_col3:
                    plot_histogram(
                        df_all_options_display,
                        "star_rating",
                        "Distribution of Star Rating",
                        "Star Rating (Numeric)",
                        altair_available,
                    )  # Pass global altair_available
                st.markdown("---")
            else:
                st.write("No hotel options found for the given criteria.")
        except Exception as e:
            progress_bar_placeholder.empty()
            status_text_placeholder.empty()
            st.error(f"An error occurred during the search: {e}")
            st.exception(e)
else:
    st.info(
        "Enter search parameters in the sidebar and click 'Search for Hotel Deals'."
    )

st.sidebar.markdown("---")
st.sidebar.subheader("Authentication Details")
st.sidebar.caption(
    "Note: Authenticated requests (e.g., via cURL or headers file) are recommended to see personalized bonus levels, "
    "promotional offers, and accurate mileage earnings based on your AAdvantage status or specific card benefits."
)

# Store the auth method from *before* the radio button potentially changes it in this run
# This helps detect if the user switched away from "JSON File" method
previous_auth_method_for_json_handling = st.session_state.auth_method_key

# Render the radio button. Its state is now updated in st.session_state.auth_method_key
st.sidebar.radio(
    "Authentication Method",
    ("cURL Command", "Manual Cookie/XSRF", "JSON File"),
    index=0,  # Default to "cURL Command" if key not in session_state or is None
    help="Choose how to provide authentication details. cURL is often easiest if you can copy it from your browser's developer tools.",
    key="auth_method_key",
)
# current_auth_method is the source of truth for the selected auth method
current_auth_method = st.session_state.auth_method_key

# If auth method was "JSON File" and has now changed to something else, clear the stored JSON headers
if (
    previous_auth_method_for_json_handling == "JSON File"
    and current_auth_method != "JSON File"
):
    st.session_state.session_headers_from_file = {}
    # st.sidebar.caption("Cleared previously uploaded JSON headers due to method change.") # Optional user feedback

session_headers: Dict[str, str] = {}  # Initialize for this script run
# This variable will hold the text from the cURL input area if that's the selected method.
# It's populated by the widget itself, drawing from st.session_state.curl_command_value.
curl_command_text_area_content = ""


if current_auth_method == "Manual Cookie/XSRF":
    # Widgets use keys, so their values are in st.session_state
    st.sidebar.text_area(
        "Cookie String",
        height=100,
        help="Paste the full cookie string here.",
        key="cookie_input_value",
    )
    st.sidebar.text_input(
        "XSRF Token", help="Paste the XSRF token here.", key="xsrf_token_input_value"
    )
    # Populate session_headers from the sticky session state values
    if st.session_state.get("cookie_input_value"):
        session_headers["Cookie"] = st.session_state.cookie_input_value.strip()
    if st.session_state.get("xsrf_token_input_value"):
        session_headers["X-XSRF-TOKEN"] = (
            st.session_state.xsrf_token_input_value.strip()
        )

elif current_auth_method == "cURL Command":
    # The text area widget populates st.session_state.curl_command_value
    # and returns its current content to curl_command_text_area_content.
    curl_command_text_area_content = st.sidebar.text_area(
        "Paste cURL Command",
        height=200,
        help="Paste the full cURL command copied from your browser's network tab. This will attempt to parse headers and cookies.",
        key="curl_command_value",
    )
    # session_headers from cURL are parsed and populated upon button click.

elif current_auth_method == "JSON File":
    uploaded_headers_file = st.sidebar.file_uploader(
        "Upload Session Headers JSON file",
        type=["json"],
        key="uploaded_headers_file_key",  # Added key
    )
    if uploaded_headers_file is not None:  # A new file has been uploaded
        try:
            # Parse and store in st.session_state to persist across reruns
            st.session_state.session_headers_from_file = json.load(
                uploaded_headers_file
            )
            session_headers = (
                st.session_state.session_headers_from_file
            )  # Use for current run
            st.sidebar.success("Headers file loaded and stored in session.")
        except json.JSONDecodeError:
            st.sidebar.error("Error decoding JSON from headers file.")
            st.session_state.session_headers_from_file = {}  # Clear persisted on error
            session_headers = {}  # Clear for current run
        except Exception as e:
            st.sidebar.error(f"Error loading headers: {e}")
            st.session_state.session_headers_from_file = {}
            session_headers = {}
    elif (
        st.session_state.session_headers_from_file
    ):  # No new file, but we have persisted headers
        session_headers = st.session_state.session_headers_from_file
        st.sidebar.info("Using previously uploaded headers.")

    if (
        st.session_state.session_headers_from_file
    ):  # Show clear button if there are stored headers
        if st.sidebar.button(
            "Clear Stored JSON Headers", key="clear_json_headers_button"
        ):
            st.session_state.session_headers_from_file = {}
            session_headers = {}  # Clear for current run too

st.sidebar.markdown("---")
st.sidebar.subheader("Optimization Strategy")
optimization_strategy_options = {
    "Maximize Points per Dollar (Greedy PPD)": "points_per_dollar",
    "Minimize Cost for Target LP (Greedy Cheapest Stays)": "minimize_cost_for_target_lp",
    "Minimize Cost for Target LP (Dynamic Programming)": "dp_minimize_cost",
    "Fastest Calendar Time to Target LP (Overlaps OK)": "fastest_calendar_time_lp",
}
selected_strategy_display = st.sidebar.radio(
    "Choose Optimization Method:",
    options=list(optimization_strategy_options.keys()),
    index=0,  # Default to PPD
    help=(
        "Maximize PPD: Good for general high-value stays.\n"
        "Minimize Cost (Greedy): Finds the cheapest stays to hit LP target quickly.\n"
        "Minimize Cost (DP): More thorough, aims for true minimum cost to hit LP target (can be slower).\n"
        "Fastest Calendar Time to Target LP: Aims to complete the LP target by the earliest possible calendar date, allowing stays to overlap."
    ),
    key="selected_strategy_display_key",
)
optimization_strategy_value = optimization_strategy_options[selected_strategy_display]

# Add conditional input for max overlaps for the specific strategy
max_concurrent_overlaps = 5  # Default value
if optimization_strategy_value == "fastest_calendar_time_lp":
    max_concurrent_overlaps = st.sidebar.number_input(
        "Max Concurrent Overlaps:",
        min_value=1,
        max_value=20,  # Arbitrary upper limit, can be adjusted
        value=5,
        step=1,
        key="max_concurrent_overlaps_input",
        help="Set the maximum number of hotel stays that can overlap on any given day for the 'Fastest Calendar Time' strategy.",
    )

st.sidebar.markdown("---")
st.sidebar.subheader("Search Mode")
target_loyalty_points = st.sidebar.number_input(
    "Target Loyalty Points",
    min_value=0,
    value=DEFAULT_TARGET_POINTS,
    step=1000,
    key="target_loyalty_points_input",
)
iterative_search_checkbox = st.sidebar.checkbox(
    "Search future dates until LP target is met",
    value=False,
    help="If checked, the search will extend into future dates (up to ~6 months or as configured) until the LP target is met.",
    key="iterative_search_checkbox",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Advanced Settings")
miles_value_cents_input = st.sidebar.number_input(
    "Mileage Value (cents per mile)",
    min_value=0.1,
    max_value=10.0,
    value=1.5,
    step=0.1,
    format="%.2f",
    key="miles_value_cents_input",
    help="Set your valuation of one AAdvantage mile in cents (e.g., 1.5 for 1.5¢).",
)
# Convert cents to decimal for backend (e.g., 1.5 cents -> 0.015)
miles_value_rate_for_backend = miles_value_cents_input / 100.0

st.sidebar.markdown("---")
