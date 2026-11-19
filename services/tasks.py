"""Tasks & follow-ups: validated CRUD with audit trail."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, db

CATEGORIES = ["Customer escalation", "Renewal preparation", "Sales follow-up", "Product demonstration", "Onboarding",
              "Commercial reporting"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In progress", "Blocked", "Done"]
FIELDS = ["title", "customer_id", "counterparty_id", "category", "priority", "owner_id", "due_date", "status", "notes"]


def _clean(data: dict) -> dict:
    out = {k: data.get(k) for k in FIELDS}
    out["title"] = (out["title"] or "").strip()
    out["notes"] = (out["notes"] or "").strip() or None
    for k in ("customer_id", "counterparty_id", "owner_id"):
        v = out[k]
        out[k] = None if v in (None, "", 0) or (isinstance(v, float) and pd.isna(v)) else int(v)
    if isinstance(out["due_date"], date):
        out["due_date"] = out["due_date"].isoformat()
    out["status"] = out["status"] or "Open"
    out["priority"] = out["priority"] or "Medium"
    return out


def validate(data: dict) -> list[str]:
    d = _clean(data)
    errors = []
    if not d["title"]:
        errors.append("Title is required.")
    elif len(d["title"]) > 200:
        errors.append("Title must be 200 characters or fewer.")
    if not d["owner_id"]:
        errors.append("Owner is required.")
    if not d["due_date"]:
        errors.append("Due date is required.")
    else:
        try:
            date.fromisoformat(str(d["due_date"])[:10])
        except ValueError:
            errors.append("Due date is not a valid date.")
    if d["category"] not in CATEGORIES:
        errors.append("Choose a valid category.")
    if d["priority"] not in PRIORITIES:
        errors.append("Choose a valid priority.")
    if d["status"] not in STATUSES:
        errors.append("Choose a valid status.")
    if d["customer_id"] and d["counterparty_id"]:
        errors.append("Link a task to a customer or a counterparty, not both.")
    return errors


def insert(conn, user: str, data: dict, as_of: str, source: str = "Manual") -> int:
    """Insert inside an existing transaction (used by meeting / retention workflows)."""
    errors = validate(data)
    if errors:
        raise ValueError(" ".join(errors))
    d = _clean(data)
    tid = db.insert_returning_id(
        conn,
        """INSERT INTO tasks (title, customer_id, counterparty_id, category, priority, owner_id, due_date, status, notes,
           source, created_on, completed_on)
           VALUES (:title, :customer_id, :counterparty_id, :category, :priority, :owner_id, :due_date, :status, :notes,
           :source, :created_on, :completed_on) RETURNING task_id""",
        {**d, "source": source, "created_on": as_of, "completed_on": as_of if d["status"] == "Done" else None},
    )
    audit.log(conn, user, "task", tid, "create", f"Task created: {d['title']}", d["customer_id"], d["counterparty_id"],
              changes={k: [None, v] for k, v in d.items() if v is not None})
    return tid


def create(engine: Engine, user: str, data: dict, source: str = "Manual") -> int:
    as_of = db.as_of(engine)
    with engine.begin() as conn:
        return insert(conn, user, data, as_of, source)


def get(engine: Engine, task_id: int) -> dict | None:
    return db.query_one(engine, "SELECT * FROM tasks WHERE task_id = :id", {"id": task_id})


def update(engine: Engine, user: str, task_id: int, data: dict) -> None:
    old = get(engine, task_id)
    if not old:
        raise ValueError("Task not found.")
    merged = {**{k: old[k] for k in FIELDS}, **data}
    errors = validate(merged)
    if errors:
        raise ValueError(" ".join(errors))
    d = _clean(merged)
    as_of = db.as_of(engine)
    completed_on = old["completed_on"]
    if d["status"] == "Done" and old["status"] != "Done":
        completed_on = as_of
    elif d["status"] != "Done":
        completed_on = None
    changes = audit.diff({k: old[k] for k in FIELDS}, d)
    if not changes:
        return
    with engine.begin() as conn:
        db.execute(conn, """UPDATE tasks SET title=:title, customer_id=:customer_id, counterparty_id=:counterparty_id,
                            category=:category, priority=:priority, owner_id=:owner_id, due_date=:due_date, status=:status,
                            notes=:notes, completed_on=:completed_on WHERE task_id=:id""",
                   {**d, "completed_on": completed_on, "id": task_id})
        audit.log(conn, user, "task", task_id, "update", f"Task updated: {d['title']}", d["customer_id"],
                  d["counterparty_id"], changes)


def complete(engine: Engine, user: str, task_ids: list[int]) -> int:
    n = 0
    for tid in task_ids:
        t = get(engine, tid)
        if t and t["status"] != "Done":
            update(engine, user, tid, {"status": "Done"})
            n += 1
    return n


def delete(engine: Engine, user: str, task_id: int) -> None:
    old = get(engine, task_id)
    if not old:
        raise ValueError("Task not found.")
    with engine.begin() as conn:
        db.execute(conn, "DELETE FROM tasks WHERE task_id = :id", {"id": task_id})
        audit.log(conn, user, "task", task_id, "delete", f"Task deleted: {old['title']}", old["customer_id"],
                  old["counterparty_id"], changes={k: [old[k], None] for k in FIELDS})


def list_all(engine: Engine) -> pd.DataFrame:
    return db.query_df(engine, db.load_query(engine, "tasks_list"))


def bucket(due_date: str, status: str, as_of: str) -> str:
    if status == "Done":
        return "Done"
    if due_date < as_of:
        return "Overdue"
    if due_date == as_of:
        return "Due today"
    return "Upcoming"
