-- Renewal forecast: ARR renewing in the next :days days by renewal month and calculated health category
SELECT substr(renewal_date, 1, 7) AS renewal_month,
       health_category,
       COUNT(*) AS accounts,
       SUM(arr_pence) AS arr_pence
FROM v_renewals
WHERE days_to_renewal BETWEEN 0 AND :days
GROUP BY substr(renewal_date, 1, 7), health_category
ORDER BY renewal_month, health_category
