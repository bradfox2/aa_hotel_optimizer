"""Community Cloud entrypoint: the shared planner is the default experience."""

import runpy
from pathlib import Path

import streamlit as st

if st.query_params.get("view") == "classic":
    runpy.run_path(str(Path(__file__).with_name("streamlit_classic.py")), run_name="__main__")
else:
    from aa_hotel_optimizer.streamlit_ui import render

    render()
