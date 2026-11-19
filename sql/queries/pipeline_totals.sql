-- Pipeline totals. Potential expansion = open (not Closed Won/Lost) opportunities, unweighted.
-- Weighted pipeline = Σ potential × probability. Booked new ACV = Closed Won (all time and on the as-of date).
SELECT
    COALESCE(SUM(CASE WHEN is_open = 1 THEN potential_arr_pence ELSE 0 END), 0) AS potential_expansion_pence,
    COALESCE(SUM(CASE WHEN is_open = 1 THEN expected_value_pence ELSE 0 END), 0) AS weighted_pipeline_pence,
    COALESCE(SUM(CASE WHEN is_open = 1 THEN 1 ELSE 0 END), 0) AS open_count,
    COALESCE(SUM(CASE WHEN stage = 'Closed Won' THEN potential_arr_pence ELSE 0 END), 0) AS booked_acv_all_time_pence,
    COALESCE(SUM(CASE WHEN stage = 'Closed Won' AND closed_date = {{AS_OF}} THEN potential_arr_pence ELSE 0 END), 0) AS booked_acv_today_pence
FROM v_pipeline
