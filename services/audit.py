"""Audit trail: every create/update/delete records who/what/when/old→new."""
from __future__ import annotations

import json
from datetime import datetime

from services.db import execute


def now_ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def diff(old: dict | None, new: dict) -> dict:
    old = old or {}
    out = {}
    for k, v in new.items():
        ov = old.get(k)
        if str(ov) != str(v):
            out[k] = [ov, v]
    return out


def log(conn, user_email: str, entity: str, entity_id: int | None, action: str, summary: str,
        customer_id: int | None = None, counterparty_id: int | None = None, changes: dict | None = None) -> None:
    execute(
        conn,
        """INSERT INTO audit_log (ts, user_email, entity, entity_id, action, customer_id, counterparty_id, summary, changes_json)
           VALUES (:ts, :u, :e, :eid, :a, :cid, :cpid, :s, :c)""",
        {"ts": now_ts(), "u": user_email, "e": entity, "eid": entity_id, "a": action, "cid": customer_id,
         "cpid": counterparty_id, "s": summary, "c": json.dumps(changes, default=str) if changes else None},
    )
