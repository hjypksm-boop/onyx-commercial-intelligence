-- Headline KPIs for the selected subscription accounts (trading counterparties are never in v_customer_kpis).
SELECT COUNT(*) AS accounts,
       COALESCE(SUM(arr_pence), 0) AS arr_pence,
       COALESCE(SUM(licensed_seats), 0) AS licensed_seats,
       COALESCE(SUM(active_users), 0) AS active_users,
       CASE WHEN SUM(licensed_seats) > 0 THEN 100.0 * SUM(active_users) / SUM(licensed_seats) END AS adoption_pct,
       COALESCE(SUM(CASE WHEN health_category = 'At Risk' THEN arr_pence ELSE 0 END), 0) AS revenue_at_risk_pence,
       COALESCE(SUM(CASE WHEN health_category = 'At Risk' THEN 1 ELSE 0 END), 0) AS at_risk_accounts,
       COALESCE(SUM(potential_expansion_pence), 0) AS potential_expansion_pence,
       COALESCE(SUM(weighted_expansion_pence), 0) AS weighted_pipeline_pence
FROM v_customer_kpis
WHERE (:all_verticals = 1 OR vertical IN :verticals)
  AND (:all_owners = 1 OR owner_name IN :owners)
  AND (:all_health = 1 OR health_category IN :health)
