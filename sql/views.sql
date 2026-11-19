-- ONYX | Commercial Intelligence — reporting views. All headline KPIs come from these views.
-- {{AS_OF}} is the demo clock stored in app_config (see services/dialect.py).

{{DROP_VIEW(v_portfolio_kpis)}};
{{DROP_VIEW(v_renewals)}};
{{DROP_VIEW(v_customer_kpis)}};
{{DROP_VIEW(v_counterparty_summary)}};
{{DROP_VIEW(v_feature_adoption)}};
{{DROP_VIEW(v_onboarding)}};
{{DROP_VIEW(v_last_contact)}};
{{DROP_VIEW(v_pipeline)}};
{{DROP_VIEW(v_customer_health)}};
{{DROP_VIEW(v_health_inputs)}};
{{DROP_VIEW(v_monthly_usage)}};
{{DROP_VIEW(v_current_contracts)}};
{{DROP_VIEW(v_app_as_of)}};

CREATE VIEW v_app_as_of AS
SELECT value AS as_of_date FROM app_config WHERE key = 'as_of_date';

CREATE VIEW v_current_contracts AS
SELECT ct.contract_id, ct.customer_id, ct.start_date, ct.renewal_date, ct.term_months, ct.arr_pence,
       ct.status, ct.billing_frequency, ct.modules,
       {{DAYS(ct.renewal_date, {{AS_OF}})}} AS days_to_renewal
FROM contracts ct
WHERE ct.is_current = 1;

-- Monthly aggregates computed from daily usage records
CREATE VIEW v_monthly_usage AS
SELECT u.customer_id,
       substr(u.usage_date, 1, 7) AS month,
       COUNT(DISTINCT CASE WHEN u.logins > 0 THEN u.user_key END) AS mau,
       SUM(u.logins) AS logins,
       SUM(u.sessions) AS sessions,
       SUM(u.pricing_queries) AS pricing_queries,
       SUM(u.analytics_runs) AS analytics_runs,
       SUM(u.reports_downloaded) AS reports_downloaded,
       SUM(u.api_calls) AS api_calls,
       COUNT(*) AS active_user_days
FROM usage_daily u
WHERE u.usage_date <= {{AS_OF}}
GROUP BY u.customer_id, substr(u.usage_date, 1, 7);

CREATE VIEW v_health_inputs AS
@INCLUDE(queries/health_inputs.sql);

-- Latest calculated health snapshot per customer (written by services/health.py)
CREATE VIEW v_customer_health AS
SELECT h.customer_id, h.snapshot_date, h.score, h.category, h.adoption_score, h.usage_trend_score,
       h.support_score, h.engagement_score, h.sentiment_score, h.components_available
FROM health_snapshots h
WHERE h.snapshot_date = (SELECT MAX(h2.snapshot_date) FROM health_snapshots h2 WHERE h2.customer_id = h.customer_id);

CREATE VIEW v_pipeline AS
SELECT o.opportunity_id, o.customer_id, c.name AS customer_name, p.name AS product, o.product_id,
       o.description, o.potential_arr_pence, o.probability,
       CAST(ROUND(o.potential_arr_pence * o.probability) AS INTEGER) AS expected_value_pence,
       o.stage, o.expected_close_date, o.owner_id, ow.name AS owner_name, o.next_action,
       o.created_date, o.closed_date,
       CASE WHEN o.stage IN ('Closed Won', 'Closed Lost') THEN 0 ELSE 1 END AS is_open
FROM opportunities o
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p ON p.product_id = o.product_id
JOIN owners ow ON ow.owner_id = o.owner_id;

CREATE VIEW v_last_contact AS
SELECT customer_id, MAX(activity_date) AS last_contact_date
FROM activities
WHERE customer_id IS NOT NULL
  AND activity_type IN ('Meeting', 'Call', 'Email', 'Demo')
  AND activity_date <= {{AS_OF}}
GROUP BY customer_id;

CREATE VIEW v_onboarding AS
SELECT c.customer_id,
       COUNT(m.milestone_id) AS milestones_total,
       SUM(CASE WHEN m.completed_date IS NOT NULL THEN 1 ELSE 0 END) AS milestones_done,
       MAX(CASE WHEN m.is_first_value = 1 AND m.completed_date IS NOT NULL
                THEN {{DAYS(m.completed_date, c.customer_since)}} END) AS ttfv_days
FROM customers c
LEFT JOIN onboarding_milestones m ON m.customer_id = c.customer_id
GROUP BY c.customer_id;

CREATE VIEW v_feature_adoption AS
SELECT fu.customer_id, c.name AS customer_name, fc.product_id, p.name AS vertical, fc.feature_id,
       fc.name AS feature, fu.adopted, fu.usage_count_90d, fu.first_used_date
FROM feature_usage fu
JOIN feature_catalogue fc ON fc.feature_id = fu.feature_id
JOIN customers c ON c.customer_id = fu.customer_id
JOIN products p ON p.product_id = fc.product_id;

-- One row per subscription customer: the basis of every portfolio KPI
CREATE VIEW v_customer_kpis AS
SELECT c.customer_id,
       c.name AS customer_name,
       p.name AS vertical,
       c.segment,
       c.hq_region,
       c.owner_id,
       COALESCE(ow.name, 'Unassigned') AS owner_name,
       ct.arr_pence,
       s.licensed_seats,
       s.active_users,
       CASE WHEN s.licensed_seats > 0 THEN 100.0 * s.active_users / s.licensed_seats END AS adoption_pct,
       ct.renewal_date,
       ct.days_to_renewal,
       ct.status AS contract_status,
       h.score AS health_score,
       h.category AS health_category,
       h.components_available,
       COALESCE(pl.potential_pence, 0) AS potential_expansion_pence,
       COALESCE(pl.weighted_pence, 0) AS weighted_expansion_pence,
       COALESCE(pl.open_count, 0) AS open_opportunities,
       lc.last_contact_date,
       ob.ttfv_days,
       ob.milestones_done,
       ob.milestones_total
FROM customers c
JOIN products p ON p.product_id = c.product_id
JOIN subscriptions s ON s.customer_id = c.customer_id
JOIN v_current_contracts ct ON ct.customer_id = c.customer_id
LEFT JOIN owners ow ON ow.owner_id = c.owner_id
LEFT JOIN v_customer_health h ON h.customer_id = c.customer_id
LEFT JOIN v_last_contact lc ON lc.customer_id = c.customer_id
LEFT JOIN v_onboarding ob ON ob.customer_id = c.customer_id
LEFT JOIN (
    SELECT customer_id,
           SUM(potential_arr_pence) AS potential_pence,
           SUM(expected_value_pence) AS weighted_pence,
           COUNT(*) AS open_count
    FROM v_pipeline
    WHERE is_open = 1
    GROUP BY customer_id
) pl ON pl.customer_id = c.customer_id
WHERE c.status = 'Active';

CREATE VIEW v_renewals AS
SELECT customer_id, customer_name, vertical, owner_name, arr_pence, renewal_date, days_to_renewal,
       health_score, health_category
FROM v_customer_kpis;

-- Unfiltered portfolio totals (trading counterparties are not in v_customer_kpis, so contribute £0)
CREATE VIEW v_portfolio_kpis AS
SELECT SUM(arr_pence) AS arr_pence,
       SUM(licensed_seats) AS licensed_seats,
       SUM(active_users) AS active_users,
       100.0 * SUM(active_users) / SUM(licensed_seats) AS adoption_pct,
       SUM(CASE WHEN health_category = 'At Risk' THEN arr_pence ELSE 0 END) AS revenue_at_risk_pence,
       SUM(potential_expansion_pence) AS potential_expansion_pence,
       SUM(weighted_expansion_pence) AS weighted_pipeline_pence,
       COUNT(*) AS accounts
FROM v_customer_kpis;

-- Trading counterparties: relationship view. Notional is NOT revenue.
CREATE VIEW v_counterparty_summary AS
SELECT cp.counterparty_id,
       cp.name AS counterparty_name,
       cp.region,
       cp.relationship_status,
       cp.approval_status,
       cp.primary_products,
       COALESCE(ow.name, 'Unassigned') AS owner_name,
       cp.owner_id,
       COALESCE(ta.trades_12m, 0) AS trades_12m,
       COALESCE(ta.notional_usd_12m, 0) AS notional_usd_12m,
       COALESCE(iss.open_issues, 0) AS open_issues,
       lc.last_contact_date
FROM counterparties cp
LEFT JOIN owners ow ON ow.owner_id = cp.owner_id
LEFT JOIN (
    SELECT counterparty_id, SUM(trade_count) AS trades_12m, SUM(notional_usd) AS notional_usd_12m
    FROM trading_activity
    WHERE month > {{MONTH_ADD({{AS_OF}}, -12)}}
    GROUP BY counterparty_id
) ta ON ta.counterparty_id = cp.counterparty_id
LEFT JOIN (
    SELECT counterparty_id, COUNT(*) AS open_issues
    FROM counterparty_issues
    WHERE status <> 'Resolved'
    GROUP BY counterparty_id
) iss ON iss.counterparty_id = cp.counterparty_id
LEFT JOIN (
    SELECT counterparty_id, MAX(activity_date) AS last_contact_date
    FROM activities
    WHERE counterparty_id IS NOT NULL AND activity_type IN ('Meeting', 'Call', 'Email', 'Demo')
      AND activity_date <= {{AS_OF}}
    GROUP BY counterparty_id
) lc ON lc.counterparty_id = cp.counterparty_id
