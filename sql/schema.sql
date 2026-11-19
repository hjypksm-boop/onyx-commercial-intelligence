-- ONYX | Commercial Intelligence — schema (portable SQLite / PostgreSQL via services/dialect.py macros)
-- Conventions: dates are ISO TEXT 'YYYY-MM-DD'; timestamps ISO TEXT; money is INTEGER pence; flags are INTEGER 0/1.

CREATE TABLE app_config (
    key   VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE owners (
    owner_id  {{PK}},
    name      VARCHAR(120) NOT NULL UNIQUE,
    title     VARCHAR(120) NOT NULL,
    email     VARCHAR(200) NOT NULL UNIQUE
);

CREATE TABLE users (
    user_id       {{PK}},
    email         VARCHAR(200) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  VARCHAR(120) NOT NULL,
    role          VARCHAR(40) NOT NULL CHECK (role IN ('CS_EXEC', 'DIRECTOR')),
    owner_id      INTEGER REFERENCES owners(owner_id)
);

CREATE TABLE products (
    product_id  VARCHAR(8) PRIMARY KEY,
    name        VARCHAR(80) NOT NULL UNIQUE,
    description TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id    {{PK}},
    name           VARCHAR(160) NOT NULL UNIQUE,
    product_id     VARCHAR(8) NOT NULL REFERENCES products(product_id),
    segment        VARCHAR(60) NOT NULL,
    hq_region      VARCHAR(60) NOT NULL,
    owner_id       INTEGER REFERENCES owners(owner_id),
    customer_since TEXT NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Churned'))
);

CREATE TABLE counterparties (
    counterparty_id     {{PK}},
    name                VARCHAR(160) NOT NULL UNIQUE,
    region              VARCHAR(60) NOT NULL,
    relationship_status VARCHAR(30) NOT NULL CHECK (relationship_status IN ('Active', 'Developing', 'Dormant', 'On hold')),
    approval_status     VARCHAR(30) NOT NULL CHECK (approval_status IN ('Approved', 'Pending KYC', 'Under Review', 'Suspended')),
    owner_id            INTEGER REFERENCES owners(owner_id),
    relationship_since  TEXT NOT NULL,
    primary_products    VARCHAR(200) NOT NULL
);

CREATE TABLE subscriptions (
    subscription_id {{PK}},
    customer_id     INTEGER NOT NULL UNIQUE REFERENCES customers(customer_id),
    product_id      VARCHAR(8) NOT NULL REFERENCES products(product_id),
    licensed_seats  INTEGER NOT NULL CHECK (licensed_seats >= 0),
    active_users    INTEGER NOT NULL CHECK (active_users >= 0),
    status          VARCHAR(20) NOT NULL DEFAULT 'Active',
    CHECK (active_users <= licensed_seats)
);

CREATE TABLE contracts (
    contract_id       {{PK}},
    customer_id       INTEGER NOT NULL REFERENCES customers(customer_id),
    start_date        TEXT NOT NULL,
    renewal_date      TEXT NOT NULL,
    term_months       INTEGER NOT NULL CHECK (term_months > 0),
    arr_pence         INTEGER NOT NULL CHECK (arr_pence >= 0),
    status            VARCHAR(20) NOT NULL CHECK (status IN ('Active', 'Renewed', 'Expired', 'Churned')),
    billing_frequency VARCHAR(20) NOT NULL CHECK (billing_frequency IN ('Annual', 'Quarterly', 'Monthly')),
    modules           TEXT NOT NULL,
    is_current        INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1))
);
CREATE INDEX ix_contracts_customer ON contracts(customer_id);

CREATE TABLE contacts (
    contact_id        {{PK}},
    customer_id       INTEGER REFERENCES customers(customer_id),
    counterparty_id   INTEGER REFERENCES counterparties(counterparty_id),
    name              VARCHAR(120) NOT NULL,
    title             VARCHAR(120) NOT NULL,
    email             VARCHAR(200),
    is_champion       INTEGER NOT NULL DEFAULT 0 CHECK (is_champion IN (0, 1)),
    is_decision_maker INTEGER NOT NULL DEFAULT 0 CHECK (is_decision_maker IN (0, 1)),
    status            VARCHAR(20) NOT NULL DEFAULT 'Active' CHECK (status IN ('Active', 'Left')),
    left_date         TEXT,
    CHECK (customer_id IS NOT NULL OR counterparty_id IS NOT NULL)
);

CREATE TABLE usage_daily (
    usage_id           {{PK}},
    customer_id        INTEGER NOT NULL REFERENCES customers(customer_id),
    usage_date         TEXT NOT NULL,
    user_key           VARCHAR(20) NOT NULL,
    logins             INTEGER NOT NULL DEFAULT 0 CHECK (logins >= 0),
    sessions           INTEGER NOT NULL DEFAULT 0 CHECK (sessions >= 0),
    pricing_queries    INTEGER NOT NULL DEFAULT 0 CHECK (pricing_queries >= 0),
    analytics_runs     INTEGER NOT NULL DEFAULT 0 CHECK (analytics_runs >= 0),
    reports_downloaded INTEGER NOT NULL DEFAULT 0 CHECK (reports_downloaded >= 0),
    api_calls          INTEGER NOT NULL DEFAULT 0 CHECK (api_calls >= 0)
);
CREATE INDEX ix_usage_customer_date ON usage_daily(customer_id, usage_date);

CREATE TABLE feature_catalogue (
    feature_id  {{PK}},
    product_id  VARCHAR(8) NOT NULL REFERENCES products(product_id),
    name        VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    UNIQUE (product_id, name)
);

CREATE TABLE feature_usage (
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    feature_id      INTEGER NOT NULL REFERENCES feature_catalogue(feature_id),
    adopted         INTEGER NOT NULL CHECK (adopted IN (0, 1)),
    usage_count_90d INTEGER NOT NULL DEFAULT 0 CHECK (usage_count_90d >= 0),
    first_used_date TEXT,
    PRIMARY KEY (customer_id, feature_id)
);

CREATE TABLE ports (
    port_id   {{PK}},
    name      VARCHAR(80) NOT NULL UNIQUE,
    country   VARCHAR(80) NOT NULL,
    latitude  NUMERIC(9, 5) NOT NULL,
    longitude NUMERIC(9, 5) NOT NULL
);

CREATE TABLE customer_ports (
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    port_id     INTEGER NOT NULL REFERENCES ports(port_id),
    subscribed  INTEGER NOT NULL CHECK (subscribed IN (0, 1)),
    PRIMARY KEY (customer_id, port_id)
);

CREATE TABLE port_activity (
    customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
    port_id         INTEGER NOT NULL REFERENCES ports(port_id),
    month           VARCHAR(7) NOT NULL,
    price_lookups   INTEGER NOT NULL CHECK (price_lookups >= 0),
    stems_reported  INTEGER NOT NULL CHECK (stems_reported >= 0),
    PRIMARY KEY (customer_id, port_id, month)
);

CREATE TABLE benchmark_coverage (
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    benchmark   VARCHAR(120) NOT NULL,
    region      VARCHAR(60) NOT NULL,
    licensed    INTEGER NOT NULL CHECK (licensed IN (0, 1)),
    PRIMARY KEY (customer_id, benchmark)
);

CREATE TABLE onboarding_milestones (
    milestone_id   {{PK}},
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    seq            INTEGER NOT NULL,
    milestone      VARCHAR(120) NOT NULL,
    target_date    TEXT NOT NULL,
    completed_date TEXT,
    is_first_value INTEGER NOT NULL DEFAULT 0 CHECK (is_first_value IN (0, 1))
);

CREATE TABLE support_tickets (
    ticket_id    {{PK}},
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    subject      VARCHAR(200) NOT NULL,
    severity     VARCHAR(10) NOT NULL CHECK (severity IN ('Low', 'Medium', 'High', 'Critical')),
    status       VARCHAR(20) NOT NULL CHECK (status IN ('Open', 'In progress', 'Resolved', 'Closed')),
    opened_date  TEXT NOT NULL,
    closed_date  TEXT,
    sla_hours    INTEGER NOT NULL CHECK (sla_hours > 0),
    sla_breached INTEGER NOT NULL DEFAULT 0 CHECK (sla_breached IN (0, 1)),
    escalated    INTEGER NOT NULL DEFAULT 0 CHECK (escalated IN (0, 1))
);
CREATE INDEX ix_tickets_customer ON support_tickets(customer_id, opened_date);

CREATE TABLE data_incidents (
    incident_id    {{PK}},
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    incident_date  TEXT NOT NULL,
    dataset        VARCHAR(120) NOT NULL,
    duration_hours NUMERIC(6, 1) NOT NULL CHECK (duration_hours >= 0),
    impact         VARCHAR(10) NOT NULL CHECK (impact IN ('Low', 'Medium', 'High')),
    resolved_date  TEXT
);
CREATE INDEX ix_incidents_customer ON data_incidents(customer_id, incident_date);

CREATE TABLE activities (
    activity_id     {{PK}},
    customer_id     INTEGER REFERENCES customers(customer_id),
    counterparty_id INTEGER REFERENCES counterparties(counterparty_id),
    activity_type   VARCHAR(20) NOT NULL CHECK (activity_type IN ('Meeting', 'Call', 'Email', 'Demo', 'Note', 'Escalation')),
    activity_date   TEXT NOT NULL,
    subject         VARCHAR(200) NOT NULL,
    summary         TEXT,
    attendees       TEXT,
    sentiment       INTEGER CHECK (sentiment IS NULL OR sentiment BETWEEN 1 AND 5),
    next_steps      TEXT,
    owner_id        INTEGER REFERENCES owners(owner_id),
    created_by      VARCHAR(200) NOT NULL,
    created_at      TEXT NOT NULL,
    CHECK (customer_id IS NOT NULL OR counterparty_id IS NOT NULL)
);
CREATE INDEX ix_activities_customer ON activities(customer_id, activity_date);
CREATE INDEX ix_activities_date ON activities(activity_date);

CREATE TABLE account_notes (
    note_id         {{PK}},
    customer_id     INTEGER REFERENCES customers(customer_id),
    counterparty_id INTEGER REFERENCES counterparties(counterparty_id),
    note_date       TEXT NOT NULL,
    author          VARCHAR(200) NOT NULL,
    body            TEXT NOT NULL,
    CHECK (customer_id IS NOT NULL OR counterparty_id IS NOT NULL)
);

CREATE TABLE opportunities (
    opportunity_id      {{PK}},
    customer_id         INTEGER NOT NULL REFERENCES customers(customer_id),
    product_id          VARCHAR(8) NOT NULL REFERENCES products(product_id),
    description         VARCHAR(200) NOT NULL,
    potential_arr_pence INTEGER NOT NULL CHECK (potential_arr_pence > 0),
    probability         NUMERIC(4, 3) NOT NULL CHECK (probability >= 0 AND probability <= 1),
    stage               VARCHAR(20) NOT NULL CHECK (stage IN ('Identified', 'Qualified', 'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost')),
    expected_close_date TEXT NOT NULL,
    owner_id            INTEGER NOT NULL REFERENCES owners(owner_id),
    next_action         TEXT,
    qualification       TEXT,
    created_date        TEXT NOT NULL,
    closed_date         TEXT
);
CREATE INDEX ix_opps_customer ON opportunities(customer_id);

CREATE TABLE opportunity_stage_history (
    history_id     {{PK}},
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(opportunity_id) ON DELETE CASCADE,
    from_stage     VARCHAR(20),
    to_stage       VARCHAR(20) NOT NULL,
    changed_on     TEXT NOT NULL,
    changed_by     VARCHAR(200) NOT NULL
);

CREATE TABLE tasks (
    task_id         {{PK}},
    title           VARCHAR(200) NOT NULL,
    customer_id     INTEGER REFERENCES customers(customer_id),
    counterparty_id INTEGER REFERENCES counterparties(counterparty_id),
    category        VARCHAR(40) NOT NULL CHECK (category IN ('Customer escalation', 'Renewal preparation', 'Sales follow-up', 'Product demonstration', 'Onboarding', 'Commercial reporting')),
    priority        VARCHAR(10) NOT NULL CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    owner_id        INTEGER NOT NULL REFERENCES owners(owner_id),
    due_date        TEXT NOT NULL,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('Open', 'In progress', 'Blocked', 'Done')),
    notes           TEXT,
    source          VARCHAR(40) NOT NULL DEFAULT 'Manual',
    created_on      TEXT NOT NULL,
    completed_on    TEXT
);
CREATE INDEX ix_tasks_due ON tasks(due_date);
CREATE INDEX ix_tasks_customer ON tasks(customer_id);

CREATE TABLE health_weights (
    weights_id     {{PK}},
    adoption       INTEGER NOT NULL CHECK (adoption BETWEEN 0 AND 100),
    usage_trend    INTEGER NOT NULL CHECK (usage_trend BETWEEN 0 AND 100),
    support        INTEGER NOT NULL CHECK (support BETWEEN 0 AND 100),
    engagement     INTEGER NOT NULL CHECK (engagement BETWEEN 0 AND 100),
    sentiment      INTEGER NOT NULL CHECK (sentiment BETWEEN 0 AND 100),
    effective_from TEXT NOT NULL,
    changed_by     VARCHAR(200) NOT NULL,
    CHECK (adoption + usage_trend + support + engagement + sentiment = 100)
);

CREATE TABLE health_snapshots (
    customer_id          INTEGER NOT NULL REFERENCES customers(customer_id),
    snapshot_date        TEXT NOT NULL,
    score                NUMERIC(5, 1) NOT NULL CHECK (score BETWEEN 0 AND 100),
    category             VARCHAR(10) NOT NULL CHECK (category IN ('Healthy', 'Monitor', 'At Risk')),
    adoption_score       NUMERIC(5, 1),
    usage_trend_score    NUMERIC(5, 1),
    support_score        NUMERIC(5, 1),
    engagement_score     NUMERIC(5, 1),
    sentiment_score      NUMERIC(5, 1),
    components_available INTEGER NOT NULL CHECK (components_available BETWEEN 1 AND 5),
    PRIMARY KEY (customer_id, snapshot_date)
);

CREATE TABLE risk_hypotheses (
    hypothesis_id  {{PK}},
    customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
    cause          TEXT NOT NULL,
    category       VARCHAR(40) NOT NULL,
    status         VARCHAR(12) NOT NULL CHECK (status IN ('Hypothesis', 'Confirmed', 'Rejected')),
    evidence       TEXT,
    source         VARCHAR(10) NOT NULL CHECK (source IN ('Manual', 'AI', 'System')),
    confirmed_by   VARCHAR(200),
    confirmed_activity_id INTEGER REFERENCES activities(activity_id),
    created_by     VARCHAR(200) NOT NULL,
    created_on     TEXT NOT NULL,
    updated_on     TEXT NOT NULL
);

CREATE TABLE recovery_plans (
    plan_id        {{PK}},
    customer_id    INTEGER NOT NULL UNIQUE REFERENCES customers(customer_id),
    status         VARCHAR(20) NOT NULL CHECK (status IN ('Not started', 'Investigating', 'Customer contacted', 'Plan agreed', 'Improving', 'Renewed', 'Churned')),
    current_step   INTEGER NOT NULL DEFAULT 1 CHECK (current_step BETWEEN 1 AND 6),
    owner_id       INTEGER REFERENCES owners(owner_id),
    started_on     TEXT,
    baseline_mau   INTEGER,
    baseline_score NUMERIC(5, 1),
    step_notes     TEXT NOT NULL DEFAULT '{}',
    outcome        VARCHAR(30) CHECK (outcome IS NULL OR outcome IN ('Renewed', 'Renewed with downsell', 'Churned')),
    outcome_reason TEXT,
    updated_on     TEXT NOT NULL
);

CREATE TABLE value_reviews (
    review_id    {{PK}},
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    version      INTEGER NOT NULL CHECK (version >= 1),
    content_json TEXT NOT NULL,
    created_by   VARCHAR(200) NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE close_reports (
    report_id       {{PK}},
    report_date     TEXT NOT NULL,
    version         INTEGER NOT NULL CHECK (version >= 1),
    metrics_json    TEXT NOT NULL,
    commentary_json TEXT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Approved')),
    approved_by     VARCHAR(200),
    created_by      VARCHAR(200) NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE trading_activity (
    counterparty_id INTEGER NOT NULL REFERENCES counterparties(counterparty_id),
    month           VARCHAR(7) NOT NULL,
    trade_count     INTEGER NOT NULL CHECK (trade_count >= 0),
    notional_usd    INTEGER NOT NULL CHECK (notional_usd >= 0),
    PRIMARY KEY (counterparty_id, month)
);

CREATE TABLE counterparty_issues (
    issue_id        {{PK}},
    counterparty_id INTEGER NOT NULL REFERENCES counterparties(counterparty_id),
    issue_type      VARCHAR(20) NOT NULL CHECK (issue_type IN ('Execution', 'Settlement', 'Confirmation', 'Service', 'Credit')),
    description     TEXT NOT NULL,
    severity        VARCHAR(10) NOT NULL CHECK (severity IN ('Low', 'Medium', 'High', 'Critical')),
    status          VARCHAR(20) NOT NULL CHECK (status IN ('Open', 'In progress', 'Resolved')),
    opened_date     TEXT NOT NULL,
    resolved_date   TEXT,
    owner_id        INTEGER REFERENCES owners(owner_id)
);

CREATE TABLE audit_log (
    audit_id        {{PK}},
    ts              TEXT NOT NULL,
    user_email      VARCHAR(200) NOT NULL,
    entity          VARCHAR(40) NOT NULL,
    entity_id       INTEGER,
    action          VARCHAR(10) NOT NULL CHECK (action IN ('create', 'update', 'delete')),
    customer_id     INTEGER,
    counterparty_id INTEGER,
    summary         TEXT NOT NULL,
    changes_json    TEXT
);
CREATE INDEX ix_audit_customer ON audit_log(customer_id)
