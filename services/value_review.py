"""Value Review Builder — assembles an editable business review from stored account data only."""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, customers, db, health
from services import formatting as fmt

SECTIONS = [
    ("summary", "Executive summary"),
    ("overview", "Customer overview"),
    ("commercial", "Subscription and commercial value"),
    ("usage", "Usage and adoption trends"),
    ("achievements", "Key achievements"),
    ("issues", "Outstanding issues"),
    ("health", "Customer health"),
    ("opportunities", "Opportunities for additional value"),
    ("actions", "Recommended actions"),
    ("owners", "Owners and deadlines"),
]


def facts(engine: Engine, customer_id: int, start: str, end: str) -> dict:
    """Structured facts for one customer and period. The only data passed to templates and the AI."""
    p = customers.profile(engine, customer_id)
    if not p:
        raise ValueError("Customer not found.")
    usage = db.query_df(engine, """SELECT month, mau, sessions, logins, pricing_queries, analytics_runs, reports_downloaded,
                                   api_calls FROM v_monthly_usage WHERE customer_id = :c AND month >= :s AND month <= :e
                                   ORDER BY month""", {"c": customer_id, "s": start[:7], "e": end[:7]})
    feats = db.query_df(engine, """SELECT feature, adopted, usage_count_90d FROM v_feature_adoption WHERE customer_id = :c
                                   ORDER BY usage_count_90d DESC""", {"c": customer_id})
    tickets = db.query_df(engine, """SELECT subject, severity, status, opened_date, closed_date, sla_breached
                                     FROM support_tickets WHERE customer_id = :c
                                     AND (opened_date BETWEEN :s AND :e OR closed_date IS NULL)
                                     ORDER BY opened_date""", {"c": customer_id, "s": start, "e": end})
    meetings = db.query_df(engine, """SELECT activity_date, subject, sentiment FROM activities WHERE customer_id = :c
                                      AND activity_type = 'Meeting' AND activity_date BETWEEN :s AND :e
                                      ORDER BY activity_date""", {"c": customer_id, "s": start, "e": end})
    opps = db.query_df(engine, """SELECT description, potential_arr_pence, probability, expected_value_pence, stage,
                                  expected_close_date, owner_name, next_action FROM v_pipeline WHERE customer_id = :c
                                  AND is_open = 1 ORDER BY expected_value_pence DESC""", {"c": customer_id})
    tasks = db.query_df(engine, """SELECT t.title, t.due_date, t.priority, ow.name AS owner_name FROM tasks t
                                   JOIN owners ow ON ow.owner_id = t.owner_id WHERE t.customer_id = :c
                                   AND t.status <> 'Done' ORDER BY t.due_date""", {"c": customer_id})
    milestones = db.query_df(engine, """SELECT milestone, completed_date FROM onboarding_milestones WHERE customer_id = :c
                                        ORDER BY seq""", {"c": customer_id})
    hres = next((r for r in health.compute(engine) if r.customer_id == customer_id), None)
    missing = []
    if usage.empty:
        missing.append("No usage records in this period.")
    if meetings.empty or meetings["sentiment"].isna().all():
        missing.append("No sentiment recorded in this period.")
    if hres and hres.available < 5:
        missing.append(f"Health score is partial ({hres.available} of 5 components).")
    first_mau = int(usage["mau"].iloc[0]) if len(usage) else None
    last_mau = int(usage["mau"].iloc[-1]) if len(usage) else None
    return {
        "customer": p["customer_name"], "vertical": p["vertical"], "segment": p["segment"], "region": p["hq_region"],
        "owner": p["owner_name"], "customer_since": p["customer_since"], "period_start": start, "period_end": end,
        "arr_pence": int(p["arr_pence"]), "renewal_date": p["renewal_date"], "days_to_renewal": int(p["days_to_renewal"]),
        "modules": p["modules"], "contract_status": p["contract_status"], "billing": p["billing_frequency"],
        "licensed_seats": int(p["licensed_seats"]), "active_users": int(p["active_users"]),
        "adoption_pct": float(p["adoption_pct"]), "ttfv_days": p["ttfv_days"],
        "onboarding": f"{int(p['milestones_done'] or 0)} of {int(p['milestones_total'] or 0)} milestones complete",
        "mau_first": first_mau, "mau_last": last_mau,
        "mau_change_pct": ((last_mau - first_mau) / first_mau * 100) if first_mau else None,
        "usage": usage, "features": feats, "tickets": tickets, "meetings": meetings, "opportunities": opps,
        "tasks": tasks, "milestones": milestones,
        "health_score": hres.score if hres else None, "health_category": hres.category if hres else None,
        "health_reason": hres.reason if hres else "No health data.", "health_result": hres, "missing": missing,
    }


def facts_for_ai(f: dict) -> dict:
    """JSON-safe subset of facts sent to the model (synthetic data only)."""
    adopted = f["features"][f["features"]["adopted"] == 1]["feature"].tolist() if len(f["features"]) else []
    not_adopted = f["features"][f["features"]["adopted"] == 0]["feature"].tolist() if len(f["features"]) else []
    return {
        "customer": f["customer"], "vertical": f["vertical"], "period": f"{f['period_start']} to {f['period_end']}",
        "annual_contract_value_gbp": f["arr_pence"] / 100, "renewal_date": f["renewal_date"],
        "days_to_renewal": f["days_to_renewal"], "licensed_seats": f["licensed_seats"], "active_users": f["active_users"],
        "adoption_pct": round(f["adoption_pct"], 1), "mau_start_of_period": f["mau_first"], "mau_end_of_period": f["mau_last"],
        "health_score": f["health_score"], "health_category": f["health_category"], "health_reason": f["health_reason"],
        "features_adopted": adopted, "features_not_adopted": not_adopted,
        "open_tickets": f["tickets"][f["tickets"]["closed_date"].isna()]["subject"].tolist() if len(f["tickets"]) else [],
        "open_opportunities": [{"description": r["description"], "potential_gbp": r["potential_arr_pence"] / 100,
                                "probability": float(r["probability"]), "stage": r["stage"]}
                               for r in f["opportunities"].to_dict("records")],
        "missing_information": f["missing"],
    }


def default_sections(f: dict) -> dict:
    """Template text for every section, built only from facts. Missing info is stated explicitly."""
    usage, feats, tickets, opps, tasks = f["usage"], f["features"], f["tickets"], f["opportunities"], f["tasks"]
    open_t = tickets[tickets["closed_date"].isna()] if len(tickets) else tickets
    closed_t = tickets[tickets["closed_date"].notna()] if len(tickets) else tickets
    adopted = feats[feats["adopted"] == 1] if len(feats) else feats
    s = {}
    trend = ("" if f["mau_change_pct"] is None else
             f"Monthly active users moved from {f['mau_first']} to {f['mau_last']} over the period "
             f"({f['mau_change_pct']:+.0f}%). ")
    s["summary"] = (
        f"{f['customer']} ({f['vertical']}) holds an annual contract worth {fmt.gbp(f['arr_pence'])}, renewing on "
        f"{fmt.fdate(f['renewal_date'])} ({f['days_to_renewal']} days). {f['active_users']} of {f['licensed_seats']} licensed "
        f"seats are active ({f['adoption_pct']:.1f}%). {trend}Calculated health: {f['health_category']} "
        f"({f['health_score']:.0f}/100). " + (f"{len(opps)} open growth opportunit{'y' if len(opps) == 1 else 'ies'} "
                                              f"identified." if len(opps) else "No open growth opportunities.")
    )
    s["overview"] = (f"Vertical: {f['vertical']} · Segment: {f['segment']} · Region: {f['region']} · Customer since "
                     f"{fmt.fdate(f['customer_since'])} · Relationship owner: {f['owner']}.")
    s["commercial"] = (f"Annual contract value {fmt.gbp(f['arr_pence'])} ({f['billing']} billing), contract status "
                       f"{f['contract_status']}. Modules: {f['modules']}. Renewal {fmt.fdate(f['renewal_date'])}.")
    if usage.empty:
        s["usage"] = "Missing information: no usage records for this period."
    else:
        s["usage"] = (f"{trend}Seat adoption {f['adoption_pct']:.1f}% ({f['active_users']}/{f['licensed_seats']}). "
                      f"Sessions in period: {int(usage['sessions'].sum()):,}. Time to first value: "
                      f"{f['ttfv_days'] if f['ttfv_days'] is not None else 'not recorded'} days; onboarding {f['onboarding']}.")
    ach = []
    if len(adopted):
        top = adopted.head(3)
        ach.append("Most-used capabilities (90 days): " + ", ".join(f"{r.feature} ({r.usage_count_90d:,})"
                                                                     for r in top.itertuples()) + ".")
    if len(closed_t):
        ach.append(f"{len(closed_t)} support ticket(s) resolved in the period.")
    if f["mau_change_pct"] is not None and f["mau_change_pct"] > 0:
        ach.append(f"Active user base grew {f['mau_change_pct']:.0f}%.")
    s["achievements"] = " ".join(ach) or "No achievements could be evidenced from stored data for this period."
    s["issues"] = ("Open support issues: " + "; ".join(f"{r.severity} — {r.subject}" for r in open_t.itertuples()) + "."
                   if len(open_t) else "No open support issues.")
    not_adopted = feats[feats["adopted"] == 0]["feature"].tolist() if len(feats) else []
    if not_adopted:
        s["issues"] += " Capabilities not yet adopted: " + ", ".join(not_adopted) + "."
    s["health"] = f["health_reason"]
    s["opportunities"] = ("; ".join(f"{r.description} — {fmt.gbp(r.potential_arr_pence)} potential, "
                                    f"{float(r.probability) * 100:.0f}% probability ({r.stage})" for r in opps.itertuples()) + "."
                          if len(opps) else "No open opportunities recorded.")
    acts = []
    if f["adoption_pct"] < 70:
        acts.append("Run a seat-activation session for inactive licensed users.")
    if len(open_t):
        acts.append("Agree resolution dates for open support issues.")
    if not_adopted:
        acts.append(f"Demonstrate {not_adopted[0]} to relevant users.")
    if f["days_to_renewal"] <= 90:
        acts.append("Begin renewal conversation with the decision maker.")
    s["actions"] = " ".join(acts) or "Maintain current engagement cadence."
    s["owners"] = ("; ".join(f"{r.title} — {r.owner_name}, due {fmt.fdate(r.due_date)}" for r in tasks.itertuples()) + "."
                   if len(tasks) else "No open tasks assigned. Assign owners for the recommended actions above.")
    if f["missing"]:
        s["summary"] += " Assumptions / missing information: " + " ".join(f["missing"])
    return s


def save(engine: Engine, user: str, customer_id: int, start: str, end: str, content: dict) -> int:
    version = int(db.scalar(engine, "SELECT COALESCE(MAX(version), 0) FROM value_reviews WHERE customer_id = :c",
                            {"c": customer_id})) + 1
    with engine.begin() as conn:
        rid = db.insert_returning_id(conn, """INSERT INTO value_reviews (customer_id, period_start, period_end, version,
                content_json, created_by, created_at) VALUES (:c, :s, :e, :v, :j, :u, :ts) RETURNING review_id""",
                                     {"c": customer_id, "s": start, "e": end, "v": version, "j": json.dumps(content),
                                      "u": user, "ts": audit.now_ts()})
        audit.log(conn, user, "value_review", rid, "create", f"Value review v{version} saved", customer_id)
    return rid


def versions(engine: Engine, customer_id: int) -> pd.DataFrame:
    return db.query_df(engine, """SELECT review_id, version, period_start, period_end, created_by, created_at, content_json
                                  FROM value_reviews WHERE customer_id = :c ORDER BY version DESC""", {"c": customer_id})
