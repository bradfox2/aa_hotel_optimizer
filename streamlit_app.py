import json
import os  # Add os import
import sys  # Add sys import
from datetime import date, timedelta
from typing import Dict, Optional

import pandas as pd
import streamlit as st

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

# Attempt to import from the local package
try:
    from aa_hotel_optimizer.locations import PREDEFINED_CITY_LISTS
    from aa_hotel_optimizer.main import (
        find_best_hotel_deals,
        parse_curl_command,
    )
except ImportError as e:
    st.error(
        f"Failed to import necessary modules: {e}. Ensure 'aa_hotel_optimizer' is correctly structured and all dependencies are installed. "
        "If running from the project root, this should work if the package structure is correct."
    )
    # Provide more granular fallbacks or stop if critical components are missing
    if "find_best_hotel_deals" not in globals():
        st.error(
            "Core function 'find_best_hotel_deals' is missing. App cannot function."
        )
        st.stop()
    if "parse_curl_command" not in globals():
        st.warning(
            "Function 'parse_curl_command' is missing. cURL input will not work."
        )
    if "PREDEFINED_CITY_LISTS" not in globals():
        PREDEFINED_CITY_LISTS = {"Error": ["Could not load city lists"]}
        st.warning("Predefined city lists are not available.")


# Default target points, can be overridden by user input
DEFAULT_TARGET_POINTS = 250000

st.title("AAdvantage Hotel Optimizer")

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
        "City to Search:", "Phoenix", help="Enter the city you want to search."
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
    )
    custom_cities_input = st.sidebar.text_area(
        "Or, add custom cities (comma-separated):",
        help="Enter additional city names, separated by commas.",
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

start_date_input = st.sidebar.date_input("Start Date", default_start_date)
end_date_input = st.sidebar.date_input("End Date", default_end_date)

target_loyalty_points = st.sidebar.number_input(
    "Target Loyalty Points", min_value=0, value=DEFAULT_TARGET_POINTS, step=1000
)

aa_card_bonus_checkbox = st.sidebar.checkbox(
    "AA Credit Card Bonus (10 miles/$)",
    value=False,
    help="Select if you are using an AAdvantage credit card for an extra 10 miles per dollar spent.",
)

current_lp_balance_input = st.sidebar.number_input(
    "Current Loyalty Points Balance",
    min_value=0,
    value=0,
    step=100,
    help="Enter your current AAdvantage Loyalty Points balance to factor in status bonuses.",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Search Mode")
iterative_search_checkbox = st.sidebar.checkbox(
    "Search future dates until LP target is met",
    value=False,
    help="If checked, the search will extend into future dates (up to ~6 months or as configured) until the LP target is met.",
)
# Optionally, add an input for max_search_days if iterative_search_checkbox is checked.
# For now, we'll use the default from the backend.
# max_search_days_input = st.sidebar.number_input(
# "Max search days ahead (for iterative search)", min_value=30, max_value=365, value=180, step=30,
# disabled=not iterative_search_checkbox
# )


st.sidebar.markdown("---")
st.sidebar.subheader("Optimization Strategy")
optimization_strategy_options = {
    "Maximize Points per Dollar (Greedy PPD)": "points_per_dollar",
    "Minimize Cost for Target LP (Greedy Cheapest Stays)": "minimize_cost_for_target_lp",
    "Minimize Cost for Target LP (Dynamic Programming)": "dp_minimize_cost",
}
selected_strategy_display = st.sidebar.radio(
    "Choose Optimization Method:",
    options=list(optimization_strategy_options.keys()),
    index=0,  # Default to PPD
    help=(
        "Maximize PPD: Good for general high-value stays.\n"
        "Minimize Cost (Greedy): Finds the cheapest stays to hit LP target quickly.\n"
        "Minimize Cost (DP): More thorough, aims for true minimum cost to hit LP target (can be slower)."
    ),
)
optimization_strategy_value = optimization_strategy_options[selected_strategy_display]


st.sidebar.markdown("---")
st.sidebar.subheader("Authentication Details")

auth_method = st.sidebar.radio(
    "Authentication Method",
    ("Manual Cookie/XSRF", "cURL Command", "JSON File"),
    index=0,
    help="Choose how to provide authentication details. cURL is often easiest if you can copy it from your browser's developer tools.",
)

session_headers: Dict[str, str] = {}
curl_command_input = ""

if auth_method == "Manual Cookie/XSRF":
    cookie_input = st.sidebar.text_area(
        "Cookie String", height=100, help="Paste the full cookie string here."
    )
    xsrf_token_input = st.sidebar.text_input(
        "XSRF Token", help="Paste the XSRF token here."
    )
    if cookie_input:
        session_headers["Cookie"] = cookie_input.strip()
    if xsrf_token_input:
        session_headers["X-XSRF-TOKEN"] = xsrf_token_input.strip()
elif auth_method == "cURL Command":
    curl_command_input = st.sidebar.text_area(
        "Paste cURL Command",
        height=200,
        help="Paste the full cURL command copied from your browser's network tab. This will attempt to parse headers and cookies.",
    )
    # Parsing will happen when the search button is clicked
elif auth_method == "JSON File":
    uploaded_headers_file = st.sidebar.file_uploader(
        "Upload Session Headers JSON file", type=["json"]
    )
    if uploaded_headers_file is not None:
        try:
            session_headers = json.load(uploaded_headers_file)
            st.sidebar.success("Headers file loaded successfully!")
        except json.JSONDecodeError:
            st.sidebar.error("Error decoding JSON from headers file.")
            session_headers = {}
        except Exception as e:
            st.sidebar.error(f"Error loading headers: {e}")
            session_headers = {}


if st.sidebar.button("Search for Hotel Deals"):
    # Process cURL command if that method was selected and input is provided
    if auth_method == "cURL Command" and curl_command_input:
        try:
            # Ensure parse_curl_command is available
            if "parse_curl_command" in globals() and callable(parse_curl_command):
                parsed_url, parsed_headers = parse_curl_command(curl_command_input)
                if parsed_headers:
                    session_headers = parsed_headers  # Use all headers from cURL
                    st.sidebar.success(
                        "cURL command parsed successfully. Using extracted headers."
                    )
                    if "Cookie" not in parsed_headers:
                        st.sidebar.warning(
                            "Cookie not found in cURL command. Requests might fail."
                        )
                else:
                    st.sidebar.error(
                        "Could not parse headers from cURL command. Please check the format."
                    )
            else:
                st.sidebar.error(
                    "cURL parsing function is not available. Cannot process cURL input."
                )
        except Exception as e:  # General exception for parsing logic
            st.sidebar.error(f"Error parsing cURL command: {e}")
            session_headers = {}  # Clear headers on error

    # Validation for city input
    if (
        not city_query_for_backend
    ):  # Check if any city was resolved to be sent to backend
        if search_type == "Specific Location(s)":
            st.error("Please enter a city for 'Specific Location(s)' search.")
        elif search_type == "Broad Points Optimization":
            st.error(
                "Please select a region or enter custom cities for 'Broad Points Optimization'."
            )
        st.stop()  # Stop execution if no city input is valid
    elif start_date_input > end_date_input:
        st.error("Start date cannot be after end date.")
    else:
        progress_bar_placeholder = st.empty()
        status_text_placeholder = st.empty()

        # Updated progress callback for multi-city and iterative search feedback
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

            if status_message:  # For specific messages like "Place ID not found", "Target Met", "Extending Search"
                msg_parts.append(f"- {status_message}")
            elif iterative_search_checkbox and is_final_city_in_pass:
                msg_parts.append(
                    "Pass complete."
                )  # Backend will log/handle if extending search
            elif (
                iterative_search_checkbox
            ):  # Implies not final_city_in_pass, or still processing current pass
                msg_parts.append("Searching...")
            # If not iterative_search_checkbox, the message parts for city/date processing are usually enough.

            status_text_placeholder.text(" | ".join(msg_parts))

        # Define styling function here to ensure it's in scope
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
            return df  # Return unstyled df if column not suitable or empty

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
            # Ensure find_best_hotel_deals is available
            if "find_best_hotel_deals" not in globals() or not callable(
                find_best_hotel_deals
            ):
                st.error(
                    "Core search function 'find_best_hotel_deals' is not available. App cannot proceed."
                )
                st.stop()

            # TODO: When backend supports List[str] for cities, pass cities_to_process_log directly.
            # For now, we pass city_query_for_backend which is cities_to_process_log[0] or the single specific city.
            all_hotel_options, final_itinerary, total_cost, total_points_earned = (
                find_best_hotel_deals(
                    city_queries=cities_to_process_log,  # Pass the full list of cities
                    start_date=start_date_input,
                    end_date=end_date_input,
                    session_headers=session_headers,
                    target_loyalty_points=target_loyalty_points,
                    progress_callback=streamlit_progress_callback,
                    aa_card_bonus=aa_card_bonus_checkbox,
                    optimization_strategy=optimization_strategy_value,
                    iterative_search_for_lp_target=iterative_search_checkbox,
                    # max_search_days_iterative=max_search_days_input, # If we add this input
                    current_lp_balance=current_lp_balance_input,  # Pass current LP balance
                )
            )

            progress_bar_placeholder.empty()
            status_text_placeholder.empty()

            st.subheader("All Hotel Options Found")
            if all_hotel_options:
                df_all_options = pd.DataFrame(all_hotel_options)
                # Updated columns to show more point details available at this stage
                display_cols_all = [
                    "name",
                    "location",
                    "check_in_date",
                    "total_price",
                    "api_points_earned",
                    "card_bonus_points",  # Added
                    "points_earned",  # This is api_points + card_bonus
                    "points_per_dollar",  # Based on api_points + card_bonus
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
                        "Base+Card PPD",
                        format="%.2f",
                        help="PPD based on API Points + Card Bonus.",
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
                        # Using 'points_per_dollar' which is Base+Card PPD for this table
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
            else:
                st.write("No hotel options found for the given criteria.")

            st.subheader("Optimal Loyalty Points Strategy")
            if final_itinerary:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Target LP", f"{target_loyalty_points:,}")
                col2.metric("Achieved LP", f"{total_points_earned:,}")
                col3.metric("Total Cost", f"${total_cost:,.2f}")
                overall_ppd = (
                    (total_points_earned / total_cost) if total_cost > 0 else 0
                )
                col4.metric("Overall PPD", f"{overall_ppd:.2f}")

                st.markdown("---")
                st.write("Itinerary Details:")
                df_itinerary = pd.DataFrame(final_itinerary)
                # Updated columns to show detailed point breakdown
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
                ]
                df_itinerary_display = df_itinerary[
                    [
                        col
                        for col in display_cols_itinerary
                        if col in df_itinerary.columns
                    ]
                ].copy()

                # Updated column configurations for the new detailed view
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
                        "Stay PPD",
                        format="%.2f",
                        help="Total Loyalty Points / Price for this stay.",
                    ),
                }
                active_column_config_itinerary = {
                    k: v
                    for k, v in column_config_itinerary.items()
                    if k in df_itinerary_display.columns
                }

                # Style based on the final PPD for the itinerary
                styled_df_itinerary = style_ppd_column(
                    df_itinerary_display,
                    column_name="points_per_dollar_final_for_itinerary",
                )
                st.dataframe(
                    styled_df_itinerary, column_config=active_column_config_itinerary
                )
            else:
                st.write(
                    f"Could not form an itinerary to meet the target of {target_loyalty_points} points from the found options."
                )
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
st.sidebar.markdown("Feel the VIBES")
