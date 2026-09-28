"""Mount the shared web planner using Streamlit's supported component API."""

import base64
import re
from pathlib import Path

import streamlit as st

from .streamlit_runtime import PreviewSession

STATIC = Path(__file__).parent / "service" / "static"


def preview_session():
    previous = st.session_state.get("lp_preview")
    if getattr(previous, "VERSION", None) != PreviewSession.VERSION or not isinstance(
        previous, PreviewSession
    ):
        if previous is not None:
            previous.disconnect()
        st.session_state.lp_preview = PreviewSession()
        st.session_state.lp_response = None
    return st.session_state.lp_preview


@st.cache_resource
def component_assets(version):
    html = (STATIC / "index.html").read_text().split("<body>", 1)[1].split("</body>", 1)[0]
    html = '<div class="lp-app">' + html + "</div>"
    css = (STATIC / "app.css").read_text()
    # Shadow DOM prevents the planner and Streamlit themes from colliding.
    css = re.sub(r"(?<![\w-])(?:body|html)(?![\w-])|:root\b", ".lp-app", css)
    css += "\n.lp-app{min-height:100vh;padding-bottom:24px}dialog{font-family:var(--body)}"
    # Font-face declarations must live in the document, not the shadow root.
    fonts = (STATIC / "fonts" / "fonts.css").read_text()
    for font in (STATIC / "fonts").glob("*.ttf"):
        encoded = base64.b64encode(font.read_bytes()).decode()
        fonts = fonts.replace(f"/static/fonts/{font.name}", f"data:font/ttf;base64,{encoded}")
    js = (STATIC / "app.js").read_text() + "\n" + (STATIC / "streamlit-bridge.js").read_text()
    return html, css, js, fonts


def render():
    st.set_page_config(
        page_title="LP Optimizer · Same trip. More Loyalty Points.",
        page_icon="🏨",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    html, css, js, fonts = component_assets(
        tuple(
            (STATIC / name).stat().st_mtime_ns
            for name in ("index.html", "app.css", "app.js", "streamlit-bridge.js")
        )
    )
    st.html(
        "<style>"
        + fonts
        + """
        .stMainBlockContainer{padding:0;max-width:none}
        [data-testid="stHeader"]{display:none}
        [data-testid="stAppViewContainer"]{background:#f3f6fa}
        [data-testid="stVerticalBlock"]{gap:0}
        </style>"""
    )
    preview_session()
    # A protocol change must also remount the client, clearing pending requests
    # and callbacks that belonged to the old connection transport.
    widget_key = f"lp_planner_v{PreviewSession.VERSION}"

    def receive():
        event = st.session_state[widget_key].get("request")
        if event:
            st.session_state.lp_response = preview_session().handle(event)

    planner = st.components.v2.component("lp_planner", html=html, css=css, js=js)
    planner(
        key=widget_key,
        data={"response": st.session_state.get("lp_response")},
        on_request_change=receive,
        height="content",
        width="stretch",
    )
