import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

# Attempt to import from the local package
try:
    from aa_hotel_optimizer.main import (
        find_best_hotel_deals,
        parse_curl_command,  # Added import
    )
except ImportError:
    st.error(
        "Failed to import from 'aa_hotel_optimizer'. Ensure it's installed or accessible in your PYTHONPATH. "
        "If running from the project root, this should work if the package structure is correct."
    )
    # Attempt individual imports as a fallback or for more specific error messages
    try:
        from aa_hotel_optimizer.main import find_best_hotel_deals
    except ImportError:
        st.error("Could not import 'find_best_hotel_deals'. App may not function.")
        st.stop() # Stop if core function is missing
    try:
        from aa_hotel_optimizer.main import parse_curl_command
    except ImportError:
        st.warning("Could not import 'parse_curl_command'. cURL input will not work.")
        # Don't stop here, as other auth methods might still work


# Default target points, can be overridden by user input
DEFAULT_TARGET_POINTS = 250000

st.set_page_config(layout="wide")

st.title("AAdvantage Hotel Optimizer")

st.sidebar.header("Search Parameters")

# Inputs
city_query = st.sidebar.text_input("City", "Phoenix")

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
    help="Select if you are using an AAdvantage credit card for an extra 10 miles per dollar spent."
)

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
    index=0, # Default to PPD
    help=(
        "Maximize PPD: Good for general high-value stays.\n"
        "Minimize Cost (Greedy): Finds the cheapest stays to hit LP target quickly.\n"
        "Minimize Cost (DP): More thorough, aims for true minimum cost to hit LP target (can be slower)."
    )
)
optimization_strategy_value = optimization_strategy_options[selected_strategy_display]


st.sidebar.markdown("---")
st.sidebar.subheader("Authentication Details")

auth_method = st.sidebar.radio(
    "Authentication Method",
    ("Manual Cookie/XSRF", "cURL Command", "JSON File"),
    index=0,
    help="Choose how to provide authentication details. cURL is often easiest if you can copy it from your browser's developer tools."
)

session_headers: Dict[str, str] = {}
curl_command_input = ""

if auth_method == "Manual Cookie/XSRF":
    cookie_input = st.sidebar.text_area("Cookie String", height=100, help="Paste the full cookie string here.")
    xsrf_token_input = st.sidebar.text_input("XSRF Token", help="Paste the XSRF token here.")
    if cookie_input:
        session_headers["Cookie"] = cookie_input.strip()
    if xsrf_token_input:
        session_headers["X-XSRF-TOKEN"] = xsrf_token_input.strip()
elif auth_method == "cURL Command":
    curl_command_input = st.sidebar.text_area(
        "Paste cURL Command",
        height=200,
        help="Paste the full cURL command copied from your browser's network tab. This will attempt to parse headers and cookies."
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
            parsed_url, parsed_headers = parse_curl_command(curl_command_input)
            if parsed_headers:
                session_headers = parsed_headers # Use all headers from cURL
                st.sidebar.success("cURL command parsed successfully. Using extracted headers.")
                # Optionally, display some of the parsed headers for confirmation (e.g., User-Agent)
                # if "User-Agent" in parsed_headers:
                #     st.sidebar.caption(f"Using User-Agent: {parsed_headers['User-Agent'][:30]}...")
                if "Cookie" not in parsed_headers:
                    st.sidebar.warning("Cookie not found in cURL command. Requests might fail.")
            else:
                st.sidebar.error("Could not parse headers from cURL command. Please check the format.")
        except NameError: # If parse_curl_command failed to import
            st.sidebar.error("cURL parsing function is not available. Cannot process cURL input.")
        except Exception as e:
            st.sidebar.error(f"Error parsing cURL command: {e}")
            # Potentially clear session_headers or revert to a safe state
            session_headers = {}


    if not city_query:
        st.error("Please enter a city.")
    elif start_date_input > end_date_input:
        st.error("Start date cannot be after end date.")
    else:
        progress_bar_placeholder = st.empty()
        status_text_placeholder = st.empty()

        def streamlit_progress_callback(completed_count: int, total_count: int):
            progress = 0.0
            if total_count > 0: # Avoid division by zero
                progress = completed_count / total_count
            progress_bar_placeholder.progress(progress)
            status_text_placeholder.text(f"Processed {completed_count}/{total_count} dates...")

        # Define styling function here to ensure it's in scope
        def style_ppd_column(df):
            if 'points_per_dollar' in df.columns and pd.api.types.is_numeric_dtype(df['points_per_dollar']) and not df['points_per_dollar'].empty:
                if df['points_per_dollar'].count() > 0: 
                     return df.style.background_gradient(subset=['points_per_dollar'], cmap='Greens', low=0.1, high=1.0)
            return df # Return unstyled df if column not suitable or empty

        status_text_placeholder.text(f"Initiating search for {city_query}...")
        
        try:
            progress_bar_placeholder.progress(0) 
            all_hotel_options, final_itinerary, total_cost, total_points_earned = find_best_hotel_deals(
                city_query=city_query,
                start_date=start_date_input,
                end_date=end_date_input,
                session_headers=session_headers,
                target_loyalty_points=target_loyalty_points,
                progress_callback=streamlit_progress_callback,
                aa_card_bonus=aa_card_bonus_checkbox,
                optimization_strategy=optimization_strategy_value, # Pass selected strategy
            )
            
            progress_bar_placeholder.empty()
            status_text_placeholder.empty()

            st.subheader("All Hotel Options Found")
            if all_hotel_options:
                df_all_options = pd.DataFrame(all_hotel_options)
                display_cols_all = [
                    "name", "location", "check_in_date", "total_price",
                    "points_earned", "points_per_dollar", "refundability",
                    "star_rating", "user_rating",
                ]
                df_all_options_display = df_all_options[[col for col in display_cols_all if col in df_all_options.columns]].copy()

                if "refundability" in df_all_options_display.columns:
                    df_all_options_display.loc[:, "refundability"] = df_all_options_display["refundability"].apply(
                        lambda x: "✅ Refundable" if x == "REFUNDABLE" else ("❌ Non-Refundable" if x == "NON_REFUNDABLE" else "❓ Unknown")
                    )
                if "star_rating" in df_all_options_display.columns:
                    df_all_options_display.loc[:, "star_rating_display"] = df_all_options_display["star_rating"].apply(lambda x: f"{x:.1f} ⭐" if pd.notna(x) and x > 0 else "N/A")
                    display_cols_all = [col if col != "star_rating" else "star_rating_display" for col in display_cols_all]
                
                final_display_cols_all = [col for col in display_cols_all if col in df_all_options_display.columns]

                if "points_per_dollar" in df_all_options_display.columns:
                    df_all_options_display = df_all_options_display.sort_values(by="points_per_dollar", ascending=False)

                column_config_all = {
                    "name": st.column_config.TextColumn("Hotel Name", width="large"),
                    "location": "Location", "check_in_date": "Check-in",
                    "total_price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "points_earned": st.column_config.NumberColumn("Points", format="%d"),
                    "points_per_dollar": st.column_config.NumberColumn("Points/$", format="%.2f"),
                    "refundability": "Refundable",
                    "star_rating_display": st.column_config.TextColumn("Stars"),
                    "user_rating": st.column_config.NumberColumn("Rating", format="%.1f"),
                }
                active_column_config_all = {k: v for k, v in column_config_all.items() if k in final_display_cols_all}
                
                styled_df_all_options = style_ppd_column(df_all_options_display[final_display_cols_all])
                st.dataframe(styled_df_all_options, column_config=active_column_config_all)

                st.markdown("---")
                st.subheader("Visualizations for All Hotel Options")
                col1, col2 = st.columns(2)
                with col1:
                    if "points_per_dollar" in df_all_options_display.columns and not df_all_options_display["points_per_dollar"].empty:
                        st.write("Distribution of Points per Dollar")
                        st.bar_chart(df_all_options_display["points_per_dollar"].value_counts().sort_index())
                    else:
                        st.write("Points per Dollar data not available for histogram.")
                with col2:
                    if "total_price" in df_all_options_display.columns and "points_earned" in df_all_options_display.columns and not df_all_options_display[["total_price", "points_earned"]].empty:
                        st.write("Total Price vs. Points Earned")
                        scatter_df = df_all_options_display[["total_price", "points_earned"]].copy()
                        scatter_df.columns = ['Total Price ($)', 'Points Earned']
                        st.scatter_chart(scatter_df, x='Total Price ($)', y='Points Earned')
                    else:
                        st.write("Price/Points data not available for scatter plot.")
                st.markdown("---")
            else:
                st.write("No hotel options found for the given criteria.")

            st.subheader("Optimal Loyalty Points Strategy")
            if final_itinerary:
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Target LP", f"{target_loyalty_points:,}")
                col2.metric("Achieved LP", f"{total_points_earned:,}")
                col3.metric("Total Cost", f"${total_cost:,.2f}")
                overall_ppd = (total_points_earned / total_cost) if total_cost > 0 else 0
                col4.metric("Overall PPD", f"{overall_ppd:.2f}")
                
                st.markdown("---")
                st.write("Itinerary Details:")
                df_itinerary = pd.DataFrame(final_itinerary)
                display_cols_itinerary = [
                    "name", "location", "check_in_date", "total_price",
                    "points_earned", "points_per_dollar",
                ]
                df_itinerary_display = df_itinerary[[col for col in display_cols_itinerary if col in df_itinerary.columns]].copy()
                column_config_itinerary = {
                    "name": st.column_config.TextColumn("Hotel Name", width="large"),
                    "location": "Location", "check_in_date": "Check-in",
                    "total_price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    "points_earned": st.column_config.NumberColumn("Points", format="%d"),
                    "points_per_dollar": st.column_config.NumberColumn("Points/$", format="%.2f"),
                }
                active_column_config_itinerary = {k:v for k,v in column_config_itinerary.items() if k in df_itinerary_display.columns}
                
                styled_df_itinerary = style_ppd_column(df_itinerary_display)
                st.dataframe(styled_df_itinerary, column_config=active_column_config_itinerary)
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
    st.info("Enter search parameters in the sidebar and click 'Search for Hotel Deals'.")

st.sidebar.markdown("---")
st.sidebar.markdown("Feel the VIBES")
