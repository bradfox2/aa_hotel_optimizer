import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

# Attempt to import from the local package
try:
    from aa_hotel_optimizer.main import (
        discover_phoenix_metro_place_ids,  # May not be directly used by UI but good to have
        # TARGET_LOYALTY_POINTS as DEFAULT_TARGET_POINTS # If we want to use the default from main
        find_best_hotel_deals,
    )
except ImportError:
    st.error(
        "Failed to import 'aa_hotel_optimizer'. Ensure it's installed or accessible in your PYTHONPATH. "
        "If running from the project root, this should work if the package structure is correct."
    )
    # As a fallback for development, try a relative import if the script is in the root
    # and aa_hotel_optimizer is a subdirectory. This is not standard for packages.
    try:
        from aa_hotel_optimizer.main import find_best_hotel_deals
        # from aa_hotel_optimizer.main import TARGET_LOYALTY_POINTS as DEFAULT_TARGET_POINTS
    except ImportError:
        st.stop()


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

# Convert date objects to string format MM/DD/YYYY for the backend function if needed,
# but find_best_hotel_deals expects date objects.
# start_date_str = start_date_input.strftime("%m/%d/%Y")
# end_date_str = end_date_input.strftime("%m/%d/%Y")


target_loyalty_points = st.sidebar.number_input(
    "Target Loyalty Points", min_value=0, value=DEFAULT_TARGET_POINTS, step=1000
)

st.sidebar.markdown("---")
st.sidebar.subheader("Authentication Details")
cookie_input = st.sidebar.text_area("Cookie String", height=100, help="Paste the full cookie string here.")
xsrf_token_input = st.sidebar.text_input("XSRF Token", help="Paste the XSRF token here.")

uploaded_headers_file = st.sidebar.file_uploader(
    "Optional: Upload Session Headers JSON file (Cookie/XSRF token from above will override if provided)", type=["json"]
)

session_headers: Dict[str, str] = {}
if uploaded_headers_file is not None:
    try:
        session_headers = json.load(uploaded_headers_file)
        st.sidebar.success("Headers file loaded successfully!")
    except json.JSONDecodeError:
        st.sidebar.error("Error decoding JSON from headers file.")
        session_headers = {} # Reset on error
    except Exception as e:
        st.sidebar.error(f"Error loading headers: {e}")
        session_headers = {} # Reset on error

# Override or set Cookie and XSRF token from direct input if provided
if cookie_input:
    session_headers["Cookie"] = cookie_input.strip()
if xsrf_token_input:
    session_headers["X-XSRF-TOKEN"] = xsrf_token_input.strip()


if st.sidebar.button("Search for Hotel Deals"):
    if not city_query:
        st.error("Please enter a city.")
    elif start_date_input > end_date_input:
        st.error("Start date cannot be after end date.")
    else:
        with st.spinner(
            f"Searching for hotel deals in {city_query} from {start_date_input.strftime('%m/%d/%Y')} to {end_date_input.strftime('%m/%d/%Y')}..."
        ):
            try:
                (
                    all_hotel_options,
                    final_itinerary,
                    total_cost,
                    total_points_earned,
                ) = find_best_hotel_deals(
                    city_query=city_query,
                    start_date=start_date_input,
                    end_date=end_date_input,
                    session_headers=session_headers,
                    target_loyalty_points=target_loyalty_points,
                )

                st.subheader("All Hotel Options Found")
                if all_hotel_options:
                    df_all_options = pd.DataFrame(all_hotel_options)
                    # Select and reorder columns for display
                    display_cols_all = [
                        "name",
                        "location",
                        "check_in_date",
                        "total_price",
                        "points_earned",
                        "points_per_dollar",
                        "refundability",
                        "star_rating",
                        "user_rating",
                    ]
                    # Filter out columns that might not exist if the list is empty or structure changes
                    df_all_options_display = df_all_options[[col for col in display_cols_all if col in df_all_options.columns]].copy() # Use .copy() to avoid SettingWithCopyWarning

                    # Pre-process for better display
                    if "refundability" in df_all_options_display.columns:
                        df_all_options_display.loc[:, "refundability"] = df_all_options_display["refundability"].apply(
                            lambda x: "✅ Refundable" if x == "REFUNDABLE" else ("❌ Non-Refundable" if x == "NON_REFUNDABLE" else "❓ Unknown")
                        )
                    if "star_rating" in df_all_options_display.columns:
                         df_all_options_display.loc[:, "star_rating_display"] = df_all_options_display["star_rating"].apply(lambda x: f"{x:.1f} ⭐" if pd.notna(x) and x > 0 else "N/A")
                         display_cols_all = [col if col != "star_rating" else "star_rating_display" for col in display_cols_all]


                    if "points_per_dollar" in df_all_options_display.columns:
                        df_all_options_display = df_all_options_display.sort_values(by="points_per_dollar", ascending=False)

                    # Define column configurations
                    column_config_all = {
                        "name": st.column_config.TextColumn("Hotel Name", width="large"),
                        "location": "Location",
                        "check_in_date": "Check-in",
                        "total_price": st.column_config.NumberColumn("Price", format="$%.2f"),
                        "points_earned": st.column_config.NumberColumn("Points", format="%d"),
                        "points_per_dollar": st.column_config.NumberColumn("Points/$", format="%.2f"),
                        "refundability": "Refundable",
                        "star_rating_display": st.column_config.TextColumn("Stars"),
                        "user_rating": st.column_config.NumberColumn("Rating", format="%.1f"),
                    }
                    # Ensure we only try to configure columns that exist
                    active_column_config_all = {k: v for k, v in column_config_all.items() if k in df_all_options_display.columns or (k == "star_rating_display" and "star_rating" in df_all_options.columns)}


                    st.dataframe(df_all_options_display[[col for col in display_cols_all if col in df_all_options_display.columns or col == "star_rating_display"]], column_config=active_column_config_all)

                    # Add visualizations
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
                        if "total_price" in df_all_options_display.columns and \
                           "points_earned" in df_all_options_display.columns and \
                           not df_all_options_display[["total_price", "points_earned"]].empty:
                            st.write("Total Price vs. Points Earned")
                            # Create a new DataFrame for the scatter chart to avoid modifying the original
                            scatter_df = df_all_options_display[["total_price", "points_earned"]].copy()
                            scatter_df.columns = ['Total Price ($)', 'Points Earned'] # Rename for better axis labels
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
                    
                    st.markdown("---") # Visual separator
                    st.write("Itinerary Details:")
                    df_itinerary = pd.DataFrame(final_itinerary)
                    display_cols_itinerary = [
                        "name",
                        "location",
                        "check_in_date",
                        "total_price",
                        "points_earned",
                        "points_per_dollar",
                    ]
                    df_itinerary_display = df_itinerary[[col for col in display_cols_itinerary if col in df_itinerary.columns]].copy()

                    column_config_itinerary = {
                        "name": st.column_config.TextColumn("Hotel Name", width="large"),
                        "location": "Location",
                        "check_in_date": "Check-in",
                        "total_price": st.column_config.NumberColumn("Price", format="$%.2f"),
                        "points_earned": st.column_config.NumberColumn("Points", format="%d"),
                        "points_per_dollar": st.column_config.NumberColumn("Points/$", format="%.2f"),
                    }
                    active_column_config_itinerary = {k:v for k,v in column_config_itinerary.items() if k in df_itinerary_display.columns}

                    st.dataframe(df_itinerary_display, column_config=active_column_config_itinerary)

                else:
                    st.write(
                        f"Could not form an itinerary to meet the target of {target_loyalty_points} points from the found options."
                    )

            except Exception as e:
                st.error(f"An error occurred during the search: {e}")
                st.exception(e) # Provides a full traceback for debugging

else:
    st.info("Enter search parameters in the sidebar and click 'Search for Hotel Deals'.")

st.sidebar.markdown("---")
st.sidebar.markdown("Feel the VIBES")
