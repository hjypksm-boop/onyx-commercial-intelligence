-- Recent customer & counterparty activity within the selected date range
SELECT a.activity_id, a.activity_date, a.activity_type, a.subject, a.summary, a.sentiment,
       COALESCE(c.name, cp.name) AS account_name, a.customer_id, a.counterparty_id,
       ow.name AS owner_name
FROM activities a
LEFT JOIN customers c ON c.customer_id = a.customer_id
LEFT JOIN counterparties cp ON cp.counterparty_id = a.counterparty_id
LEFT JOIN owners ow ON ow.owner_id = a.owner_id
WHERE a.activity_date BETWEEN :start AND :end
ORDER BY a.activity_date DESC, a.activity_id DESC
