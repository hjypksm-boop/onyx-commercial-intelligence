-- Retention cohort: customers with a contract active 12 months before the as-of date,
-- their ARR then (start) and their current-contract ARR now (0 if churned).
-- GRR = (start − downsell − churn) ÷ start; NRR = current ÷ start.
WITH a AS (SELECT {{AS_OF}} AS as_of),
start_c AS (
    SELECT ct.customer_id, SUM(ct.arr_pence) AS start_arr_pence
    FROM contracts ct CROSS JOIN a
    WHERE ct.start_date <= {{ADD_DAYS(a.as_of, -365)}}
      AND ct.renewal_date > {{ADD_DAYS(a.as_of, -365)}}
    GROUP BY ct.customer_id
),
now_c AS (
    SELECT ct.customer_id, SUM(ct.arr_pence) AS current_arr_pence
    FROM contracts ct JOIN customers c ON c.customer_id = ct.customer_id
    WHERE ct.is_current = 1 AND c.status = 'Active'
    GROUP BY ct.customer_id
)
SELECT c.customer_id, c.name AS customer_name, s.start_arr_pence, COALESCE(n.current_arr_pence, 0) AS current_arr_pence
FROM start_c s
JOIN customers c ON c.customer_id = s.customer_id
LEFT JOIN now_c n ON n.customer_id = s.customer_id
ORDER BY c.name
