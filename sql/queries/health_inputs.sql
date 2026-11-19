-- Raw inputs for the customer health score, evaluated at a point in time.
-- Used verbatim as the body of view v_health_inputs ({{AS_OF}} = app_config.as_of_date)
-- and as a parameterised query (:as_of) for historical month-end snapshots.
WITH a AS (
    SELECT {{AS_OF}} AS as_of
),
m AS (
    SELECT ud.customer_id, substr(ud.usage_date, 1, 7) AS month, COUNT(DISTINCT ud.user_key) AS mau
    FROM usage_daily ud CROSS JOIN a
    WHERE ud.usage_date <= a.as_of
      AND ud.logins > 0
      AND substr(ud.usage_date, 1, 7) >= {{MONTH_ADD(a.as_of, -5)}}
    GROUP BY ud.customer_id, substr(ud.usage_date, 1, 7)
),
trend AS (
    SELECT m.customer_id,
           SUM(CASE WHEN m.month >= {{MONTH_ADD(a.as_of, -2)}} THEN m.mau ELSE 0 END) / 3.0 AS mau_last3_avg,
           SUM(CASE WHEN m.month <  {{MONTH_ADD(a.as_of, -2)}} THEN m.mau ELSE 0 END) / 3.0 AS mau_prev3_avg,
           SUM(CASE WHEN m.month <  {{MONTH_ADD(a.as_of, -2)}} THEN 1 ELSE 0 END) AS prev3_months_with_data,
           SUM(CASE WHEN m.month =  {{MONTH_ADD(a.as_of, 0)}} THEN m.mau ELSE 0 END) AS mau_current_month
    FROM m CROSS JOIN a
    GROUP BY m.customer_id
),
tk AS (
    SELECT t.customer_id,
           SUM(CASE WHEN t.opened_date <= a.as_of AND (t.closed_date IS NULL OR t.closed_date > a.as_of)
                     AND t.severity IN ('High', 'Critical') THEN 1 ELSE 0 END) AS open_high,
           SUM(CASE WHEN t.opened_date <= a.as_of AND (t.closed_date IS NULL OR t.closed_date > a.as_of)
                     AND t.severity = 'Medium' THEN 1 ELSE 0 END) AS open_medium,
           SUM(CASE WHEN t.opened_date <= a.as_of AND (t.closed_date IS NULL OR t.closed_date > a.as_of)
                     AND t.severity = 'Low' THEN 1 ELSE 0 END) AS open_low,
           SUM(CASE WHEN t.sla_breached = 1 AND t.opened_date <= a.as_of
                     AND t.opened_date > {{ADD_DAYS(a.as_of, -90)}} THEN 1 ELSE 0 END) AS sla_breaches_90d
    FROM support_tickets t CROSS JOIN a
    GROUP BY t.customer_id
),
co AS (
    SELECT x.customer_id,
           MAX(x.activity_date) AS last_contact_date,
           MAX(CASE WHEN x.activity_type = 'Meeting' THEN x.activity_date END) AS last_meeting_date
    FROM activities x CROSS JOIN a
    WHERE x.customer_id IS NOT NULL
      AND x.activity_date <= a.as_of
      AND x.activity_type IN ('Meeting', 'Call', 'Email', 'Demo')
    GROUP BY x.customer_id
),
se AS (
    SELECT r.customer_id, AVG(r.sentiment * 1.0) AS sentiment_avg, COUNT(*) AS sentiment_n
    FROM (
        SELECT x.customer_id, x.sentiment,
               ROW_NUMBER() OVER (PARTITION BY x.customer_id ORDER BY x.activity_date DESC, x.activity_id DESC) AS rn
        FROM activities x CROSS JOIN a
        WHERE x.customer_id IS NOT NULL
          AND x.activity_type = 'Meeting'
          AND x.sentiment IS NOT NULL
          AND x.activity_date <= a.as_of
    ) r
    WHERE r.rn <= 3
    GROUP BY r.customer_id
)
SELECT c.customer_id,
       c.name AS customer_name,
       a.as_of,
       s.licensed_seats,
       s.active_users,
       ct.renewal_date,
       {{DAYS(ct.renewal_date, a.as_of)}} AS days_to_renewal,
       tr.mau_last3_avg,
       tr.mau_prev3_avg,
       COALESCE(tr.prev3_months_with_data, 0) AS prev3_months_with_data,
       COALESCE(tr.mau_current_month, 0) AS mau_current_month,
       COALESCE(tk.open_high, 0) AS open_high,
       COALESCE(tk.open_medium, 0) AS open_medium,
       COALESCE(tk.open_low, 0) AS open_low,
       COALESCE(tk.sla_breaches_90d, 0) AS sla_breaches_90d,
       co.last_contact_date,
       {{DAYS(a.as_of, co.last_contact_date)}} AS days_since_contact,
       co.last_meeting_date,
       {{DAYS(a.as_of, co.last_meeting_date)}} AS days_since_meeting,
       se.sentiment_avg,
       COALESCE(se.sentiment_n, 0) AS sentiment_n
FROM customers c
CROSS JOIN a
JOIN subscriptions s ON s.customer_id = c.customer_id
JOIN contracts ct ON ct.customer_id = c.customer_id AND ct.is_current = 1
LEFT JOIN trend tr ON tr.customer_id = c.customer_id
LEFT JOIN tk ON tk.customer_id = c.customer_id
LEFT JOIN co ON co.customer_id = c.customer_id
LEFT JOIN se ON se.customer_id = c.customer_id
WHERE c.status = 'Active'
