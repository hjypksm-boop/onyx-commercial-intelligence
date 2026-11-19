"""Consistent display formatting: £48,000 · 18 Nov 2026 · 70.4%."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def _isnull(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def gbp(pence, dp: int = 0) -> str:
    if _isnull(pence):
        return "—"
    v = float(pence) / 100
    sign = "-" if v < 0 else ""
    return f"{sign}£{abs(v):,.{dp}f}"


def gbp_pounds(pounds) -> str:
    return "—" if _isnull(pounds) else gbp(float(pounds) * 100)


def gbp_compact(pence) -> str:
    """Compact form for chart labels only: £1.2k, £3.4m."""
    if _isnull(pence):
        return "—"
    v = float(pence) / 100
    if abs(v) >= 1_000_000:
        return f"£{v / 1_000_000:.1f}m"
    if abs(v) >= 1_000:
        return f"£{v / 1_000:.1f}k"
    return f"£{v:,.0f}"


def usd(v) -> str:
    if _isnull(v):
        return "—"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:,.1f}m"
    return f"${v:,.0f}"


def pct(v, dp: int = 1) -> str:
    return "—" if _isnull(v) else f"{float(v):.{dp}f}%"


def to_date(v) -> date | None:
    if _isnull(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def fdate(v) -> str:
    d = to_date(v)
    return "—" if d is None else d.strftime("%d %b %Y").lstrip("0")


def num(v, dp: int = 0) -> str:
    return "—" if _isnull(v) else f"{float(v):,.{dp}f}"


def month_label(month_key: str) -> str:
    return datetime.strptime(month_key, "%Y-%m").strftime("%b %Y")


def month_name(month_key: str) -> str:
    return datetime.strptime(month_key, "%Y-%m").strftime("%B")


def txt(v) -> str:
    """Nullable text → '' (pandas returns NaN for NULL strings)."""
    return "" if _isnull(v) else str(v)
