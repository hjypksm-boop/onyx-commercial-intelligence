# CLAUDE.md — ONYX | Commercial Intelligence

Synthetic-data demo of a customer-success / revenue-ops platform. Streamlit UI, raw parameterised SQL via SQLAlchemy
Core, SQLite by default (PostgreSQL via `DATABASE_URL`), Groq/Llama AI with template fallbacks.

## Commands
- `make seed` — rebuild `data/baseline.db` + live `data/onyx.db` (deterministic, `RNG_SEED` in `services/seed.py`)
- `make run` — `streamlit run app.py`
- `make test` — pytest (≈70 tests, ~10 s). `make lint` — ruff.
- Headless check: `.venv/bin/streamlit run app.py --server.headless true`

## Architecture
- `app.py` — page config, CSS, bootstrap seed, login gate, `st.navigation`, sidebar, banner.
- `pages/NN_*.py` — one script per page (keys/paths in `components/context.py::PAGES`).
- `components/` — `context.py` (active DB per demo mode, cached reads `ctx.call("module.fn", ...)` / `ctx.q(sql)`,
  `after_write()`, `goto()`), `ui.py` (KPI cards, badges, Show SQL, AI output), `dialogs.py` (st.dialog action forms),
  `sidebar.py` (filters, Demo Mode steps, tour), `theme.py` (CSS + Plotly "onyx" template), `charts.py`.
- `services/` — no Streamlit imports. Every function takes an `Engine` first. Writes validate, run in one transaction,
  and call `audit.log`. `dialect.py` is the ONLY place with SQLite/PostgreSQL differences.
- `sql/schema.sql`, `sql/views.sql`, `sql/queries/*.sql` — macros `{{PK}} {{DAYS(a,b)}} {{ADD_DAYS(d,n)}}
  {{MONTH_ADD(d,n)}} {{AS_OF}} {{DROP_VIEW(v)}}`, `@INCLUDE(file)` in views.

## Conventions
- Money = integer pence (`*_pence`); trading notional = `notional_usd`, never revenue. Dates = ISO TEXT.
- Demo clock = `app_config.as_of_date`; never use `date.today()` in business logic.
- Health is computed in Python from `v_health_inputs`, stored in `health_snapshots`; KPI views read the latest
  snapshot. Call `ctx.after_write()` after any UI write (refreshes snapshots + clears caches).
- Counterparties are never in `v_customer_kpis` (no ARR/seats/health).
- pandas returns NaN for NULL text — use `formatting.txt()` before string operations.
- Never hard-code acceptance numbers; tune seed data instead. Tests in `tests/test_acceptance.py` guard them.
- AI: only `services/ai.py` talks to Groq; outputs are labelled, never auto-saved; AI root causes saved as Hypothesis.
- Role check: `auth.can_edit(user)` (CS_EXEC) for edits; reports/value reviews can be saved by both; approval = DIRECTOR.
