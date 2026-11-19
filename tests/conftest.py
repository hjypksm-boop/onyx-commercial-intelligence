import shutil

import pytest
from streamlit.testing.v1 import AppTest

from services import config, db, seed

AS_OF = "2026-11-18"


@pytest.fixture(scope="session")
def baseline_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("baseline") / "baseline.db"
    seed.build_sqlite_file(path, AS_OF)
    return path


@pytest.fixture()
def engine(baseline_file, tmp_path):
    """A fresh, writable copy of the seeded baseline for each test."""
    path = tmp_path / "work.db"
    shutil.copyfile(baseline_file, path)
    eng = db.get_engine(config.sqlite_url(path))
    yield eng
    eng.dispose()


USER = "cs.exec@demo.local"


APP = str(config.ROOT / "app.py")


@pytest.fixture()
def app_env(baseline_file, tmp_path, monkeypatch):
    live = tmp_path / "live.db"
    shutil.copyfile(baseline_file, live)
    monkeypatch.setenv("DATABASE_URL", config.sqlite_url(live))
    monkeypatch.setenv("AS_OF_DATE", AS_OF)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(config, "BASELINE_DB_PATH", tmp_path / "baseline.db")
    monkeypatch.setattr(config, "SCENARIO_DIR", tmp_path / "scenarios")
    shutil.copyfile(baseline_file, config.BASELINE_DB_PATH)
    return live


def _login(at: AppTest) -> AppTest:
    at.session_state["user"] = {"user_id": 1, "email": "cs.exec@demo.local", "display_name": "Alex Morgan",
                                "role": "CS_EXEC", "owner_id": 1, "role_label": "Customer Success Executive"}
    return at
