"""App imports and every page renders without exceptions (Streamlit AppTest), in live mode and a scenario."""
import pytest
from streamlit.testing.v1 import AppTest

from components.context import PAGES
from services import config

from .conftest import APP, _login  # noqa: F401


def test_login_page_renders(app_env):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Demo credentials" in m.value for m in at.markdown)


def test_login_flow(app_env):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[1].input("Demo123!")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["user"]["role"] == "CS_EXEC"


@pytest.mark.parametrize("key", list(PAGES))
def test_page_renders(app_env, key):
    at = _login(AppTest.from_file(APP, default_timeout=90))
    at.run()
    at.switch_page(PAGES[key][0]).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("key", ["overview", "c360", "close"])
def test_page_renders_in_scenario(app_env, key):
    at = _login(AppTest.from_file(APP, default_timeout=90))
    at.session_state["demo_mode"] = "C"
    at.run()
    at.switch_page(PAGES[key][0]).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("name", ["Gulf Marine Fuels", "Northstar Energy Trading", "Harbour Refining"])
def test_customer_360_variants(app_env, name, baseline_file):
    from services import db
    eng = db.get_engine(config.sqlite_url(baseline_file))
    cid = db.scalar(eng, "SELECT customer_id FROM customers WHERE name = :n", {"n": name})
    at = _login(AppTest.from_file(APP, default_timeout=90))
    at.session_state["c360_select"] = f"c:{cid}"
    at.run()
    at.switch_page(PAGES["c360"][0]).run()
    assert not at.exception, [e.value for e in at.exception]
    if name == "Gulf Marine Fuels":
        assert any("Active users declined 60% from June to November (10 → 4)" in m.value for m in at.markdown)


def test_counterparty_360(app_env):
    at = _login(AppTest.from_file(APP, default_timeout=90))
    at.session_state["c360_select"] = "p:1"
    at.run()
    at.switch_page(PAGES["c360"][0]).run()
    assert not at.exception, [e.value for e in at.exception]


def test_director_read_only(app_env):
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["user"] = {"user_id": 2, "email": "director@demo.local", "display_name": "Dana Whitfield",
                                "role": "DIRECTOR", "owner_id": 2, "role_label": "Commercial Director"}
    at.run()
    for key in ("c360", "tasks", "growth"):
        at.switch_page(PAGES[key][0]).run()
        assert not at.exception, (key, [e.value for e in at.exception])
