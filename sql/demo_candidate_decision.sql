\pset pager off

\echo '1) Positive software-demo candidates by high-confidence adverse events'
SELECT
    d.canonical_name,
    d.manufacturer,
    d.latest_submission_number,
    d.latest_decision_date,
    d.primary_product_code,
    COUNT(*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
    COUNT(*) FILTER (WHERE l.needs_review = true) AS review_events,
    COUNT(l.id) AS total_events,
    STRING_AGG(DISTINCT NULLIF(ae.brand_name, ''), ' | ') FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS example_brands
FROM devices d
LEFT JOIN device_adverse_event_links l ON d.id = l.device_id
LEFT JOIN adverse_events ae ON ae.id = l.adverse_event_id
GROUP BY d.id
ORDER BY high_conf_events DESC, review_events ASC, d.latest_decision_date DESC NULLS LAST
LIMIT 20;

\echo '2) High-confidence enforcement links to sanity-check'
SELECT
    d.canonical_name,
    ea.recalling_firm,
    ea.product_code,
    l.match_method,
    l.match_confidence,
    l.needs_review,
    LEFT(ea.product_description, 140) AS product_description,
    LEFT(ea.reason_for_recall, 180) AS reason
FROM devices d
JOIN device_enforcement_links l ON d.id = l.device_id
JOIN enforcement_actions ea ON ea.id = l.enforcement_action_id
WHERE l.needs_review = false AND l.match_confidence >= 0.85
ORDER BY d.canonical_name, ea.recall_initiation_date DESC NULLS LAST
LIMIT 80;

\echo '3) Red Dot enforcement/recall after strict gate: should not show unrelated electrode/corrosion as high confidence'
SELECT
    d.canonical_name,
    ea.recalling_firm,
    ea.product_code,
    l.match_method,
    l.match_confidence,
    l.needs_review,
    LEFT(ea.product_description, 160) AS product_description,
    LEFT(ea.reason_for_recall, 200) AS reason
FROM devices d
JOIN device_enforcement_links l ON d.id = l.device_id
JOIN enforcement_actions ea ON ea.id = l.enforcement_action_id
WHERE d.canonical_name ILIKE '%Red Dot%'
ORDER BY l.needs_review, l.match_confidence DESC;
