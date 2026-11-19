"""Central configuration. Values are read from the environment at call time so tests can override them."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SQL_DIR = ROOT / "sql"
DATA_DIR = ROOT / "data"
SCENARIO_DIR = DATA_DIR / "scenarios"
LIVE_DB_PATH = DATA_DIR / "onyx.db"
BASELINE_DB_PATH = DATA_DIR / "baseline.db"

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

DISCLAIMER = (
    "Demonstration environment — all customers, values and activity are synthetic. "
    "Not connected to any Onyx Capital Group system."
)


def sqlite_url(path: Path | str) -> str:
    return f"sqlite:///{Path(path).resolve()}"


def database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    return url or sqlite_url(LIVE_DB_PATH)


def groq_api_key() -> str | None:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    return key or None


def groq_model() -> str:
    """The single place the Groq model name is resolved."""
    return (os.getenv("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL


def as_of_override() -> str | None:
    val = (os.getenv("AS_OF_DATE") or "").strip()
    return val or None
