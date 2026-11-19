"""CRUD round-trips, validation, sandbox isolation, reset, SQL guard."""
import shutil

import pytest

from services import (
    audit,
    config,
    customers,
    db,
    demo_mode,
    kpis,
    opportunities,
    reports,
    retention,
    seed,
    sqlguard,
    tasks,
    value_review,
)

from .conftest import USER


def _cid(engine, name):
    return db.scalar(engine, "SELECT customer_id FROM customers WHERE name = :n", {"n": name})


def test_task_crud_round_trip(engine):
    as_of = db.as_of(engine)
    tid = tasks.create(engine, USER, {"title": "Call Gulf", "customer_id": _cid(engine, "Gulf Marine Fuels"),
                                      "category": "Renewal preparation", "priority": "High", "owner_id": 1,
                                      "due_date": as_of, "status": "Open"})
    t = tasks.get(engine, tid)
    assert t["title"] == "Call Gulf"
    tasks.update(engine, USER, tid, {"owner_id": 3, "title": "Call Gulf ops"})
    assert tasks.get(engine, tid)["owner_id"] == 3
    tasks.complete(engine, USER, [tid])
    t = tasks.get(engine, tid)
    assert t["status"] == "Done" and t["completed_on"] == as_of
    tasks.delete(engine, USER, tid)
    assert tasks.get(engine, tid) is None
    actions = db.query_df(engine, "SELECT action FROM audit_log WHERE entity = 'task' AND entity_id = :i", {"i": tid})
    assert list(actions["action"]) == ["create", "update", "update", "delete"]


def test_task_validation(engine):
    with pytest.raises(ValueError, match="Title is required"):
        tasks.create(engine, USER, {"title": "", "category": "Onboarding", "priority": "Low", "owner_id": 1,
                                    "due_date": "2026-12-01"})
    with pytest.raises(ValueError, match="Owner is required"):
        tasks.create(engine, USER, {"title": "x", "category": "Onboarding", "priority": "Low", "owner_id": None,
                                    "due_date": "2026-12-01"})


def test_opportunity_crud_round_trip(engine):
    cid = _cid(engine, "Summit Energy Research")
    oid = opportunities.create(engine, USER, {"customer_id": cid, "product_id": "OFF", "description": "API feed",
                                              "potential_arr_pence": 5_000_00, "probability": 0.5, "stage": "Identified",
                                              "expected_close_date": "2027-01-31", "owner_id": 3})
    assert opportunities.totals(engine)["potential_expansion_pence"] == 67_000_00
    opportunities.update(engine, USER, oid, {"probability": 0.8, "next_action": "Send pricing"})
    o = opportunities.get(engine, oid)
    assert float(o["probability"]) == 0.8 and o["next_action"] == "Send pricing"
    opportunities.move_stage(engine, USER, oid, "Qualified")
    assert len(opportunities.stage_history(engine, oid)) == 2
    opportunities.delete(engine, USER, oid)
    assert opportunities.get(engine, oid) is None
    assert opportunities.totals(engine)["potential_expansion_pence"] == 62_000_00


def test_opportunity_validation(engine):
    cid = _cid(engine, "Summit Energy Research")
    base = {"customer_id": cid, "product_id": "OFF", "description": "x", "potential_arr_pence": 100,
            "probability": 0.5, "stage": "Identified", "expected_close_date": "2027-01-31", "owner_id": 3}
    for bad, msg in [({"potential_arr_pence": 0}, "greater than"), ({"probability": 1.2}, "between 0% and 100%"),
                     ({"expected_close_date": "2020-01-01"}, "past"), ({"owner_id": None}, "Owner")]:
        with pytest.raises(ValueError, match=msg):
            opportunities.create(engine, USER, {**base, **bad})


def test_meeting_updates_health_and_creates_tasks(engine):
    gid = _cid(engine, "Gulf Marine Fuels")
    before = db.query_one(engine, "SELECT days_since_contact FROM v_health_inputs WHERE customer_id = :c", {"c": gid})
    aid = customers.log_activity(engine, USER, activity_type="Meeting", activity_date=db.as_of(engine),
                                 subject="Recovery call", attendees="Aisha Rahman", sentiment=3, customer_id=gid,
                                 follow_up_tasks=[{"title": "Send training plan", "category": "Onboarding",
                                                   "priority": "High", "owner_id": 1, "due_date": "2026-11-25"}])
    assert aid
    after = db.query_one(engine, "SELECT days_since_contact FROM v_health_inputs WHERE customer_id = :c", {"c": gid})
    assert before["days_since_contact"] == 21 and after["days_since_contact"] == 0
    assert db.scalar(engine, "SELECT COUNT(*) FROM tasks WHERE source = :s", {"s": f"Meeting #{aid}"}) == 1


def test_active_cannot_exceed_licensed(engine):
    with pytest.raises(ValueError, match="cannot exceed"):
        customers.update_account(engine, USER, 1, licensed_seats=5, active_users=6, owner_id=1)


def test_escalation_creates_ticket_and_activity(engine):
    gid = _cid(engine, "Gulf Marine Fuels")
    tid = customers.log_escalation(engine, USER, gid, reason="CFO raised concerns", subject="Exec escalation",
                                   severity="Critical")
    t = db.query_one(engine, "SELECT * FROM support_tickets WHERE ticket_id = :t", {"t": tid})
    assert t["escalated"] == 1 and t["severity"] == "Critical"
    assert db.scalar(engine, "SELECT COUNT(*) FROM activities WHERE customer_id = :c AND activity_type = 'Escalation'",
                     {"c": gid}) == 1


def test_hypotheses_and_confirmation(engine):
    gid = _cid(engine, "Gulf Marine Fuels")
    hid = retention.add_hypothesis(engine, USER, gid, "Champion left", "Champion change", source="AI")
    h = retention.list_hypotheses(engine, gid)
    assert h.iloc[0]["status"] == "Hypothesis" and h.iloc[0]["source"] == "AI"
    with pytest.raises(ValueError):
        retention.confirm_hypothesis(engine, USER, hid, None, "evidence")
    act = db.scalar(engine, "SELECT MAX(activity_id) FROM activities WHERE customer_id = :c AND activity_type='Meeting'",
                    {"c": gid})
    retention.confirm_hypothesis(engine, USER, hid, act, "Confirmed by Aisha in meeting")
    assert retention.list_hypotheses(engine, gid).iloc[0]["status"] == "Confirmed"
    assert len(retention.evidence(engine, gid)) >= 5


def test_recovery_plan_flow(engine):
    gid = _cid(engine, "Gulf Marine Fuels")
    retention.ensure_plan(engine, USER, gid, 1)
    retention.update_plan(engine, USER, gid, status="Investigating", current_step=2, note_step=1, note="Reviewed")
    p = retention.get_plan(engine, gid)
    assert p["started_on"] == db.as_of(engine) and p["baseline_mau"] == 4 and p["step_notes"]["1"] == "Reviewed"
    with pytest.raises(ValueError, match="churn reason"):
        retention.update_plan(engine, USER, gid, outcome="Churned", status="Churned")


def test_retention_metrics(engine):
    m = retention.retention_metrics(engine)
    assert m["start_arr_pence"] == 254_000_00
    assert round(m["nrr"], 1) == round(270_000 / 254_000 * 100, 1)
    assert round(m["grr"], 1) == round(248_000 / 254_000 * 100, 1)


def test_close_report_baseline(engine):
    r = reports.compute(engine, db.as_of(engine))
    m = r["metrics"]
    assert m["meetings_completed"] == 8
    assert m["accounts_at_risk"] == 2
    assert m["revenue_at_risk_pence"] == 96_000_00
    assert m["new_opportunities"] == 0
    assert m["booked_acv_pence"] == 0
    csv = reports.to_csv(r).decode()
    assert "meetings_completed,8" in csv
    rid = reports.save(engine, USER, db.as_of(engine), m, reports.default_commentary(r))
    reports.approve(engine, "director@demo.local", rid)
    assert reports.versions(engine, db.as_of(engine)).iloc[0]["status"] == "Approved"


def test_value_review(engine):
    gid = _cid(engine, "Gulf Marine Fuels")
    f = value_review.facts(engine, gid, "2026-06-01", "2026-11-18")
    s = value_review.default_sections(f)
    assert "£36,000" in s["summary"] and "10 to 4" in s["summary"]
    rid = value_review.save(engine, USER, gid, "2026-06-01", "2026-11-18", s)
    assert rid and len(value_review.versions(engine, gid)) == 1


def test_scenario_sandbox_isolation_and_reset(tmp_path, monkeypatch, baseline_file):
    monkeypatch.setattr(config, "BASELINE_DB_PATH", tmp_path / "baseline.db")
    monkeypatch.setattr(config, "SCENARIO_DIR", tmp_path / "scenarios")
    shutil.copyfile(baseline_file, config.BASELINE_DB_PATH)
    base_eng = db.get_engine(config.sqlite_url(config.BASELINE_DB_PATH))
    base_tasks = db.scalar(base_eng, "SELECT COUNT(*) FROM tasks")

    eng_a = db.get_engine(demo_mode.db_url("A"))
    tasks.create(eng_a, USER, {"title": "Sandbox only", "category": "Onboarding", "priority": "Low", "owner_id": 1,
                               "due_date": "2026-12-01"})
    assert db.scalar(eng_a, "SELECT COUNT(*) FROM tasks") == base_tasks + 1
    assert db.scalar(base_eng, "SELECT COUNT(*) FROM tasks") == base_tasks

    # Scenario C example day lives only in its sandbox
    eng_c = db.get_engine(demo_mode.db_url("C"))
    m = reports.compute(eng_c, db.as_of(eng_c))["metrics"]
    assert m["meetings_completed"] == 8 and m["new_opportunities"] == 3
    assert m["new_opportunities_potential_pence"] == 75_000_00 and m["accounts_at_risk"] == 2
    assert kpis.portfolio_kpis(base_eng)["potential_expansion_pence"] == 62_000_00

    demo_mode.reset_sandbox("A")
    eng_a = db.get_engine(demo_mode.db_url("A"))
    assert db.scalar(eng_a, "SELECT COUNT(*) FROM tasks") == base_tasks


def test_reset_restores_acceptance_values(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASELINE_DB_PATH", tmp_path / "baseline.db")
    monkeypatch.setattr(config, "SCENARIO_DIR", tmp_path / "scenarios")
    live = tmp_path / "live.db"
    monkeypatch.setenv("DATABASE_URL", config.sqlite_url(live))
    seed.reset_live("2026-11-18")
    eng = db.get_engine(config.database_url())
    oid = db.scalar(eng, "SELECT opportunity_id FROM opportunities WHERE description = 'Houston port expansion'")
    opportunities.move_stage(eng, USER, oid, "Closed Lost")
    assert kpis.portfolio_kpis(eng)["potential_expansion_pence"] == 44_000_00
    seed.reset_live("2026-11-18")
    eng = db.get_engine(config.database_url())
    k = kpis.portfolio_kpis(eng)
    assert (k["arr_pence"], k["licensed_seats"], k["active_users"], k["revenue_at_risk_pence"],
            k["potential_expansion_pence"]) == (270_000_00, 71, 50, 96_000_00, 62_000_00)


@pytest.mark.parametrize("sql", [
    "INSERT INTO tasks (title) VALUES ('x')",
    "UPDATE tasks SET status = 'Done'",
    "DELETE FROM tasks",
    "DROP TABLE tasks",
    "SELECT * FROM v_customer_kpis; DROP TABLE tasks",
    "SELECT 1; SELECT 2",
    "SELECT * FROM users",
    "SELECT * FROM audit_log",
    "SELECT * FROM sqlite_master",
    "WITH x AS (SELECT 1) DELETE FROM tasks",
    "PRAGMA table_info(tasks)",
    "SELECT * FROM v_customer_kpis, users",
    "ATTACH DATABASE 'x.db' AS x",
])
def test_sql_guard_rejects(sql):
    ok, _, err = sqlguard.validate(sql)
    assert not ok, sql
    assert err


def test_sql_guard_accepts_and_runs(engine):
    for q in sqlguard.EXAMPLES.values():
        ok, _, err = sqlguard.validate(q)
        assert ok, err
    df = sqlguard.run_readonly(engine, sqlguard.EXAMPLES["Total ARR by vertical"])
    assert df["arr_gbp"].sum() == 270_000
    # strings containing forbidden words are fine
    assert sqlguard.validate("SELECT customer_name FROM v_customer_kpis WHERE customer_name <> 'drop table'")[0]


def test_audit_diff():
    assert audit.diff({"a": 1, "b": 2}, {"a": 1, "b": 3}) == {"b": [2, 3]}
