"""Catch import, widget and rendering regressions before the linked Cloud deploy."""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from aa_hotel_optimizer import main

app = AppTest.from_file(
    Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=30
).run()
if app.exception:
    raise RuntimeError([exception.message for exception in app.exception])
assert "lp_preview" in app.session_state
print("PASS Streamlit mounts the new planner by default")

app = AppTest.from_file(
    Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=30
)
app.query_params["view"] = "classic"
app.run()
if app.exception:
    raise RuntimeError([exception.message for exception in app.exception])
if not app.title or "Hotel" not in app.title[0].value:
    raise RuntimeError("The Streamlit planner did not render.")
print("PASS Original planner remains available on the deployment interpreter")
stay = main.analyze_hotel_data(
    {
        "results": [
            {
                "hotel": {
                    "id": "fixture",
                    "name": "Fictional test hotel",
                    "stars": 4,
                    "rating": 8.5,
                },
                "grandTotalPublishedPriceInclusiveWithFees": {"amount": 100},
                "rewards": 1000,
                "refundability": "REFUNDABLE",
            }
        ]
    },
    "Phoenix",
    (date.today() + timedelta(days=28)).strftime("%m/%d/%Y"),
)[0]
with patch.object(main, "find_best_hotel_deals", return_value=([stay], [stay], 100, 1000)):
    app.sidebar.button[0].click().run()
    assert not app.exception, [e.message for e in app.exception]
    assert len(app.dataframe) == 2
    app.sidebar.number_input(key="miles_value_cents_input").set_value(2.0).run()
    assert not app.exception and len(app.dataframe) == 2
print("PASS Streamlit displays a mocked search and preserves it across a widget change")
