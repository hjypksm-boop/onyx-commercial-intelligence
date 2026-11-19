"""Chart helpers (Plotly, 'onyx' template)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components.theme import HEALTH_COLORS

CONFIG = {"displayModeBar": False, "responsive": True}


def show(fig: go.Figure, key: str, height: int = 300) -> None:
    fig.update_layout(height=height)
    st.plotly_chart(fig, width="stretch", config=CONFIG, key=key)


def health_bar(counts: dict[str, int], title: str = "Customer health distribution") -> go.Figure:
    cats = ["Healthy", "Monitor", "At Risk"]
    fig = go.Figure(go.Bar(x=cats, y=[counts.get(c, 0) for c in cats], marker_color=[HEALTH_COLORS[c] for c in cats],
                           text=[counts.get(c, 0) for c in cats], textposition="outside",
                           hovertemplate="%{x}: %{y} account(s)<extra></extra>"))
    fig.update_layout(title=title, yaxis_title="Accounts", showlegend=False, yaxis=dict(dtick=1))
    return fig
