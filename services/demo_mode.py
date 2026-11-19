"""Demo Mode: scenario sandboxes are SQLite copies of baseline.db — they never touch the baseline or live workspace."""
from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

from services import audit, config, db, health, seed

MODES = {
    "live": "Live workspace",
    "A": "Scenario A — Customer at risk",
    "B": "Scenario B — Expansion opportunity",
    "C": "Scenario C — Executive reporting",
}

# Each step: (title, narration, page key, focus customer name or None)
SCENARIOS = {
    "A": {
        "title": "Customer at risk — Gulf Marine Fuels",
        "intro": "Gulf Marine Fuels' active users have fallen steeply and the contract renews in 30 days.",
        "steps": [
            ("Spot the account", "Open the Executive Overview — Gulf Marine tops 'Accounts requiring immediate attention'.",
             "overview", None),
            ("Review usage", "In Customer 360 the MAU chart shows the June → November decline and the computed warning.",
             "c360", "Gulf Marine Fuels"),
            ("Review support history", "Open the Support tab: an escalated High ticket breached SLA.", "c360",
             "Gulf Marine Fuels"),
            ("Log hypotheses", "In Health & Retention, review evidence and log root causes as Hypotheses (not facts).",
             "retention", "Gulf Marine Fuels"),
            ("Create a recovery task", "Agree recovery actions — this creates owned, dated tasks.", "retention",
             "Gulf Marine Fuels"),
            ("Prepare the conversation", "Generate an AI meeting brief / talking points from Customer 360 → Actions.",
             "c360", "Gulf Marine Fuels"),
        ],
    },
    "B": {
        "title": "Expansion opportunity — Northstar Energy Trading",
        "intro": "Northstar runs 85% seat adoption with deep analytics and API usage and a new gas desk is launching.",
        "steps": [
            ("Show the usage evidence", "Customer 360 → Usage: seat utilisation near capacity and rising MAU.", "c360",
             "Northstar Energy Trading"),
            ("Feature depth", "Product Analytics → Flux Analytics: Northstar has adopted every feature.", "analytics", None),
            ("Qualify", "Growth Opportunities: complete the qualification checklist (need, budget, timing, decision maker).",
             "growth", "Northstar Energy Trading"),
            ("Progress the deal", "Move 'Additional analytics seats' through stages; every move is logged.", "growth",
             "Northstar Energy Trading"),
        ],
    },
    "C": {
        "title": "Executive reporting — end-of-day summary",
        "intro": "The Commercial Director requests today's summary: 8 meetings, 3 new opportunities (£75,000 potential), "
                 "2 accounts at risk.",
        "steps": [
            ("Open the Close Report", "The report auto-compiles from today's records.", "close", None),
            ("Review activity & pipeline", "Check meetings, new opportunities (potential, not booked) and risks.", "close",
             None),
            ("Edit commentary", "Draft commentary (AI or template) and edit each section.", "close", None),
            ("Export", "Save the version and export PDF / CSV.", "close", None),
        ],
    },
}


def scenario_path(mode: str) -> Path:
    return config.SCENARIO_DIR / f"scenario_{mode.lower()}.db"


def db_url(mode: str) -> str:
    if mode == "live":
        return config.database_url()
    path = scenario_path(mode)
    if not path.exists():
        create_sandbox(mode)
    return config.sqlite_url(path)


def create_sandbox(mode: str) -> Path:
    if mode not in SCENARIOS:
        raise ValueError(f"Unknown scenario {mode}")
    if not config.BASELINE_DB_PATH.exists():
        seed.build_sqlite_file(config.BASELINE_DB_PATH)
    path = scenario_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    url = config.sqlite_url(path)
    db.dispose(url)
    shutil.copyfile(config.BASELINE_DB_PATH, path)
    if mode == "C":
        apply_scenario_c(db.get_engine(url))
    return path


def reset_sandbox(mode: str) -> Path:
    path = scenario_path(mode)
    url = config.sqlite_url(path)
    db.dispose(url)
    if path.exists():
        path.unlink()
    return create_sandbox(mode)


def apply_scenario_c(engine) -> None:
    """The example day for the executive report: 3 new opportunities worth £75,000 identified today."""
    as_of = db.as_of(engine)
    ids = {r["name"]: r["customer_id"] for r in db.query_df(engine, "SELECT customer_id, name FROM customers")
           .to_dict("records")}
    close = (date.fromisoformat(as_of) + timedelta(days=60)).isoformat()
    user = "scenario-c@demo.local"
    with engine.begin() as conn:
        for cust, pid, desc, pounds, prob, owner in [
            ("Atlantic Bunker Co.", "FB", "Fujairah & Singapore port coverage", 30000, 0.3, 1),
            ("Northstar Energy Trading", "FA", "Gas desk analytics package", 25000, 0.4, 3),
            ("Harbour Refining", "OFF", "Regional benchmark report bundle", 20000, 0.25, 1),
        ]:
            oid = db.insert_returning_id(conn, """INSERT INTO opportunities (customer_id, product_id, description,
                    potential_arr_pence, probability, stage, expected_close_date, owner_id, next_action, created_date)
                    VALUES (:c, :p, :d, :v, :pr, 'Identified', :cl, :o, 'Qualify need and budget', :cr)
                    RETURNING opportunity_id""",
                                         {"c": ids[cust], "p": pid, "d": desc, "v": pounds * 100, "pr": prob, "cl": close,
                                          "o": owner, "cr": as_of})
            db.execute(conn, """INSERT INTO opportunity_stage_history (opportunity_id, from_stage, to_stage, changed_on,
                                changed_by) VALUES (:o, NULL, 'Identified', :d, :u)""", {"o": oid, "d": as_of, "u": user})
        audit.log(conn, user, "database", None, "create", "Scenario C example day applied")
    health.refresh_snapshots(engine)
