"""Per-session context: which database (live / scenario sandbox), current user, filters, cached reads."""
from __future__ import annotations

import importlib
import logging
from datetime import date, timedelta

import streamlit as st

from services import db, demo_mode, health

log = logging.getLogger("onyx")

PAGES = {
    "overview": ("pages/01_executive_overview.py", "Executive Overview", ":material/dashboard:"),
    "portfolio": ("pages/02_customer_portfolio.py", "Customer Portfolio", ":material/table_view:"),
    "c360": ("pages/03_customer_360.py", "Customer 360", ":material/person_search:"),
    "analytics": ("pages/04_product_analytics.py", "Product Analytics", ":material/insights:"),
    "retention": ("pages/05_health_retention.py", "Customer Health & Retention", ":material/health_and_safety:"),
    "growth": ("pages/06_growth_opportunities.py", "Growth Opportunities", ":material/trending_up:"),
    "value_review": ("pages/07_value_review.py", "Value Review Builder", ":material/summarize:"),
    "close": ("pages/08_close_report.py", "Commercial Close Report", ":material/assignment_turned_in:"),
    "tasks": ("pages/09_tasks.py", "Tasks & Follow-ups", ":material/task_alt:"),
    "settings": ("pages/10_settings.py", "Settings", ":material/settings:"),
}


def mode() -> str:
    return st.session_state.get("demo_mode", "live")


def db_url() -> str:
    return demo_mode.db_url(mode())


def engine():
    return db.get_engine(db_url())


def user() -> dict:
    return st.session_state.get("user") or {}


def user_email() -> str:
    return user().get("email", "unknown")


def as_of() -> str:
    return call("db.as_of")


def as_of_date() -> date:
    return date.fromisoformat(as_of())


def filters() -> dict:
    f = st.session_state.get("filters")
    if not f:
        d = as_of_date()
        f = {"verticals": [], "owners": [], "health": [], "start": d - timedelta(days=364), "end": d}
        st.session_state["filters"] = f
    return f


def fsub() -> dict:
    """Account filters only (vertical / owner / health) — the part passed to SQL."""
    f = filters()
    return {"verticals": list(f["verticals"]), "owners": list(f["owners"]), "health": list(f["health"])}


def date_range() -> tuple[str, str]:
    f = filters()
    return f["start"].isoformat(), f["end"].isoformat()


def filter_params() -> dict:
    from services.kpis import filter_params as fp
    return fp(fsub())


FILTER_SQL = """(:all_verticals = 1 OR vertical IN :verticals)
  AND (:all_owners = 1 OR owner_name IN :owners)
  AND (:all_health = 1 OR health_category IN :health)"""


@st.cache_data(show_spinner=False, ttl=900)
def _cached(url: str, fn_path: str, args: tuple, kwargs: dict):
    mod, attr = fn_path.split(".")
    fn = getattr(importlib.import_module(f"services.{mod}"), attr)
    return fn(db.get_engine(url), *args, **kwargs)


def call(fn_path: str, *args, **kwargs):
    """Cached read: call services.<mod>.<fn>(engine, *args) keyed on the active database URL."""
    return _cached(db_url(), fn_path, args, kwargs)


@st.cache_data(show_spinner=False, ttl=900)
def _q(url: str, sql: str, params: dict | None):
    return db.query_df(db.get_engine(url), sql, params)


def q(sql: str, params: dict | None = None):
    return _q(db_url(), sql, params)


def after_write(message: str | None = None) -> None:
    """Recalculate health, clear read caches so every view refreshes, optional toast, rerun."""
    try:
        health.refresh_snapshots(engine())
    except Exception:  # pragma: no cover
        log.exception("health refresh failed")
    st.cache_data.clear()
    if message:
        st.session_state["_toast"] = message


def show_pending_toast() -> None:
    msg = st.session_state.pop("_toast", None)
    if msg:
        st.toast(msg, icon=":material/check_circle:")


def goto(page_key: str, customer_id: int | None = None, counterparty_id: int | None = None) -> None:
    if customer_id is not None:
        st.session_state["customer_id"] = int(customer_id)
        st.session_state.pop("counterparty_id", None)
        st.session_state["c360_select"] = f"c:{int(customer_id)}"
    if counterparty_id is not None:
        st.session_state["counterparty_id"] = int(counterparty_id)
        st.session_state.pop("customer_id", None)
        st.session_state["c360_select"] = f"p:{int(counterparty_id)}"
    st.switch_page(PAGES[page_key][0])


def run_safely(fn, *args, success: str | None = None, **kwargs) -> bool:
    """Execute a write; show friendly validation errors; log unexpected ones."""
    try:
        fn(*args, **kwargs)
    except ValueError as e:
        st.error(str(e), icon=":material/error:")
        return False
    except Exception as e:  # pragma: no cover
        log.exception("write failed")
        st.error(f"Something went wrong saving your change ({type(e).__name__}). Details were logged.")
        return False
    after_write(success)
    return True
