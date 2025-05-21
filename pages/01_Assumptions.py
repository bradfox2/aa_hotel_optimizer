import streamlit as st

st.set_page_config(layout="wide", page_title="Assumptions - AAdvantage Hotel Optimizer")

st.title("Key Assumptions and Simplifications")

st.markdown("""
This AAdvantage Hotel Optimizer tool operates under several key assumptions and simplifications.
Understanding these will help you interpret the results more effectively.
""")

st.subheader("Loyalty Point Bonus Calculations")
st.markdown("""
*   **Status Bonus (20% at 60k LP, 30% at 100k LP):**
    *   Applied to the base Loyalty Points earned directly from the AAdvantageHotels.com booking (referred to as `api_points_earned` internally).
    *   This bonus is **not** applied to points earned from credit card bonuses (e.g., the 10 miles/$ AA card bonus).
    *   If a Loyalty Point threshold (60,000 LP or 100,000 LP) is crossed *during the generation of a proposed itinerary*, the relevant bonus percentage will apply to all subsequent hotel stays *within that same generated itinerary*.
    *   The "six-month duration" for these status bonuses is simplified: the tool assumes the bonus eligibility, once achieved, persists for all stays in the current optimized plan. It does not track a strict six-month window from the exact date a threshold is crossed.
*   **AA Credit Card Bonus (10 miles/$):**
    *   Assumed to apply to the total pre-tax price of the hotel booking if the "AA Credit Card Bonus" option is selected in the sidebar.
    *   Calculated as `total_price * 10`.
""")

st.subheader("API and Data")
st.markdown("""
*   **API Reliance:** The tool uses an unofficial AAdvantageHotels.com API. Data accuracy, availability, and API behavior can change without notice.
*   **Data Completeness:** Information such as "digital check-in" availability is not explicitly provided by the current API endpoints used, so filters based on such features are not yet implemented.
*   **Place ID Discovery:** The mechanism for finding `placeId` values for cities relies on the API's search suggestions. This may not cover all possible locations or could sometimes yield IDs that don't return hotel results.
""")

st.subheader("Search and Optimization Logic")
st.markdown("""
*   **Single Night Stays:** The optimization process considers each day as a potential one-night stay. It does not explicitly search for or prioritize multi-night stay discounts or specific multi-night point offers, unless these are inherently reflected in the per-night data fetched for consecutive days.
*   **Greedy Algorithms:**
    *   The "Maximize Points per Dollar (Greedy PPD)" strategy sorts all available hotel options (after applying card and status bonuses based on your current LP for an initial PPD calculation) and picks the best PPD stays one by one, avoiding date conflicts, until the target LP is met.
    *   The "Minimize Cost for Target LP (Greedy Cheapest Stays)" strategy sorts by the lowest price and picks stays similarly.
    *   These greedy approaches are heuristics and provide good, fast solutions but are not guaranteed to find the absolute mathematical optimum in all scenarios (especially when dynamic status bonuses can change a stay's value mid-itinerary).
*   **Dynamic Programming (DP) Strategy:**
    *   The "Minimize Cost for Target LP (Dynamic Programming)" strategy aims for a more globally optimal solution to minimize cost for the target LP.
    *   For computational feasibility with dynamically changing point values (due to status bonuses), this strategy uses the initial points (API points + AA card bonus) for its core DP table construction. Status bonuses are then applied to the stays in the selected optimal path to calculate the final points and cost. This is a practical simplification.
*   **Iterative Search:** When "Search future dates until LP target is met" is enabled:
    *   The search extends by approximately one month per iteration.
    *   There's a maximum number of iterations (default 12) and a maximum search horizon (default ~6 months from the start date) to prevent excessively long searches.
""")

st.subheader("General")
st.markdown("""
*   **No Real-Time Availability:** The tool fetches current offers but does not guarantee room availability or prices at the actual time of booking on the AAdvantageHotels.com site.
*   **Currency:** All financial calculations assume USD.
*   **Taxes and Fees:** The "total_price" used for calculations is intended to be the `grandTotalPublishedPriceInclusiveWithFees` from the API, which should include taxes and fees.
""")

st.markdown("---")
st.markdown("Always double-check details on the official AAdvantageHotels.com website before making any bookings.")
