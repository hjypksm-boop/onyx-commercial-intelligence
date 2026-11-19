-- Monthly adoption trend by vertical: Σ MAU ÷ Σ licensed seats for the selected accounts and date range
SELECT u.month,
       k.vertical,
       SUM(u.mau) AS mau,
       SUM(k.licensed_seats) AS licensed_seats,
       100.0 * SUM(u.mau) / SUM(k.licensed_seats) AS adoption_pct
FROM v_monthly_usage u
JOIN v_customer_kpis k ON k.customer_id = u.customer_id
WHERE u.month >= :start_month AND u.month <= :end_month
  AND (:all_verticals = 1 OR k.vertical IN :verticals)
  AND (:all_owners = 1 OR k.owner_name IN :owners)
  AND (:all_health = 1 OR k.health_category IN :health)
GROUP BY u.month, k.vertical
ORDER BY u.month, k.vertical
