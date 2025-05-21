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

uploaded_headers_file = st.sidebar.file_uploader(
    "Optional: Upload Session Headers JSON file", type=["json"]
)

session_headers: Dict[str, str] = {}
if uploaded_headers_file is not None:
    try:
        session_headers = json.load(uploaded_headers_file)
        st.sidebar.success("Headers file loaded successfully!")
    except json.JSONDecodeError:
        st.sidebar.error("Error decoding JSON from headers file.")
    except Exception as e:
        st.sidebar.error(f"Error loading headers: {e}")

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
                    df_all_options_display = df_all_options[[col for col in display_cols_all if col in df_all_options.columns]]
                    if "points_per_dollar" in df_all_options_display.columns:
                        df_all_options_display = df_all_options_display.sort_values(by="points_per_dollar", ascending=False)
                    st.dataframe(df_all_options_display)
                else:
                    st.write("No hotel options found for the given criteria.")

                st.subheader("Optimal Loyalty Points Strategy")
                if final_itinerary:
                    st.write(f"Target Loyalty Points: {target_loyalty_points}")
                    st.write(f"Achieved Loyalty Points: {total_points_earned}")
                    st.write(f"Total Cost: ${total_cost:.2f}")
                    if total_cost > 0:
                        st.write(
                            f"Overall Points per Dollar: {total_points_earned / total_cost:.2f}"
                        )
                    else:
                        st.write("Overall Points per Dollar: N/A (no cost)")

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
                    df_itinerary_display = df_itinerary[[col for col in display_cols_itinerary if col in df_itinerary.columns]]
                    st.dataframe(df_itinerary_display)

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
st.sidebar.markdown("Developed by Cline.")
