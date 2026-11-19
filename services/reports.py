"""Commercial Close Report (end of day) — every figure computed from stored records."""
from __future__ import annotations

import io
import json
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, db
from services import formatting as fmt

SECTIONS = [
    ("performance", "1. Commercial performance"),
    ("developments", "2. Customer developments"),
    ("risks", "3. Risks and escalations"),
    ("growth", "4. Growth opportunities"),
    ("priorities", "5. Next-day priorities"),
]

SQL = {
    "activities": """SELECT a.activity_id, a.activity_type, a.subject, a.summary, a.sentiment,
                            COALESCE(c.name, cp.name) AS account_name,
                            CASE WHEN a.counterparty_id IS NOT NULL THEN 'Counterparty' ELSE 'Customer' END AS account_type,
                            ow.name AS owner_name
                     FROM activities a
                     LEFT JOIN customers c ON c.customer_id = a.customer_id
                     LEFT JOIN counterparties cp ON cp.counterparty_id = a.counterparty_id
                     LEFT JOIN owners ow ON ow.owner_id = a.owner_id
                     WHERE a.activity_date = :d
                     ORDER BY a.activity_type, account_name""",
    "new_opps": """SELECT opportunity_id, customer_name, product, description, potential_arr_pence, probability,
                          expected_value_pence, stage, owner_name
                   FROM v_pipeline WHERE created_date = :d ORDER BY potential_arr_pence DESC""",
    "booked": """SELECT opportunity_id, customer_name, product, description, potential_arr_pence AS booked_acv_pence, owner_name
                 FROM v_pipeline WHERE stage = 'Closed Won' AND closed_date = :d""",
    "stage_moves": """SELECT p.customer_name, p.description, h.from_stage, h.to_stage, h.changed_by
                      FROM opportunity_stage_history h JOIN v_pipeline p ON p.opportunity_id = h.opportunity_id
                      WHERE h.changed_on = :d AND h.from_stage IS NOT NULL""",
    "at_risk": """SELECT c.customer_id, c.name AS customer_name, ct.arr_pence, hs.score, hs.category, ct.renewal_date
                  FROM customers c
                  JOIN contracts ct ON ct.customer_id = c.customer_id AND ct.is_current = 1
                  JOIN health_snapshots hs ON hs.customer_id = c.customer_id
                  WHERE hs.snapshot_date = (SELECT MAX(h2.snapshot_date) FROM health_snapshots h2
                                            WHERE h2.customer_id = c.customer_id AND h2.snapshot_date <= :d)
                    AND hs.category = 'At Risk' AND c.status = 'Active'
                  ORDER BY ct.arr_pence DESC""",
    "cp_issues": """SELECT cp.name AS account_name, i.issue_type, i.description, i.severity
                    FROM counterparty_issues i JOIN counterparties cp ON cp.counterparty_id = i.counterparty_id
                    WHERE i.opened_date = :d""",
    "outstanding": """SELECT t.task_id, t.title, t.priority, t.due_date, t.status, ow.name AS owner_name,
                             COALESCE(c.name, cp.name, 'Internal') AS account_name
                      FROM tasks t JOIN owners ow ON ow.owner_id = t.owner_id
                      LEFT JOIN customers c ON c.customer_id = t.customer_id
                      LEFT JOIN counterparties cp ON cp.counterparty_id = t.counterparty_id
                      WHERE t.status <> 'Done' AND t.due_date <= :d
                      ORDER BY t.due_date, t.priority""",
    "next_day": """SELECT t.task_id, t.title, t.priority, t.due_date, ow.name AS owner_name,
                          COALESCE(c.name, cp.name, 'Internal') AS account_name,
                          CASE WHEN t.due_date < :next THEN 'Carried over' ELSE 'Due tomorrow' END AS reason
                   FROM tasks t JOIN owners ow ON ow.owner_id = t.owner_id
                   LEFT JOIN customers c ON c.customer_id = t.customer_id
                   LEFT JOIN counterparties cp ON cp.counterparty_id = t.counterparty_id
                   WHERE t.status <> 'Done'
                     AND (t.due_date = :next OR (t.due_date <= :d AND t.priority IN ('High', 'Critical')))
                   ORDER BY CASE t.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
                            t.due_date""",
    "renewals_30": """SELECT customer_name, arr_pence, renewal_date, days_to_renewal, health_category
                      FROM v_renewals WHERE renewal_date > :d AND renewal_date <= :d30 ORDER BY renewal_date""",
}


def compute(engine: Engine, report_date: str) -> dict:
    d = date.fromisoformat(report_date)
    p = {"d": report_date, "next": (d + timedelta(days=1)).isoformat(), "d30": (d + timedelta(days=30)).isoformat()}
    q = {k: db.query_df(engine, sql, p) for k, sql in SQL.items()}
    acts = q["activities"]
    contact_types = ["Meeting", "Call", "Email", "Demo"]
    pipe = db.query_one(engine, db.load_query(engine, "pipeline_totals"))
    m = {
        "report_date": report_date,
        "meetings_completed": int((acts["activity_type"] == "Meeting").sum()),
        "accounts_contacted": int(acts[acts["activity_type"].isin(contact_types)]["account_name"].nunique()),
        "demonstrations_completed": int((acts["activity_type"] == "Demo").sum()),
        "new_opportunities": len(q["new_opps"]),
        "new_opportunities_potential_pence": int(q["new_opps"]["potential_arr_pence"].sum()) if len(q["new_opps"]) else 0,
        "new_opportunities_weighted_pence": int(q["new_opps"]["expected_value_pence"].sum()) if len(q["new_opps"]) else 0,
        "booked_acv_pence": int(q["booked"]["booked_acv_pence"].sum()) if len(q["booked"]) else 0,
        "revenue_at_risk_pence": int(q["at_risk"]["arr_pence"].sum()) if len(q["at_risk"]) else 0,
        "accounts_at_risk": len(q["at_risk"]),
        "escalations": int((acts["activity_type"] == "Escalation").sum()) + len(q["cp_issues"]),
        "outstanding_tasks": len(q["outstanding"]),
        "open_pipeline_potential_pence": int(pipe["potential_expansion_pence"]),
        "open_pipeline_weighted_pence": int(pipe["weighted_pipeline_pence"]),
    }
    return {"metrics": m, "tables": q}


def default_commentary(r: dict) -> dict:
    """Deterministic template commentary built only from computed metrics."""
    m, t = r["metrics"], r["tables"]
    acts = t["activities"]
    met = acts[acts["activity_type"] == "Meeting"]["account_name"].tolist()
    perf = (f"{m['meetings_completed']} customer meetings completed across {m['accounts_contacted']} accounts; "
            f"{m['demonstrations_completed']} demonstration(s). Booked new ACV today: {fmt.gbp(m['booked_acv_pence'])}"
            f"{' (no deals closed today)' if not m['booked_acv_pence'] else ''}.")
    dev = ("Meetings held with " + ", ".join(dict.fromkeys(met)) + "." if met else "No customer meetings recorded.")
    risk_names = ", ".join(t["at_risk"]["customer_name"]) or "none"
    risks = (f"{m['accounts_at_risk']} account(s) at risk ({risk_names}) representing {fmt.gbp(m['revenue_at_risk_pence'])} "
             f"ARR. {m['escalations']} escalation(s) logged today.")
    growth = (f"{m['new_opportunities']} new opportunit{'y' if m['new_opportunities'] == 1 else 'ies'} identified worth "
              f"{fmt.gbp(m['new_opportunities_potential_pence'])} potential pipeline (not booked). Total open pipeline "
              f"{fmt.gbp(m['open_pipeline_potential_pence'])} potential / {fmt.gbp(m['open_pipeline_weighted_pence'])} weighted.")
    nd = t["next_day"]
    pri = ("Tomorrow: " + "; ".join((nd["priority"] + " — " + nd["title"]).head(6)) + "." if len(nd)
           else "No tasks scheduled for tomorrow.")
    if len(t["renewals_30"]):
        pri += " Renewals within 30 days: " + ", ".join(t["renewals_30"]["customer_name"]) + "."
    return {"performance": perf, "developments": dev, "risks": risks, "growth": growth, "priorities": pri}


def save(engine: Engine, user: str, report_date: str, metrics: dict, commentary: dict) -> int:
    version = int(db.scalar(engine, "SELECT COALESCE(MAX(version), 0) FROM close_reports WHERE report_date = :d",
                            {"d": report_date})) + 1
    with engine.begin() as conn:
        rid = db.insert_returning_id(conn, """INSERT INTO close_reports (report_date, version, metrics_json, commentary_json,
                status, created_by, created_at) VALUES (:d, :v, :m, :c, 'Draft', :u, :ts) RETURNING report_id""",
                                     {"d": report_date, "v": version, "m": json.dumps(metrics), "c": json.dumps(commentary),
                                      "u": user, "ts": audit.now_ts()})
        audit.log(conn, user, "close_report", rid, "create", f"Close report {report_date} saved (v{version})")
    return rid


def approve(engine: Engine, user: str, report_id: int) -> None:
    with engine.begin() as conn:
        db.execute(conn, "UPDATE close_reports SET status = 'Approved', approved_by = :u WHERE report_id = :id",
                   {"u": user, "id": report_id})
        audit.log(conn, user, "close_report", report_id, "update", "Close report approved",
                  changes={"status": ["Draft", "Approved"]})


def versions(engine: Engine, report_date: str) -> pd.DataFrame:
    return db.query_df(engine, """SELECT report_id, version, status, approved_by, created_by, created_at, commentary_json
                                  FROM close_reports WHERE report_date = :d ORDER BY version DESC""", {"d": report_date})


def to_csv(r: dict) -> bytes:
    """CSV of the underlying metrics and activity records."""
    buf = io.StringIO()
    m = r["metrics"]
    buf.write("section,metric,value\n")
    for k, v in m.items():
        if k.endswith("_pence"):
            buf.write(f"metric,{k.replace('_pence', '_gbp')},{v / 100:.2f}\n")
        else:
            buf.write(f"metric,{k},{v}\n")
    for name, df in r["tables"].items():
        if df.empty:
            continue
        buf.write(f"\n# {name}\n")
        out = df.copy()
        for c in [c for c in out.columns if c.endswith("_pence")]:
            out[c.replace("_pence", "_gbp")] = out.pop(c) / 100
        out.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")
