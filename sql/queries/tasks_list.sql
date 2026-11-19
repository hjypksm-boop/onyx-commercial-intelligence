-- All tasks with related account and owner names
SELECT t.task_id, t.title, t.category, t.priority, t.status, t.due_date, t.notes, t.source, t.created_on, t.completed_on,
       t.owner_id, ow.name AS owner_name,
       t.customer_id, t.counterparty_id,
       COALESCE(c.name, cp.name) AS account_name,
       CASE WHEN t.counterparty_id IS NOT NULL THEN 'Counterparty' WHEN t.customer_id IS NOT NULL THEN 'Customer' ELSE 'Internal' END AS account_type,
       CASE WHEN t.status = 'Done' THEN 'Done'
            WHEN t.due_date < {{AS_OF}} THEN 'Overdue'
            WHEN t.due_date = {{AS_OF}} THEN 'Due today'
            ELSE 'Upcoming' END AS bucket
FROM tasks t
JOIN owners ow ON ow.owner_id = t.owner_id
LEFT JOIN customers c ON c.customer_id = t.customer_id
LEFT JOIN counterparties cp ON cp.counterparty_id = t.counterparty_id
ORDER BY CASE t.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, t.due_date
