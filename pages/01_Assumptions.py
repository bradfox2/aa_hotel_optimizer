import streamlit as st

st.set_page_config(layout="wide", page_title="Assumptions - LP Optimizer")
st.title("How estimates work")
st.markdown("""
The original Streamlit workflow searches one-night stays. The new service compares
both continuous stays and combinations of shorter reservations for a planned trip.

- **Hotel LP:** The provider's quoted rewards are treated as estimated base hotel
  LP. Promotional miles may not qualify. Check the final eligible LP at checkout.
- **Card rewards:** Eligible card spend can add 1 LP per dollar. Redeemable card
  miles use the rate you choose; they are tracked separately from LP.
- **Partner bonuses:** No bonus is inferred from crossing a projected balance.
  The service accepts explicit active promotion dates, percentage and remaining
  allowance. The legacy UI defaults to no active partner bonus.
- **2026 reward rules:** Registration is required for the 25% partner LP bonus
  after reaching 60,000 LP, with up to 25,000 additional LP. Prior active 20%/30%
  promotions may have different remaining eligibility. Use the dates and terms
  shown in your AA account. LP bonuses do not add redeemable miles.
- **Selection:** The minimum-cost strategy compares alternatives on the same date
  and includes the configured bonus cap. It finds the cheapest qualifying plan
  among the available quotes for non-overlapping one-night stays. Value,
  cheapest-first and overlapping fastest-finish strategies are heuristics.
- **Limits:** Searches have explicit bounds. Invalid, missing-price and non-USD
  quotes are excluded. Results are paginated, with a cap that produces an error
  rather than pretending an incomplete search is complete.
- **Booking:** Prices include the provider's quoted taxes and fees. Additional
  charges may be disclosed at checkout. Separate bookings may require another
  check-in or a room change. No-show reservations do not guarantee rewards.

Prices, availability and eligibility can change. This app does not reserve rooms
or promise that rewards will post.

[Official Loyalty Point Rewards terms](https://www.aa.com/web/i18n/aadvantage-program/aadvantage-status/loyalty-point-rewards.html)
""")
