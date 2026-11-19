# Build plan — ONYX | Commercial Intelligence

## Phases
1. **Foundation**: requirements, `.env.example`, `.streamlit/config.toml`, CSS, auth (bcrypt), `st.navigation` shell with 10 pages, disclaimer banner.
2. **Data layer**: `sql/schema.sql`, `sql/views.sql`, `sql/queries/*.sql`, `services/dialect.py` (SQLite/PostgreSQL macro renderer), `services/seed.py` (deterministic, `random.Random(20261118)`), `data/baseline.db`, reset, `docs/DATA_DICTIONARY.md`, acceptance tests.
3. **Core pages**: Executive Overview, Customer Portfolio, Customer 360 (+ action dialogs), health scoring + Settings.
4. **Commercial workflows**: Growth Opportunities, Retention workspace, Tasks, Product Analytics.
5. **Reporting**: Value Review Builder, Close Report, PDF (reportlab + matplotlib), CSV, print HTML.
6. **Demo Mode**: SQLite sandboxes copied from `baseline.db`, Scenario A/B/C guided steps, reset.
7. **Phase 2**: Groq/Llama copilot, Ask the portfolio (guarded SELECT), Show SQL, GRR/NRR, port map, audit trail, data quality, interview tour.
8. **Polish & verification**: full test run, headless launch, README, DEMO_SCRIPT, KNOWN_LIMITATIONS.

## Ambiguities resolved
| Topic | Decision |
|---|---|
| AS_OF_DATE | `AS_OF_DATE` env var, else the seed date. Stored in `app_config.as_of_date`; all views read it. This is the "demo clock": forms default to it and health is evaluated at it. |
| Dates | Stored as ISO `YYYY-MM-DD` TEXT in both dialects (portable comparisons). Date arithmetic goes through macros `{{DAYS(a,b)}}`, `{{ADD_DAYS(d,n)}}`, `{{MONTH_ADD(d,n)}}` rendered by `services/dialect.py` — the only dialect-specific module. |
| Money | Integer pence (`*_pence`). Trading notional stored as integer USD (`notional_usd`), never summed with revenue. |
| Health storage | Health is computed in Python (`services/health.py`) from SQL view `v_health_inputs`, then written to `health_snapshots`. Revenue-at-risk and all KPI views read the latest snapshot, so KPIs remain pure SQL over stored records. Snapshots are refreshed after every write and on weight changes. |
| Active users | `subscriptions.active_users` is the current licensing figure (validated ≤ licensed). Seed data makes it equal to the current-month MAU computed from `usage_daily`. Historical snapshots use the month's MAU. |
| Usage trend months | "Last 3 months" = the AS_OF month and the two before it (current month may be partial); "previous 3" = the three before that. |
| Gulf MAU labels | The six required values are always the six most recent calendar months up to AS_OF (Jun–Nov when AS_OF is in November). |
| Health history | Month-end snapshots for the previous 11 months + the AS_OF snapshot (refreshed daily on use). |
| Close Report example day | Baseline AS_OF has 8 meetings + 2 at-risk accounts from records; Scenario C sandbox adds 3 new opportunities worth £75,000. Baseline potential expansion stays £62,000. |
| Scenarios on PostgreSQL | Sandboxes are always SQLite copies of `baseline.db`; live workspace may be PostgreSQL. |
| Ask the portfolio | Lives on Executive Overview. Validator is a hand-written allow-list parser (no extra dependency) + SQLite read-only connection / PostgreSQL read-only transaction. |
| Retention metrics | On the Health & Retention page, calculated from `contracts` history (prior vs current term). |
