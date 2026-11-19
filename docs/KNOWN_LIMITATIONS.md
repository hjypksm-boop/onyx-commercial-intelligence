# Known limitations

Everything in the UI works against the database. These are the deliberate boundaries of the demo.

## Data & environment
- **PostgreSQL / Supabase is untested here.** SQL is written to be portable (dialect differences isolated in
  `services/dialect.py`, dates stored as ISO text), but the test suite runs on SQLite only; no PostgreSQL server was
  available in the build environment. Supabase Auth is not implemented — local bcrypt auth is used in all cases.
- **Scenario sandboxes are always SQLite** copies of `data/baseline.db`, even when the live workspace is PostgreSQL.
- **Demo clock.** The workspace date (`AS_OF_DATE`) is fixed at seed time. Real days passing do not move it; run
  `make seed` to roll forward. Activities cannot be dated after the workspace date.
- **Active users vs usage.** `subscriptions.active_users` can be edited manually (Customer 360 → Edit account); this does
  not create `usage_daily` rows, so MAU charts reflect recorded usage only.
- **Health history** is backfilled at month-ends only; afterwards one snapshot per workspace date is written (refreshed
  after every change). Historical snapshots use that month's MAU for adoption.
- **Contracts are not modified by the pipeline or retention workflow.** Closed Won deals are reported as *booked new ACV*
  but do not change contract ARR; a recorded renewal outcome does not create a new contract term. GRR/NRR are therefore
  computed from the seeded contract history.

## UI
- The opportunity board uses **"Move to…" controls**, not drag-and-drop (Streamlit has no native drag-and-drop).
- Follow-up emails are **drafts only** — nothing is sent.
- The port map uses Plotly's offline natural-earth projection (no street-level basemap).
- Concurrent editing is last-write-wins; there is no record locking.
- Streamlit's `AppTest` cannot submit forms inside `st.dialog` (it does not emulate the dialog's fragment rerun), so
  dialog submission is covered by service-level tests and dialog rendering by UI tests.

## AI
- Free-text **Ask the portfolio** and AI drafts require `GROQ_API_KEY`; without it, labelled template drafts and
  pre-written example queries are used. The model name is configurable (`GROQ_MODEL`) — check Groq's current model list.
- The SQL guard is an allow-list validator plus a read-only connection (SQLite `mode=ro`, PostgreSQL
  `SET TRANSACTION READ ONLY`). It accepts only a single SELECT/WITH over allow-listed views; complex but valid SQL
  (e.g. some comma-join forms) may be rejected conservatively.
- **Model:** the spec asked for Meta Llama, but Groq's model list for this account (Nov 2026) has no Llama chat model —
  only `llama-prompt-guard` classifiers. The default is `openai/gpt-oss-120b` (a reasoning model, called with
  `reasoning_effort="low"`). Set `GROQ_MODEL` to switch back to a Llama model if one becomes available.
- Responses are cached in-process only (cleared on restart).
