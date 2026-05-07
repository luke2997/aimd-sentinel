-- Useful checks after ingestion

-- 1) Seed device overview
SELECT
    d.canonical_name,
    d.manufacturer,
    d.latest_submission_number,
    d.latest_decision_date,
    d.primary_product_code,
    count(DISTINCT a.id) AS authorization_records,
    count(DISTINCT ae.id) AS linked_adverse_events,
    count(DISTINCT ea.id) AS linked_enforcement_actions,
    count(DISTINCT rr.id) AS linked_recall_records
FROM devices d
LEFT JOIN device_authorization_links dal ON dal.device_id = d.id
LEFT JOIN authorizations a ON a.id = dal.authorization_id
LEFT JOIN device_adverse_event_links dael ON dael.device_id = d.id
LEFT JOIN adverse_events ae ON ae.id = dael.adverse_event_id
LEFT JOIN device_enforcement_links del ON del.device_id = d.id
LEFT JOIN enforcement_actions ea ON ea.id = del.enforcement_action_id
LEFT JOIN device_recall_links drl ON drl.device_id = d.id
LEFT JOIN recall_records rr ON rr.id = drl.recall_record_id
GROUP BY d.id
ORDER BY d.latest_decision_date DESC NULLS LAST;

-- 2) Review low-confidence or ambiguous links first
SELECT
    d.canonical_name,
    ae.report_number,
    ae.event_type,
    ae.date_received,
    ae.brand_name,
    ae.product_code,
    l.match_method,
    l.match_confidence,
    l.needs_review
FROM device_adverse_event_links l
JOIN devices d ON d.id = l.device_id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
WHERE l.needs_review = true OR l.match_confidence < 0.85
ORDER BY l.match_confidence ASC, ae.date_received DESC NULLS LAST;

-- 3) Narrative search for AI-ish failure words within linked event reports
SELECT
    d.canonical_name,
    ae.report_number,
    ae.event_type,
    ae.date_received,
    left(ae.narrative_text, 500) AS narrative_preview
FROM adverse_events ae
JOIN device_adverse_event_links l ON l.adverse_event_id = ae.id
JOIN devices d ON d.id = l.device_id
WHERE to_tsvector('english', coalesce(ae.narrative_text, '')) @@ plainto_tsquery('english', 'false alert missed delayed algorithm software')
ORDER BY ae.date_received DESC NULLS LAST;
