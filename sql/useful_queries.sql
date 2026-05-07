-- Useful AIMD Sentinel inspection queries.
\pset pager off

-- The devices table uses primary_product_code, not product_code.
SELECT id, canonical_name, manufacturer, primary_product_code
FROM devices
ORDER BY latest_decision_date DESC NULLS LAST
LIMIT 20;

-- Counts by source table.
SELECT 'devices' AS table_name, COUNT(*) FROM devices
UNION ALL SELECT 'authorizations', COUNT(*) FROM authorizations
UNION ALL SELECT 'adverse_events', COUNT(*) FROM adverse_events
UNION ALL SELECT 'enforcement_actions', COUNT(*) FROM enforcement_actions
UNION ALL SELECT 'recall_records', COUNT(*) FROM recall_records
UNION ALL SELECT 'llm_extractions', COUNT(*) FROM llm_extractions;

-- Devices with linked event, enforcement, and recall counts.
SELECT
    d.canonical_name,
    d.manufacturer,
    d.primary_product_code,
    COUNT(DISTINCT ae.id) AS adverse_event_count,
    COUNT(DISTINCT ea.id) AS enforcement_count,
    COUNT(DISTINCT rr.id) AS recall_count
FROM devices d
LEFT JOIN device_adverse_event_links ael ON d.id = ael.device_id
LEFT JOIN adverse_events ae ON ae.id = ael.adverse_event_id
LEFT JOIN device_enforcement_links eel ON d.id = eel.device_id
LEFT JOIN enforcement_actions ea ON ea.id = eel.enforcement_action_id
LEFT JOIN device_recall_links rrl ON d.id = rrl.device_id
LEFT JOIN recall_records rr ON rr.id = rrl.recall_record_id
GROUP BY d.id, d.canonical_name, d.manufacturer, d.primary_product_code
ORDER BY adverse_event_count DESC, enforcement_count DESC, recall_count DESC;

-- Inspect linked adverse-event previews.
SELECT
    d.canonical_name,
    ae.report_number,
    ae.event_type,
    ae.date_received,
    ae.brand_name,
    ae.product_code,
    l.match_method,
    l.match_confidence,
    l.needs_review,
    LEFT(regexp_replace(coalesce(ae.narrative_text, ''), '\s+', ' ', 'g'), 240) AS narrative_preview
FROM adverse_events ae
JOIN device_adverse_event_links l ON ae.id = l.adverse_event_id
JOIN devices d ON d.id = l.device_id
ORDER BY l.needs_review DESC, ae.date_received DESC NULLS LAST
LIMIT 25;
