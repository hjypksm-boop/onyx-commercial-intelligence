"""Local login with bcrypt-hashed passwords."""
from __future__ import annotations

import bcrypt
from sqlalchemy.engine import Engine

from services import db

ROLE_LABEL = {"CS_EXEC": "Customer Success Executive", "DIRECTOR": "Commercial Director"}
DEMO_CREDENTIALS = [("cs.exec@demo.local", "Demo123!", "Customer Success Executive — full edit rights"),
                    ("director@demo.local", "Demo123!", "Commercial Director — read, reports, approve")]


def authenticate(engine: Engine, email: str, password: str) -> dict | None:
    row = db.query_one(engine, """SELECT u.user_id, u.email, u.password_hash, u.display_name, u.role, u.owner_id
                                  FROM users u WHERE lower(u.email) = lower(:e)""", {"e": (email or "").strip()})
    if not row or not password:
        return None
    try:
        ok = bcrypt.checkpw(password.encode(), row["password_hash"].encode())
    except ValueError:
        return None
    if not ok:
        return None
    row.pop("password_hash")
    row["role_label"] = ROLE_LABEL[row["role"]]
    return row


def can_edit(user: dict | None) -> bool:
    """CS Executive: full edit. Director: read + reports + approve (reports/approvals checked separately)."""
    return bool(user) and user["role"] == "CS_EXEC"


def can_approve(user: dict | None) -> bool:
    return bool(user) and user["role"] == "DIRECTOR"
