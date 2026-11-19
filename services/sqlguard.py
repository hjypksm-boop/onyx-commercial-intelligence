"""'Ask the portfolio' safety layer: only a single read-only SELECT over allow-listed views/tables."""
from __future__ import annotations

import re
import sqlite3

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

ROW_LIMIT = 500

ALLOWED_TABLES = {
    "v_customer_kpis", "v_pipeline", "v_renewals", "v_monthly_usage", "v_counterparty_summary", "v_feature_adoption",
    "v_customer_health", "v_portfolio_kpis", "tasks", "activities", "support_tickets", "owners", "products",
    "data_incidents", "trading_activity", "counterparty_issues", "customers", "contracts", "subscriptions",
    "onboarding_milestones", "port_activity", "ports",
}
FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach", "pragma", "replace", "truncate",
    "grant", "revoke", "vacuum", "reindex", "merge", "copy", "call", "exec", "execute", "into", "load_extension",
    "users", "audit_log", "app_config", "health_weights", "sqlite_master", "sqlite_schema", "information_schema",
    "pg_catalog", "pg_sleep", "set", "begin", "commit", "rollback", "savepoint", "lock", "listen", "notify",
}

SCHEMA_DOC = """\
v_customer_kpis(customer_id, customer_name, vertical, segment, hq_region, owner_name, arr_pence, licensed_seats,
  active_users, adoption_pct, renewal_date, days_to_renewal, contract_status, health_score, health_category,
  potential_expansion_pence, weighted_expansion_pence, open_opportunities, last_contact_date, ttfv_days)
v_pipeline(opportunity_id, customer_id, customer_name, product, description, potential_arr_pence, probability,
  expected_value_pence, stage, expected_close_date, owner_name, next_action, created_date, closed_date, is_open)
v_renewals(customer_id, customer_name, vertical, owner_name, arr_pence, renewal_date, days_to_renewal, health_score,
  health_category)
v_monthly_usage(customer_id, month 'YYYY-MM', mau, logins, sessions, pricing_queries, analytics_runs,
  reports_downloaded, api_calls)
v_counterparty_summary(counterparty_id, counterparty_name, region, relationship_status, approval_status, owner_name,
  trades_12m, notional_usd_12m  -- trading notional, NOT revenue, open_issues, last_contact_date)
v_feature_adoption(customer_id, customer_name, vertical, feature, adopted 0/1, usage_count_90d)
tasks(task_id, title, customer_id, category, priority, owner_id, due_date, status)
activities(activity_id, customer_id, counterparty_id, activity_type, activity_date, subject, sentiment 1-5)
support_tickets(ticket_id, customer_id, subject, severity, status, opened_date, closed_date, sla_breached, escalated)
Money columns ending _pence are integer pence (divide by 100 for £). Dates are ISO text 'YYYY-MM-DD'."""


def _strip(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validate(sql: str) -> tuple[bool, str, str | None]:
    """Return (ok, cleaned_sql, error)."""
    if not sql or not sql.strip():
        return False, "", "Empty query."
    s = _strip(sql).rstrip().rstrip(";").strip()
    no_strings = re.sub(r"'(?:[^']|'')*'", "''", s)
    if ";" in no_strings:
        return False, s, "Only a single statement is allowed."
    if not re.match(r"^\s*(select|with)\b", no_strings, re.I):
        return False, s, "Only SELECT queries are allowed."
    words = set(re.findall(r"[a-z_][a-z0-9_]*", no_strings.lower()))
    bad = sorted(words & FORBIDDEN)
    if bad:
        return False, s, f"Forbidden keyword or object: {', '.join(bad)}."
    ctes = {m.lower() for m in re.findall(r"\b([a-z_][a-z0-9_]*)\s+as\s*\(", no_strings, re.I)}
    # every table reference after FROM / JOIN / comma-join must be allow-listed
    refs = re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_\.]*)((?:\s*(?:as\s+)?[a-z_][a-z0-9_]*)?(?:\s*,\s*[a-z_][a-z0-9_\.]*)*)",
                      no_strings, re.I)
    names = []
    for first, rest in refs:
        names.append(first)
        names += re.findall(r",\s*([a-z_][a-z0-9_\.]*)", rest, re.I)
    for n in names:
        n = n.lower()
        if "." in n:
            return False, s, f"Schema-qualified names are not allowed ({n})."
        if n not in ALLOWED_TABLES and n not in ctes:
            return False, s, f"Table or view '{n}' is not in the allow-list."
    if not names:
        return False, s, "Query must read from at least one allow-listed view."
    return True, s, None


def limited(sql: str, limit: int = ROW_LIMIT) -> str:
    return f"SELECT * FROM ({sql}) AS q LIMIT {int(limit)}"


def run_readonly(engine: Engine, sql: str) -> pd.DataFrame:
    ok, cleaned, err = validate(sql)
    if not ok:
        raise ValueError(err)
    final = limited(cleaned)
    if engine.dialect.name == "sqlite":
        path = engine.url.database
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cur = conn.execute(final)
            cols = [c[0] for c in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
        finally:
            conn.close()
    with engine.connect() as conn:  # pragma: no cover - PostgreSQL
        trans = conn.begin()
        conn.execute(text("SET TRANSACTION READ ONLY"))
        res = conn.execute(text(final))
        df = pd.DataFrame(res.fetchall(), columns=list(res.keys()))
        trans.rollback()
        return df


EXAMPLES = {
    "Which accounts renew in the next 90 days and what is their health?":
        "SELECT customer_name, renewal_date, days_to_renewal, arr_pence / 100 AS arr_gbp, health_category "
        "FROM v_renewals WHERE days_to_renewal <= 90 ORDER BY days_to_renewal",
    "Total ARR by vertical":
        "SELECT vertical, SUM(arr_pence) / 100 AS arr_gbp, COUNT(*) AS accounts FROM v_customer_kpis "
        "GROUP BY vertical ORDER BY arr_gbp DESC",
    "Open opportunities ranked by expected value":
        "SELECT customer_name, description, potential_arr_pence / 100 AS potential_gbp, probability, "
        "expected_value_pence / 100 AS expected_value_gbp, stage FROM v_pipeline WHERE is_open = 1 "
        "ORDER BY expected_value_pence DESC",
    "Monthly active users for the last 6 months by customer":
        "SELECT k.customer_name, u.month, u.mau FROM v_monthly_usage u JOIN v_customer_kpis k "
        "ON k.customer_id = u.customer_id ORDER BY k.customer_name, u.month",
    "Which features are not adopted, by customer?":
        "SELECT customer_name, feature FROM v_feature_adoption WHERE adopted = 0 ORDER BY customer_name",
}
