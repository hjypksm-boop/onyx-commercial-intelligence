# ONYX | Commercial Intelligence

An internal customer-success and revenue-operations platform for a **fictional** portfolio of energy-trading and
market-intelligence customers. Built with Python, Streamlit, raw SQL (SQLAlchemy Core) and a Groq-hosted LLM (configurable).

> **Demonstration environment — all customers, values and activity are synthetic. Not connected to any Onyx Capital
> Group system.**

## Setup (VS Code)

```bash
python3 -m venv .venv                    # Python 3.11+
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                     # optionally add GROQ_API_KEY
make seed                                # builds data/baseline.db and data/onyx.db
make run                                 # streamlit run app.py
```

Open http://localhost:8501 and sign in with a demo account (also shown on the login screen):

| Email | Password | Role |
|---|---|---|
| `cs.exec@demo.local` | `Demo123!` | Customer Success Executive — full edit rights |
| `director@demo.local` | `Demo123!` | Commercial Director — read, reports, approve |

If you skip `make seed`, the app seeds itself on first launch.

## Commands

| Command | What it does |
|---|---|
| `make setup` | create `.venv`, install requirements, copy `.env.example` |
| `make seed` / `make reset` | rebuild the baseline from the deterministic seed, replace the live workspace, delete scenario sandboxes |
| `make run` | start the app |
| `make test` | run the pytest suite (acceptance values, workflows, page smoke tests, UI click-through) |
| `make lint` | ruff |

## Configuration (`.env`)

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | empty → `data/onyx.db` (SQLite) | PostgreSQL / Supabase: `postgresql+psycopg://user:pass@host:5432/db` |
| `GROQ_API_KEY` | empty | Without a key every AI feature uses a labelled template fallback |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Resolved in one place: `services/config.py`. Groq no longer serves Llama chat models to new keys (checked Nov 2026); set any Groq chat model here |
| `AS_OF_DATE` | seed date | The "demo clock". All renewal countdowns, health and reports are evaluated at this date |

The workspace date is fixed when the database is seeded, so the demo is reproducible. Run `make seed` to move it to today.

## What's inside

- **10 pages**: Executive Overview (the three commercial questions, KPI cards with *Show SQL*, Ask the portfolio),
  Customer Portfolio, Customer 360 (subscription and counterparty layouts, action dialogs), Product Analytics,
  Customer Health & Retention (GRR/NRR, guided 6-step recovery workflow), Growth Opportunities (kanban + table),
  Value Review Builder (PDF / print HTML), Commercial Close Report (PDF / CSV), Tasks & Follow-ups, Settings.
- **Calculated health score**: five configurable weighted components, re-normalised when data is missing, fully
  explained per customer. See `services/health.py`.
- **Demo Mode**: Scenario A/B/C run on SQLite sandbox copies of `data/baseline.db`, with guided steps and reset.
- **AI copilot (Groq / Llama)**: meeting briefs, value-review summaries, close-report commentary, root-cause
  hypotheses (always saved as *Hypothesis*), follow-up emails and natural-language → validated read-only SQL.

See `docs/` for the build plan, data dictionary, 5-minute demo script and known limitations.

## Acceptance values (baseline, default weights)

ARR £270,000 · adoption 50/71 = 70.4% · revenue at risk £96,000 (Gulf Marine Fuels, Meridian Commodities) ·
potential expansion £62,000 · weighted pipeline £30,200 · Gulf Marine MAU 10 → 4 (−60%). All are computed by SQL over
stored records and checked by `tests/test_acceptance.py`.
