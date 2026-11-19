"""Theme: injected CSS + one Plotly template used by every chart."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from services.config import ROOT

TEAL, AMBER, RED, BLUE, GREY, TEXT, PANEL, BORDER = ("#14B8A6", "#F59E0B", "#EF4444", "#60A5FA", "#94A3B8", "#E6EAF2",
                                                     "#111A2E", "#1E293B")
HEALTH_COLORS = {"Healthy": TEAL, "Monitor": AMBER, "At Risk": RED}
SERIES = [TEAL, BLUE, AMBER, "#A78BFA", "#F472B6", "#34D399", RED]
VERTICAL_COLORS = {"Flux Bunkers": TEAL, "Flux Analytics": BLUE, "The Officials": "#A78BFA",
                   "Trading Relationships": AMBER}


def register_plotly() -> None:
    if "onyx" in pio.templates:
        return
    pio.templates["onyx"] = go.layout.Template(layout=dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", color=TEXT, size=12),
        colorway=SERIES,
        xaxis=dict(gridcolor=BORDER, linecolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, linecolor=BORDER, zerolinecolor=BORDER),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
        margin=dict(l=10, r=10, t=36, b=10),
        hoverlabel=dict(bgcolor=PANEL, bordercolor=BORDER, font=dict(color=TEXT)),
        title=dict(font=dict(size=13, color=TEXT), x=0, xanchor="left"),
    ))
    pio.templates.default = "onyx"


def inject_css() -> None:
    css = (ROOT / "assets" / "style.css").read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    register_plotly()
