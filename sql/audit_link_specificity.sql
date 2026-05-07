\pset pager off

\echo '1) High-confidence vs review adverse-event links after specificity regrade'
SELECT
    d.canonical_name,
    d.manufacturer,
    COUNT(*) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS high_conf_events,
    COUNT(*) FILTER (WHERE l.match_confidence < 0.85 OR l.needs_review = TRUE) AS review_events,
    COUNT(*) AS total_events
FROM devices d
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY d.id, d.canonical_name, d.manufacturer
ORDER BY high_conf_events DESC, review_events DESC, d.canonical_name;

\echo '2) Link method distribution: adverse events'
SELECT
    d.canonical_name,
    l.match_method,
    l.needs_review,
    l.match_confidence,
    COUNT(*) AS records
FROM device_adverse_event_links l
JOIN devices d ON d.id = l.device_id
GROUP BY d.canonical_name, l.match_method, l.needs_review, l.match_confidence
ORDER BY d.canonical_name, records DESC;

\echo '3) High-confidence event examples that will appear in public dossier'
SELECT
    d.canonical_name,
    ae.report_number,
    ae.date_received,
    ae.brand_name,
    ae.product_code,
    l.match_method,
    l.matched_on,
    l.match_confidence,
    LEFT(ae.narrative_text, 220) AS narrative_preview
FROM device_adverse_event_links l
JOIN devices d ON d.id = l.device_id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE
ORDER BY d.canonical_name, ae.date_received DESC NULLS LAST
LIMIT 50;

\echo '4) Review-only event examples: should NOT be counted as device-specific'
SELECT
    d.canonical_name,
    ae.report_number,
    ae.date_received,
    ae.brand_name,
    ae.product_code,
    l.match_method,
    l.matched_on,
    l.match_confidence,
    l.needs_review,
    LEFT(ae.narrative_text, 220) AS narrative_preview
FROM device_adverse_event_links l
JOIN devices d ON d.id = l.device_id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
WHERE l.match_confidence < 0.85 OR l.needs_review = TRUE
ORDER BY d.canonical_name, ae.date_received DESC NULLS LAST
LIMIT 50;

\echo '5) Enforcement specificity counts'
SELECT
    d.canonical_name,
    COUNT(*) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS high_conf_enforcement,
    COUNT(*) FILTER (WHERE l.match_confidence < 0.85 OR l.needs_review = TRUE) AS review_enforcement,
    COUNT(*) AS total_enforcement
FROM devices d
LEFT JOIN device_enforcement_links l ON l.device_id = d.id
GROUP BY d.id, d.canonical_name
ORDER BY high_conf_enforcement DESC, review_enforcement DESC, d.canonical_name;

\echo '6) Recall specificity counts'
SELECT
    d.canonical_name,
    COUNT(*) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS high_conf_recalls,
    COUNT(*) FILTER (WHERE l.match_confidence < 0.85 OR l.needs_review = TRUE) AS review_recalls,
    COUNT(*) AS total_recalls
FROM devices d
LEFT JOIN device_recall_links l ON l.device_id = d.id
GROUP BY d.id, d.canonical_name
ORDER BY high_conf_recalls DESC, review_recalls DESC, d.canonical_name;
