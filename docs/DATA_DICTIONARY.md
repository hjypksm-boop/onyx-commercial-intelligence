# Data dictionary

Generated from the live schema (`sql/schema.sql`). Conventions: dates are ISO-8601 TEXT, money is INTEGER pence, flags are INTEGER 0/1. All data is synthetic.

## `app_config`

Key/value settings. `as_of_date` is the demo clock used by every view.

| Column | Type | Null | Description |
|---|---|---|---|
| `key` | VARCHAR(64) | no | Primary key |
| `value` | TEXT | no |  |

## `owners`

Relationship owners (fictional staff).

| Column | Type | Null | Description |
|---|---|---|---|
| `owner_id` | INTEGER | no | Primary key |
| `name` | VARCHAR(120) | no |  |
| `title` | VARCHAR(120) | no |  |
| `email` | VARCHAR(200) | no |  |

## `users`

Login accounts (bcrypt hashes). Role CS_EXEC = edit; DIRECTOR = read, reports, approve.

| Column | Type | Null | Description |
|---|---|---|---|
| `user_id` | INTEGER | no | Primary key |
| `email` | VARCHAR(200) | no |  |
| `password_hash` | TEXT | no |  |
| `display_name` | VARCHAR(120) | no |  |
| `role` | VARCHAR(40) | no |  |
| `owner_id` | INTEGER | yes | FK owners |

## `products`

The three subscription product verticals (FB, FA, OFF). Trading Relationships is not a product.

| Column | Type | Null | Description |
|---|---|---|---|
| `product_id` | VARCHAR(8) | no | Primary key |
| `name` | VARCHAR(80) | no |  |
| `description` | TEXT | no |  |

## `customers`

Subscription customers.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Primary key |
| `name` | VARCHAR(160) | no |  |
| `product_id` | VARCHAR(8) | no | FK products |
| `segment` | VARCHAR(60) | no |  |
| `hq_region` | VARCHAR(60) | no |  |
| `owner_id` | INTEGER | yes | FK owners |
| `customer_since` | TEXT | no | First contract start (ISO date) |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |

## `counterparties`

Institutional trading counterparties — tracked separately; no ARR, seats or subscription health.

| Column | Type | Null | Description |
|---|---|---|---|
| `counterparty_id` | INTEGER | no | Primary key |
| `name` | VARCHAR(160) | no |  |
| `region` | VARCHAR(60) | no |  |
| `relationship_status` | VARCHAR(30) | no |  |
| `approval_status` | VARCHAR(30) | no |  |
| `owner_id` | INTEGER | yes | FK owners |
| `relationship_since` | TEXT | no |  |
| `primary_products` | VARCHAR(200) | no |  |

## `subscriptions`

Seat licensing per customer. CHECK active_users ≤ licensed_seats.

| Column | Type | Null | Description |
|---|---|---|---|
| `subscription_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `product_id` | VARCHAR(8) | no | FK products |
| `licensed_seats` | INTEGER | no |  |
| `active_users` | INTEGER | no |  |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |

## `contracts`

Contract terms (prior + current). `is_current = 1` drives ARR and renewal dates; history drives GRR/NRR.

| Column | Type | Null | Description |
|---|---|---|---|
| `contract_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `start_date` | TEXT | no |  |
| `renewal_date` | TEXT | no | End of term / renewal date (ISO date) |
| `term_months` | INTEGER | no |  |
| `arr_pence` | INTEGER | no | Annual contract value in pence |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `billing_frequency` | VARCHAR(20) | no |  |
| `modules` | TEXT | no |  |
| `is_current` | INTEGER | no | 1 = current contract term |

## `contacts`

People at customers / counterparties; champion and decision-maker flags; `Left` status records champion changes.

| Column | Type | Null | Description |
|---|---|---|---|
| `contact_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | yes | FK customers |
| `counterparty_id` | INTEGER | yes | FK counterparties |
| `name` | VARCHAR(120) | no |  |
| `title` | VARCHAR(120) | no |  |
| `email` | VARCHAR(200) | yes |  |
| `is_champion` | INTEGER | no |  |
| `is_decision_maker` | INTEGER | no |  |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `left_date` | TEXT | yes |  |

## `usage_daily`

One row per user per active day. MAU and all monthly aggregates are computed from this table (v_monthly_usage).

| Column | Type | Null | Description |
|---|---|---|---|
| `usage_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `usage_date` | TEXT | no |  |
| `user_key` | VARCHAR(20) | no | Pseudonymous seat identifier (U01…) |
| `logins` | INTEGER | no |  |
| `sessions` | INTEGER | no |  |
| `pricing_queries` | INTEGER | no |  |
| `analytics_runs` | INTEGER | no |  |
| `reports_downloaded` | INTEGER | no |  |
| `api_calls` | INTEGER | no |  |

## `feature_catalogue`

Features per product vertical.

| Column | Type | Null | Description |
|---|---|---|---|
| `feature_id` | INTEGER | no | Primary key |
| `product_id` | VARCHAR(8) | no | FK products |
| `name` | VARCHAR(120) | no |  |
| `description` | TEXT | no |  |

## `feature_usage`

Per-customer feature adoption flag and 90-day usage count.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Composite key part — FK customers |
| `feature_id` | INTEGER | no | Composite key part — Primary key |
| `adopted` | INTEGER | no |  |
| `usage_count_90d` | INTEGER | no | Feature uses in last 90 days |
| `first_used_date` | TEXT | yes |  |

## `ports`

Bunkering ports with coordinates (Flux Bunkers).

| Column | Type | Null | Description |
|---|---|---|---|
| `port_id` | INTEGER | no | Primary key |
| `name` | VARCHAR(80) | no |  |
| `country` | VARCHAR(80) | no |  |
| `latitude` | NUMERIC(9, 5) | no |  |
| `longitude` | NUMERIC(9, 5) | no |  |

## `customer_ports`

Ports in a Flux Bunkers customer's footprint; `subscribed` = covered by their licence.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Composite key part — FK customers |
| `port_id` | INTEGER | no | Composite key part — Primary key |
| `subscribed` | INTEGER | no | 1 = port covered by licence |

## `port_activity`

Monthly price lookups and bunker stems reported per customer and port.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Composite key part — FK customers |
| `port_id` | INTEGER | no | Composite key part — Primary key |
| `month` | VARCHAR(7) | no | Composite key part — Primary key |
| `price_lookups` | INTEGER | no | Pricing-tool lookups for the port in the month |
| `stems_reported` | INTEGER | no | Bunker stems the customer reported at the port |

## `benchmark_coverage`

Benchmarks licensed by The Officials customers.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Composite key part — FK customers |
| `benchmark` | VARCHAR(120) | no | Composite key part — Primary key |
| `region` | VARCHAR(60) | no |  |
| `licensed` | INTEGER | no |  |

## `onboarding_milestones`

Onboarding checklist; the `is_first_value` milestone defines time-to-first-value.

| Column | Type | Null | Description |
|---|---|---|---|
| `milestone_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `seq` | INTEGER | no |  |
| `milestone` | VARCHAR(120) | no |  |
| `target_date` | TEXT | no |  |
| `completed_date` | TEXT | yes |  |
| `is_first_value` | INTEGER | no |  |

## `support_tickets`

Support tickets with severity, SLA and escalation flags.

| Column | Type | Null | Description |
|---|---|---|---|
| `ticket_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `subject` | VARCHAR(200) | no |  |
| `severity` | VARCHAR(10) | no |  |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `opened_date` | TEXT | no |  |
| `closed_date` | TEXT | yes |  |
| `sla_hours` | INTEGER | no |  |
| `sla_breached` | INTEGER | no | 1 if the SLA was breached |
| `escalated` | INTEGER | no | 1 if escalated |

## `data_incidents`

Data availability incidents (Flux Analytics).

| Column | Type | Null | Description |
|---|---|---|---|
| `incident_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `incident_date` | TEXT | no |  |
| `dataset` | VARCHAR(120) | no |  |
| `duration_hours` | NUMERIC(6, 1) | no |  |
| `impact` | VARCHAR(10) | no |  |
| `resolved_date` | TEXT | yes |  |

## `activities`

Meetings, calls, emails, demos, notes and escalations (customer or counterparty). Meeting sentiment 1–5.

| Column | Type | Null | Description |
|---|---|---|---|
| `activity_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | yes | FK customers |
| `counterparty_id` | INTEGER | yes | FK counterparties |
| `activity_type` | VARCHAR(20) | no |  |
| `activity_date` | TEXT | no |  |
| `subject` | VARCHAR(200) | no |  |
| `summary` | TEXT | yes |  |
| `attendees` | TEXT | yes |  |
| `sentiment` | INTEGER | yes | Meeting sentiment 1 (negative) – 5 (very positive) |
| `next_steps` | TEXT | yes |  |
| `owner_id` | INTEGER | yes | FK owners |
| `created_by` | VARCHAR(200) | no |  |
| `created_at` | TEXT | no |  |

## `account_notes`

Free-text account notes.

| Column | Type | Null | Description |
|---|---|---|---|
| `note_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | yes | FK customers |
| `counterparty_id` | INTEGER | yes | FK counterparties |
| `note_date` | TEXT | no |  |
| `author` | VARCHAR(200) | no |  |
| `body` | TEXT | no |  |

## `opportunities`

Expansion pipeline. Expected value = potential_arr_pence × probability. Closed Won = booked new ACV.

| Column | Type | Null | Description |
|---|---|---|---|
| `opportunity_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `product_id` | VARCHAR(8) | no | FK products |
| `description` | VARCHAR(200) | no |  |
| `potential_arr_pence` | INTEGER | no | Potential annual revenue in pence (> 0) |
| `probability` | NUMERIC(4, 3) | no | Close probability 0–1 |
| `stage` | VARCHAR(20) | no |  |
| `expected_close_date` | TEXT | no |  |
| `owner_id` | INTEGER | no | FK owners |
| `next_action` | TEXT | yes |  |
| `qualification` | TEXT | yes | JSON checklist: need, budget, timing, decision maker + notes |
| `created_date` | TEXT | no |  |
| `closed_date` | TEXT | yes |  |

## `opportunity_stage_history`

Every stage change (from → to, date, user).

| Column | Type | Null | Description |
|---|---|---|---|
| `history_id` | INTEGER | no | Primary key |
| `opportunity_id` | INTEGER | no |  |
| `from_stage` | VARCHAR(20) | yes |  |
| `to_stage` | VARCHAR(20) | no |  |
| `changed_on` | TEXT | no |  |
| `changed_by` | VARCHAR(200) | no |  |

## `tasks`

Follow-ups; `source` records where a task was created (Manual, Meeting #id, Recovery plan, Seed).

| Column | Type | Null | Description |
|---|---|---|---|
| `task_id` | INTEGER | no | Primary key |
| `title` | VARCHAR(200) | no |  |
| `customer_id` | INTEGER | yes | FK customers |
| `counterparty_id` | INTEGER | yes | FK counterparties |
| `category` | VARCHAR(40) | no |  |
| `priority` | VARCHAR(10) | no |  |
| `owner_id` | INTEGER | no | FK owners |
| `due_date` | TEXT | no |  |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `notes` | TEXT | yes |  |
| `source` | VARCHAR(40) | no | Origin of the record |
| `created_on` | TEXT | no |  |
| `completed_on` | TEXT | yes |  |

## `health_weights`

Health-score weight versions (latest row is active). CHECK weights total 100.

| Column | Type | Null | Description |
|---|---|---|---|
| `weights_id` | INTEGER | no | Primary key |
| `adoption` | INTEGER | no |  |
| `usage_trend` | INTEGER | no |  |
| `support` | INTEGER | no |  |
| `engagement` | INTEGER | no |  |
| `sentiment` | INTEGER | no | Meeting sentiment 1 (negative) – 5 (very positive) |
| `effective_from` | TEXT | no |  |
| `changed_by` | VARCHAR(200) | no |  |

## `health_snapshots`

Calculated health per customer and date (month-end history + workspace-date snapshot). NULL component = missing data.

| Column | Type | Null | Description |
|---|---|---|---|
| `customer_id` | INTEGER | no | Composite key part — FK customers |
| `snapshot_date` | TEXT | no | Composite key part — Primary key |
| `score` | NUMERIC(5, 1) | no |  |
| `category` | VARCHAR(10) | no |  |
| `adoption_score` | NUMERIC(5, 1) | yes |  |
| `usage_trend_score` | NUMERIC(5, 1) | yes |  |
| `support_score` | NUMERIC(5, 1) | yes |  |
| `engagement_score` | NUMERIC(5, 1) | yes |  |
| `sentiment_score` | NUMERIC(5, 1) | yes |  |
| `components_available` | INTEGER | no | Number of the 5 health components with data (partial score if < 5) |

## `risk_hypotheses`

Root causes for at-risk accounts: Hypothesis / Confirmed (with confirming activity and user) / Rejected.

| Column | Type | Null | Description |
|---|---|---|---|
| `hypothesis_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `cause` | TEXT | no |  |
| `category` | VARCHAR(40) | no |  |
| `status` | VARCHAR(12) | no | Lifecycle status (see CHECK constraint) |
| `evidence` | TEXT | yes |  |
| `source` | VARCHAR(10) | no | Origin of the record |
| `confirmed_by` | VARCHAR(200) | yes |  |
| `confirmed_activity_id` | INTEGER | yes | Activity in which the cause was confirmed |
| `created_by` | VARCHAR(200) | no |  |
| `created_on` | TEXT | no |  |
| `updated_on` | TEXT | no |  |

## `recovery_plans`

Guided recovery workflow state per account (status, step, notes JSON, baseline metrics, outcome).

| Column | Type | Null | Description |
|---|---|---|---|
| `plan_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `current_step` | INTEGER | no |  |
| `owner_id` | INTEGER | yes | FK owners |
| `started_on` | TEXT | yes |  |
| `baseline_mau` | INTEGER | yes | Active users when the plan started |
| `baseline_score` | NUMERIC(5, 1) | yes | Health score when the plan started |
| `step_notes` | TEXT | no | JSON {step: note} |
| `outcome` | VARCHAR(30) | yes |  |
| `outcome_reason` | TEXT | yes |  |
| `updated_on` | TEXT | no |  |

## `value_reviews`

Saved, versioned value-review content (JSON of section texts).

| Column | Type | Null | Description |
|---|---|---|---|
| `review_id` | INTEGER | no | Primary key |
| `customer_id` | INTEGER | no | FK customers |
| `period_start` | TEXT | no |  |
| `period_end` | TEXT | no |  |
| `version` | INTEGER | no |  |
| `content_json` | TEXT | no | JSON of section texts |
| `created_by` | VARCHAR(200) | no |  |
| `created_at` | TEXT | no |  |

## `close_reports`

Saved, versioned close reports: metrics JSON, commentary JSON, approval.

| Column | Type | Null | Description |
|---|---|---|---|
| `report_id` | INTEGER | no | Primary key |
| `report_date` | TEXT | no |  |
| `version` | INTEGER | no |  |
| `metrics_json` | TEXT | no | JSON of computed metrics |
| `commentary_json` | TEXT | no | JSON of section commentary |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `approved_by` | VARCHAR(200) | yes |  |
| `created_by` | VARCHAR(200) | no |  |
| `created_at` | TEXT | no |  |

## `trading_activity`

Monthly trades and notional (USD) per counterparty. Notional is NOT revenue.

| Column | Type | Null | Description |
|---|---|---|---|
| `counterparty_id` | INTEGER | no | Composite key part — FK counterparties |
| `month` | VARCHAR(7) | no | Composite key part — Primary key |
| `trade_count` | INTEGER | no |  |
| `notional_usd` | INTEGER | no | Trading notional in USD — not revenue |

## `counterparty_issues`

Execution / settlement / confirmation / service / credit issues.

| Column | Type | Null | Description |
|---|---|---|---|
| `issue_id` | INTEGER | no | Primary key |
| `counterparty_id` | INTEGER | no | FK counterparties |
| `issue_type` | VARCHAR(20) | no |  |
| `description` | TEXT | no |  |
| `severity` | VARCHAR(10) | no |  |
| `status` | VARCHAR(20) | no | Lifecycle status (see CHECK constraint) |
| `opened_date` | TEXT | no |  |
| `resolved_date` | TEXT | yes |  |
| `owner_id` | INTEGER | yes | FK owners |

## `audit_log`

Every create/update/delete: who, when, entity, summary and old → new values (JSON).

| Column | Type | Null | Description |
|---|---|---|---|
| `audit_id` | INTEGER | no | Primary key |
| `ts` | TEXT | no |  |
| `user_email` | VARCHAR(200) | no |  |
| `entity` | VARCHAR(40) | no |  |
| `entity_id` | INTEGER | yes |  |
| `action` | VARCHAR(10) | no |  |
| `customer_id` | INTEGER | yes | FK customers |
| `counterparty_id` | INTEGER | yes | FK counterparties |
| `summary` | TEXT | no |  |
| `changes_json` | TEXT | yes | JSON {field: [old, new]} |

## Views

- `v_app_as_of` — Demo clock.
- `v_current_contracts` — Current contract per customer + days_to_renewal.
- `v_monthly_usage` — Monthly MAU (distinct users with logins) and usage sums from usage_daily.
- `v_health_inputs` — Raw health-score inputs at the demo clock (same SQL as sql/queries/health_inputs.sql).
- `v_customer_health` — Latest health snapshot per customer.
- `v_pipeline` — Opportunities + expected value + is_open.
- `v_last_contact` — Last meaningful contact (meeting/call/email/demo).
- `v_onboarding` — Milestones done/total and time-to-first-value.
- `v_feature_adoption` — Feature adoption joined to customers and verticals.
- `v_customer_kpis` — One row per subscription customer — basis of every portfolio KPI.
- `v_renewals` — Renewal fields from v_customer_kpis.
- `v_portfolio_kpis` — Unfiltered portfolio totals.
- `v_counterparty_summary` — Counterparty status, 12-month trades and notional (not revenue), open issues.
