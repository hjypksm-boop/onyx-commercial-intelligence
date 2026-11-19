"""Growth pipeline: validated CRUD, stage history, expected value, booked ACV."""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.engine import Engine

from services import audit, db

STAGES = ["Identified", "Qualified", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]
OPEN_STAGES = STAGES[:4]
CLOSED_STAGES = STAGES[4:]
FIELDS = ["customer_id", "product_id", "description", "potential_arr_pence", "probability", "stage",
          "expected_close_date", "owner_id", "next_action", "qualification"]
QUALIFICATION = ["Need confirmed", "Budget identified", "Timing agreed", "Decision maker engaged"]


def expected_value(potential_pence: int, probability: float) -> int:
    """Expected value = potential revenue × probability (pence, rounded)."""
    return int(round(float(potential_pence) * float(probability)))


def _clean(data: dict) -> dict:
    d = {k: data.get(k) for k in FIELDS}
    d["description"] = (d["description"] or "").strip()
    d["next_action"] = (d["next_action"] or "").strip() or None
    if isinstance(d["expected_close_date"], date):
        d["expected_close_date"] = d["expected_close_date"].isoformat()
    for k in ("customer_id", "owner_id"):
        d[k] = None if d[k] in (None, "", 0) or (isinstance(d[k], float) and pd.isna(d[k])) else int(d[k])
    if d["potential_arr_pence"] is not None:
        d["potential_arr_pence"] = int(round(float(d["potential_arr_pence"])))
    if d["probability"] is not None:
        d["probability"] = float(d["probability"])
    return d


def validate(data: dict, as_of: str, check_close_date: bool = True) -> list[str]:
    d = _clean(data)
    errors = []
    if not d["customer_id"]:
        errors.append("Customer is required.")
    if not d["description"]:
        errors.append("Description is required.")
    if d["potential_arr_pence"] is None or d["potential_arr_pence"] <= 0:
        errors.append("Potential annual revenue must be greater than £0.")
    if d["probability"] is None or not (0 <= d["probability"] <= 1):
        errors.append("Probability must be between 0% and 100%.")
    if d["stage"] not in STAGES:
        errors.append("Choose a valid stage.")
    if not d["owner_id"]:
        errors.append("Owner is required.")
    if not d["expected_close_date"]:
        errors.append("Expected close date is required.")
    elif check_close_date and d["stage"] in OPEN_STAGES and str(d["expected_close_date"]) < as_of:
        errors.append("Expected close date cannot be in the past for an open opportunity.")
    return errors


def get(engine: Engine, opp_id: int) -> dict | None:
    return db.query_one(engine, "SELECT * FROM opportunities WHERE opportunity_id = :id", {"id": opp_id})


def create(engine: Engine, user: str, data: dict) -> int:
    as_of = db.as_of(engine)
    data = {"stage": "Identified", **data}
    errors = validate(data, as_of)
    if errors:
        raise ValueError(" ".join(errors))
    d = _clean(data)
    if d["stage"] == "Closed Won":
        d["probability"] = 1.0
    elif d["stage"] == "Closed Lost":
        d["probability"] = 0.0
    with engine.begin() as conn:
        oid = db.insert_returning_id(
            conn,
            """INSERT INTO opportunities (customer_id, product_id, description, potential_arr_pence, probability, stage,
               expected_close_date, owner_id, next_action, qualification, created_date, closed_date)
               VALUES (:customer_id, :product_id, :description, :potential_arr_pence, :probability, :stage,
               :expected_close_date, :owner_id, :next_action, :qualification, :created, :closed) RETURNING opportunity_id""",
            {**d, "created": as_of, "closed": as_of if d["stage"] in CLOSED_STAGES else None})
        db.execute(conn, """INSERT INTO opportunity_stage_history (opportunity_id, from_stage, to_stage, changed_on, changed_by)
                            VALUES (:o, NULL, :s, :d, :u)""", {"o": oid, "s": d["stage"], "d": as_of, "u": user})
        audit.log(conn, user, "opportunity", oid, "create", f"Opportunity created: {d['description']}", d["customer_id"],
                  changes={k: [None, v] for k, v in d.items() if v is not None})
    return oid


def update(engine: Engine, user: str, opp_id: int, data: dict) -> None:
    old = get(engine, opp_id)
    if not old:
        raise ValueError("Opportunity not found.")
    as_of = db.as_of(engine)
    merged = {**{k: old[k] for k in FIELDS}, **data}
    # only enforce the close-date rule when the user touches it or (re)opens a deal
    check_close = "expected_close_date" in data or (data.get("stage") in OPEN_STAGES and old["stage"] in CLOSED_STAGES)
    errors = validate(merged, as_of, check_close_date=check_close)
    if errors:
        raise ValueError(" ".join(errors))
    d = _clean(merged)
    stage_changed = d["stage"] != old["stage"]
    closed_date = old["closed_date"]
    if stage_changed:
        if d["stage"] == "Closed Won":
            d["probability"], closed_date = 1.0, as_of
        elif d["stage"] == "Closed Lost":
            d["probability"], closed_date = 0.0, as_of
        else:
            closed_date = None
    changes = audit.diff({k: old[k] for k in FIELDS}, d)
    if not changes:
        return
    with engine.begin() as conn:
        db.execute(conn, """UPDATE opportunities SET customer_id=:customer_id, product_id=:product_id,
                            description=:description, potential_arr_pence=:potential_arr_pence, probability=:probability,
                            stage=:stage, expected_close_date=:expected_close_date, owner_id=:owner_id,
                            next_action=:next_action, qualification=:qualification, closed_date=:closed
                            WHERE opportunity_id=:id""", {**d, "closed": closed_date, "id": opp_id})
        if stage_changed:
            db.execute(conn, """INSERT INTO opportunity_stage_history (opportunity_id, from_stage, to_stage, changed_on,
                                changed_by) VALUES (:o, :f, :t, :d, :u)""",
                       {"o": opp_id, "f": old["stage"], "t": d["stage"], "d": as_of, "u": user})
        summary = (f"Opportunity moved {old['stage']} → {d['stage']}: {d['description']}" if stage_changed
                   else f"Opportunity updated: {d['description']}")
        audit.log(conn, user, "opportunity", opp_id, "update", summary, d["customer_id"], changes=changes)


def move_stage(engine: Engine, user: str, opp_id: int, stage: str) -> None:
    update(engine, user, opp_id, {"stage": stage})


def delete(engine: Engine, user: str, opp_id: int) -> None:
    old = get(engine, opp_id)
    if not old:
        raise ValueError("Opportunity not found.")
    with engine.begin() as conn:
        db.execute(conn, "DELETE FROM opportunity_stage_history WHERE opportunity_id = :id", {"id": opp_id})
        db.execute(conn, "DELETE FROM opportunities WHERE opportunity_id = :id", {"id": opp_id})
        audit.log(conn, user, "opportunity", opp_id, "delete", f"Opportunity deleted: {old['description']}",
                  old["customer_id"], changes={k: [old[k], None] for k in FIELDS})


def pipeline(engine: Engine) -> pd.DataFrame:
    return db.query_df(engine, "SELECT * FROM v_pipeline ORDER BY is_open DESC, expected_value_pence DESC")


def totals(engine: Engine) -> dict:
    return db.query_one(engine, db.load_query(engine, "pipeline_totals"))


def booked_acv(engine: Engine, start: str, end: str) -> int:
    return int(db.scalar(engine, """SELECT COALESCE(SUM(potential_arr_pence), 0) FROM opportunities
                                    WHERE stage = 'Closed Won' AND closed_date BETWEEN :s AND :e""",
                         {"s": start, "e": end}) or 0)


def stage_history(engine: Engine, opp_id: int) -> pd.DataFrame:
    return db.query_df(engine, """SELECT changed_on, from_stage, to_stage, changed_by FROM opportunity_stage_history
                                  WHERE opportunity_id = :id ORDER BY history_id""", {"id": opp_id})
