"""Customer & counterparty actions (notes, meetings, escalations, seat/owner edits) and profile reads."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, db, tasks

ACTIVITY_TYPES = ["Meeting", "Call", "Email", "Demo", "Note", "Escalation"]
SEVERITIES = ["Low", "Medium", "High", "Critical"]
SLA_HOURS = {"Low": 72, "Medium": 48, "High": 24, "Critical": 8}


def _iso(v) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, date) else str(v)[:10]


# ------------------------------------------------------------------------------------------- writes
def add_note(engine: Engine, user: str, body: str, customer_id: int | None = None,
             counterparty_id: int | None = None) -> int:
    body = (body or "").strip()
    if not body:
        raise ValueError("Note text is required.")
    if len(body) > 4000:
        raise ValueError("Note must be 4,000 characters or fewer.")
    if not customer_id and not counterparty_id:
        raise ValueError("A customer or counterparty is required.")
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        nid = db.insert_returning_id(conn, """INSERT INTO account_notes (customer_id, counterparty_id, note_date, author, body)
                                              VALUES (:c, :cp, :d, :a, :b) RETURNING note_id""",
                                     {"c": customer_id, "cp": counterparty_id, "d": as_of, "a": user, "b": body})
        audit.log(conn, user, "account_note", nid, "create", "Account note added", customer_id, counterparty_id,
                  {"body": [None, body[:200]]})
    return nid


def log_activity(engine: Engine, user: str, *, activity_type: str, activity_date, subject: str, summary: str = "",
                 customer_id: int | None = None, counterparty_id: int | None = None, attendees: str = "",
                 sentiment: int | None = None, next_steps: str = "", owner_id: int | None = None,
                 follow_up_tasks: list[dict] | None = None) -> int:
    """Record a meeting/call/email/demo. Optional follow-up tasks are created in the same transaction."""
    errors = []
    if activity_type not in ACTIVITY_TYPES:
        errors.append("Choose a valid activity type.")
    if not (subject or "").strip():
        errors.append("Subject is required.")
    if not activity_date:
        errors.append("Date is required.")
    as_of = db.as_of(engine)
    d = _iso(activity_date)
    if d and d > as_of:
        errors.append("Activities cannot be dated after the workspace date (they record what has happened).")
    if sentiment is not None and not (1 <= int(sentiment) <= 5):
        errors.append("Sentiment must be between 1 and 5.")
    if activity_type == "Meeting" and not (attendees or "").strip():
        errors.append("Attendees are required for a meeting.")
    if not customer_id and not counterparty_id:
        errors.append("A customer or counterparty is required.")
    for t in follow_up_tasks or []:
        errors += [f"Follow-up task: {e}" for e in tasks.validate(t)]
    if errors:
        raise ValueError(" ".join(errors))
    with engine.begin() as conn:
        aid = db.insert_returning_id(
            conn,
            """INSERT INTO activities (customer_id, counterparty_id, activity_type, activity_date, subject, summary, attendees,
               sentiment, next_steps, owner_id, created_by, created_at)
               VALUES (:c, :cp, :t, :d, :s, :sm, :a, :se, :n, :o, :u, :ts) RETURNING activity_id""",
            {"c": customer_id, "cp": counterparty_id, "t": activity_type, "d": d, "s": subject.strip(),
             "sm": (summary or "").strip() or None, "a": (attendees or "").strip() or None,
             "se": int(sentiment) if sentiment is not None else None, "n": (next_steps or "").strip() or None,
             "o": owner_id, "u": user, "ts": audit.now_ts()})
        audit.log(conn, user, "activity", aid, "create", f"{activity_type} recorded: {subject.strip()}", customer_id,
                  counterparty_id, {"activity_date": [None, d], "sentiment": [None, sentiment]})
        for t in follow_up_tasks or []:
            tasks.insert(conn, user, {**t, "customer_id": customer_id, "counterparty_id": counterparty_id}, as_of,
                         source=f"{activity_type} #{aid}")
    return aid


def log_escalation(engine: Engine, user: str, customer_id: int, *, reason: str, ticket_id: int | None = None,
                   subject: str = "", severity: str = "High", owner_id: int | None = None) -> int:
    """Escalate an existing ticket or open a new escalated ticket; always records an Escalation activity."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Escalation reason is required.")
    if ticket_id is None:
        if not (subject or "").strip():
            raise ValueError("Ticket subject is required for a new escalation.")
        if severity not in SEVERITIES:
            raise ValueError("Choose a valid severity.")
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        if ticket_id is None:
            ticket_id = db.insert_returning_id(
                conn, """INSERT INTO support_tickets (customer_id, subject, severity, status, opened_date, sla_hours,
                         sla_breached, escalated) VALUES (:c, :s, :sev, 'Open', :d, :sla, 0, 1) RETURNING ticket_id""",
                {"c": customer_id, "s": subject.strip(), "sev": severity, "d": as_of, "sla": SLA_HOURS[severity]})
            audit.log(conn, user, "support_ticket", ticket_id, "create", f"Escalated ticket opened: {subject.strip()}",
                      customer_id, changes={"severity": [None, severity], "escalated": [None, 1]})
            label = subject.strip()
        else:
            old = db.execute(conn, "SELECT * FROM support_tickets WHERE ticket_id = :id AND customer_id = :c",
                             {"id": ticket_id, "c": customer_id}).mappings().first()
            if not old:
                raise ValueError("Ticket not found for this customer.")
            new_sev = severity if severity in SEVERITIES else old["severity"]
            db.execute(conn, """UPDATE support_tickets SET escalated = 1, severity = :sev,
                                status = CASE WHEN status IN ('Resolved', 'Closed') THEN 'Open' ELSE status END,
                                closed_date = NULL WHERE ticket_id = :id""", {"sev": new_sev, "id": ticket_id})
            audit.log(conn, user, "support_ticket", ticket_id, "update", f"Ticket escalated: {old['subject']}",
                      customer_id, changes={"escalated": [old["escalated"], 1], "severity": [old["severity"], new_sev]})
            label = old["subject"]
        aid = db.insert_returning_id(
            conn, """INSERT INTO activities (customer_id, activity_type, activity_date, subject, summary, owner_id,
                     created_by, created_at) VALUES (:c, 'Escalation', :d, :s, :sm, :o, :u, :ts) RETURNING activity_id""",
            {"c": customer_id, "d": as_of, "s": f"Escalation: {label}"[:200], "sm": reason, "o": owner_id, "u": user,
             "ts": audit.now_ts()})
        audit.log(conn, user, "activity", aid, "create", f"Escalation logged: {label}", customer_id)
    return ticket_id


def update_ticket_status(engine: Engine, user: str, ticket_id: int, status: str) -> None:
    if status not in ("Open", "In progress", "Resolved", "Closed"):
        raise ValueError("Invalid ticket status.")
    as_of = db.as_of(engine)
    old = db.query_one(engine, "SELECT * FROM support_tickets WHERE ticket_id = :id", {"id": ticket_id})
    if not old:
        raise ValueError("Ticket not found.")
    closed = as_of if status in ("Resolved", "Closed") else None
    with engine.begin() as conn:
        db.execute(conn, "UPDATE support_tickets SET status = :s, closed_date = :c WHERE ticket_id = :id",
                   {"s": status, "c": closed, "id": ticket_id})
        audit.log(conn, user, "support_ticket", ticket_id, "update", f"Ticket status → {status}: {old['subject']}",
                  old["customer_id"], changes={"status": [old["status"], status]})


def update_account(engine: Engine, user: str, customer_id: int, *, licensed_seats: int, active_users: int,
                   owner_id: int | None) -> None:
    errors = []
    if licensed_seats is None or int(licensed_seats) < 0:
        errors.append("Licensed seats must be zero or more.")
    if active_users is None or int(active_users) < 0:
        errors.append("Active users must be zero or more.")
    if not errors and int(active_users) > int(licensed_seats):
        errors.append("Active users cannot exceed licensed seats.")
    if errors:
        raise ValueError(" ".join(errors))
    old = db.query_one(engine, """SELECT s.licensed_seats, s.active_users, c.owner_id FROM subscriptions s
                                  JOIN customers c ON c.customer_id = s.customer_id WHERE s.customer_id = :c""",
                       {"c": customer_id})
    new = {"licensed_seats": int(licensed_seats), "active_users": int(active_users), "owner_id": owner_id}
    changes = audit.diff(old, new)
    if not changes:
        return
    with engine.begin() as conn:
        db.execute(conn, "UPDATE subscriptions SET licensed_seats = :l, active_users = :a WHERE customer_id = :c",
                   {"l": new["licensed_seats"], "a": new["active_users"], "c": customer_id})
        db.execute(conn, "UPDATE customers SET owner_id = :o WHERE customer_id = :c", {"o": owner_id, "c": customer_id})
        audit.log(conn, user, "customer", customer_id, "update", "Account details updated", customer_id, changes=changes)


def update_counterparty(engine: Engine, user: str, counterparty_id: int, *, relationship_status: str,
                        approval_status: str, owner_id: int | None) -> None:
    if relationship_status not in ("Active", "Developing", "Dormant", "On hold"):
        raise ValueError("Invalid relationship status.")
    if approval_status not in ("Approved", "Pending KYC", "Under Review", "Suspended"):
        raise ValueError("Invalid approval status.")
    old = db.query_one(engine, """SELECT relationship_status, approval_status, owner_id FROM counterparties
                                  WHERE counterparty_id = :id""", {"id": counterparty_id})
    new = {"relationship_status": relationship_status, "approval_status": approval_status, "owner_id": owner_id}
    changes = audit.diff(old, new)
    if not changes:
        return
    with engine.begin() as conn:
        db.execute(conn, """UPDATE counterparties SET relationship_status = :r, approval_status = :a, owner_id = :o
                            WHERE counterparty_id = :id""",
                   {"r": relationship_status, "a": approval_status, "o": owner_id, "id": counterparty_id})
        audit.log(conn, user, "counterparty", counterparty_id, "update", "Counterparty status updated",
                  counterparty_id=counterparty_id, changes=changes)


def add_counterparty_issue(engine: Engine, user: str, counterparty_id: int, *, issue_type: str, description: str,
                           severity: str, owner_id: int | None) -> int:
    if not (description or "").strip():
        raise ValueError("Issue description is required.")
    if issue_type not in ("Execution", "Settlement", "Confirmation", "Service", "Credit"):
        raise ValueError("Invalid issue type.")
    if severity not in SEVERITIES:
        raise ValueError("Invalid severity.")
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        iid = db.insert_returning_id(conn, """INSERT INTO counterparty_issues (counterparty_id, issue_type, description,
                severity, status, opened_date, owner_id) VALUES (:c, :t, :d, :s, 'Open', :o, :ow) RETURNING issue_id""",
                                     {"c": counterparty_id, "t": issue_type, "d": description.strip(), "s": severity,
                                      "o": as_of, "ow": owner_id})
        audit.log(conn, user, "counterparty_issue", iid, "create", f"{issue_type} issue logged", counterparty_id=counterparty_id)
    return iid


def resolve_counterparty_issue(engine: Engine, user: str, issue_id: int) -> None:
    as_of = db.as_of(engine)
    old = db.query_one(engine, "SELECT * FROM counterparty_issues WHERE issue_id = :id", {"id": issue_id})
    if not old:
        raise ValueError("Issue not found.")
    with engine.begin() as conn:
        db.execute(conn, "UPDATE counterparty_issues SET status = 'Resolved', resolved_date = :d WHERE issue_id = :id",
                   {"d": as_of, "id": issue_id})
        audit.log(conn, user, "counterparty_issue", issue_id, "update", "Issue resolved",
                  counterparty_id=old["counterparty_id"], changes={"status": [old["status"], "Resolved"]})


# ------------------------------------------------------------------------------------------- reads
def profile(engine: Engine, customer_id: int) -> dict | None:
    return db.query_one(engine, """SELECT k.*, c.customer_since, ct.start_date, ct.term_months, ct.billing_frequency,
                                          ct.modules, p.product_id
                                   FROM v_customer_kpis k
                                   JOIN customers c ON c.customer_id = k.customer_id
                                   JOIN products p ON p.name = k.vertical
                                   JOIN v_current_contracts ct ON ct.customer_id = k.customer_id
                                   WHERE k.customer_id = :c""", {"c": customer_id})


def monthly_usage(engine: Engine, customer_id: int) -> pd.DataFrame:
    return db.query_df(engine, "SELECT * FROM v_monthly_usage WHERE customer_id = :c ORDER BY month", {"c": customer_id})


def mau_decline(engine: Engine, customer_id: int, months: int = 6) -> dict | None:
    """Change in MAU across the most recent `months` calendar months (computed from usage_daily)."""
    df = monthly_usage(engine, customer_id)
    if len(df) < 2:
        return None
    recent = df.tail(months)
    first, last = recent.iloc[0], recent.iloc[-1]
    if not first["mau"]:
        return None
    change = (float(last["mau"]) - float(first["mau"])) / float(first["mau"])
    return {"from_month": first["month"], "to_month": last["month"], "from_mau": int(first["mau"]),
            "to_mau": int(last["mau"]), "change": change, "series": [int(x) for x in recent["mau"]]}
