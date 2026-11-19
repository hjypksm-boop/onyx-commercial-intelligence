"""Read-side KPI helpers shared by pages and tests. Filtering is done in SQL with bound parameters."""
from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from services import db, priority

VERTICALS = ["Flux Bunkers", "Flux Analytics", "The Officials"]
HEALTH_CATEGORIES = ["Healthy", "Monitor", "At Risk"]


def filter_params(filters: dict | None) -> dict:
    f = filters or {}
    v, o, h = f.get("verticals") or [], f.get("owners") or [], f.get("health") or []
    return {"all_verticals": 0 if v else 1, "verticals": list(v),
            "all_owners": 0 if o else 1, "owners": list(o),
            "all_health": 0 if h else 1, "health": list(h)}


def portfolio_kpis(engine: Engine, filters: dict | None = None) -> dict:
    return db.query_one(engine, db.load_query(engine, "portfolio_kpis"), filter_params(filters))


def customers(engine: Engine, filters: dict | None = None) -> pd.DataFrame:
    """v_customer_kpis + commercial priority (normalised over the full portfolio), then filtered."""
    df = db.query_df(engine, "SELECT * FROM v_customer_kpis ORDER BY arr_pence DESC")
    df = priority.add_priority(df)
    f = filters or {}
    if f.get("verticals"):
        df = df[df["vertical"].isin(f["verticals"])]
    if f.get("owners"):
        df = df[df["owner_name"].isin(f["owners"])]
    if f.get("health"):
        df = df[df["health_category"].isin(f["health"])]
    return df.reset_index(drop=True)


def counterparties(engine: Engine, filters: dict | None = None) -> pd.DataFrame:
    df = db.query_df(engine, "SELECT * FROM v_counterparty_summary ORDER BY counterparty_name")
    f = filters or {}
    if f.get("owners"):
        df = df[df["owner_name"].isin(f["owners"])]
    return df.reset_index(drop=True)


def adoption_trend(engine: Engine, start_month: str, end_month: str, filters: dict | None = None) -> pd.DataFrame:
    return db.query_df(engine, db.load_query(engine, "adoption_trend"),
                       {"start_month": start_month, "end_month": end_month, **filter_params(filters)})


def activity_feed(engine: Engine, start: str, end: str) -> pd.DataFrame:
    return db.query_df(engine, db.load_query(engine, "activity_feed"), {"start": start, "end": end})


def owners(engine: Engine) -> pd.DataFrame:
    return db.query_df(engine, "SELECT owner_id, name, title FROM owners ORDER BY owner_id")
