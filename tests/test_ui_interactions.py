"""Click-through tests: buttons, forms and dialogs persist to the database and views update."""
from streamlit.testing.v1 import AppTest

from components.context import PAGES
from services import config, db

from .conftest import APP, _login


def _open(page: str, **state) -> AppTest:
    at = _login(AppTest.from_file(APP, default_timeout=120))
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    at.switch_page(PAGES[page][0]).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _eng(live):
    return db.get_engine(config.sqlite_url(live))


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def test_overview_kpis_and_ask_example(app_env):
    at = _open("overview")
    html = " ".join(m.value for m in at.markdown)
    for v in ("£270,000", "70.4%", "£96,000", "£62,000"):
        assert v in html, v
    at.selectbox(key="ask_ex").select("Total ARR by vertical").run()
    _btn(at, "Run").click().run()
    assert not at.exception
    assert any(df.value.shape[0] == 3 for df in at.dataframe)


def test_filters_change_kpis(app_env):
    at = _open("overview", f_verticals=["Flux Bunkers"])
    html = " ".join(m.value for m in at.markdown)
    assert "£84,000" in html  # Atlantic 48k + Gulf 36k
    assert "£36,000" in html  # revenue at risk: Gulf only


def test_task_done_button(app_env):
    eng = _eng(app_env)
    tid = db.scalar(eng, "SELECT task_id FROM tasks WHERE title = 'Send Atlantic QBR recap'")
    at = _open("tasks")
    at.button(key=f"done_{tid}").click().run()
    assert not at.exception
    assert db.scalar(eng, "SELECT status FROM tasks WHERE task_id = :t", {"t": tid}) == "Done"
    assert db.scalar(eng, "SELECT COUNT(*) FROM audit_log WHERE entity='task' AND entity_id=:t", {"t": tid}) == 1


def test_task_dialog_opens(app_env):
    """AppTest does not emulate a dialog's fragment rerun on submit; persistence is covered in test_workflows."""
    at = _open("tasks")
    _btn(at, "New task").click().run()
    assert not at.exception
    assert [t.label for t in at.text_input] == ["Title *"]
    assert any(b.key == "FormSubmitter:task_form-Save task" for b in at.button)


def test_move_opportunity_stage(app_env):
    eng = _eng(app_env)
    oid = db.scalar(eng, "SELECT opportunity_id FROM opportunities WHERE description = 'Additional market reports'")
    at = _open("growth")
    at.selectbox(key=f"mv_{oid}").select("Qualified").run()
    assert not at.exception
    assert db.scalar(eng, "SELECT stage FROM opportunities WHERE opportunity_id = :o", {"o": oid}) == "Qualified"


def test_weights_validation_blocks_save(app_env):
    at = _open("settings")
    at.number_input(key="w_sentiment").set_value(10).run()
    assert any("must total exactly 100%" in e.value for e in at.error)
    assert _btn(at, "Save weights & recalculate").disabled


def test_save_weights_recalculates(app_env):
    eng = _eng(app_env)
    at = _open("settings")
    at.number_input(key="w_adoption").set_value(40).run()
    at.number_input(key="w_usage_trend").set_value(15).run()
    _btn(at, "Save weights & recalculate").click().run()
    assert not at.exception
    assert db.scalar(eng, "SELECT adoption FROM health_weights ORDER BY weights_id DESC LIMIT 1") == 40


def test_retention_open_plan(app_env):
    eng = _eng(app_env)
    at = _open("retention")
    _btn(at, "Open recovery plan").click().run()
    assert not at.exception
    assert db.scalar(eng, "SELECT COUNT(*) FROM recovery_plans") == 1


def test_close_report_scenario_c(app_env):
    at = _open("close", demo_mode="C")
    html = " ".join(m.value for m in at.markdown)
    assert "£75,000" in html and "£96,000" in html
    _btn(at, "Save version").click().run()
    assert not at.exception
    # live workspace untouched by the scenario
    assert db.scalar(_eng(app_env), "SELECT COUNT(*) FROM close_reports") == 0


def test_value_review_generates_and_saves(app_env, baseline_file):
    eng = _eng(app_env)
    gid = db.scalar(eng, "SELECT customer_id FROM customers WHERE name = 'Gulf Marine Fuels'")
    at = _open("value_review", vr_customer=gid)
    assert any("Gulf Marine Fuels" in t.value for t in at.text_area)
    _btn(at, "Draft summary with AI").click().run()
    assert any("AI unavailable — template draft" in m.value for m in at.markdown)
    _btn(at, "Save version").click().run()
    assert db.scalar(eng, "SELECT COUNT(*) FROM value_reviews WHERE customer_id = :c", {"c": gid}) == 1
