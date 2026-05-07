\pset pager off

-- 1) Extraction counts by device and relatedness
SELECT
    d.canonical_name,
    lx.json_output->>'possible_ai_relatedness' AS ai_relatedness,
    COUNT(*) AS records
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
JOIN LATERAL (
    SELECT json_output, prompt_version, created_at
    FROM llm_extractions x
    WHERE x.source_table = 'adverse_events'
      AND x.source_id = ae.id
      AND x.extraction_type = 'adverse_event_failure_mode'
    ORDER BY x.created_at DESC
    LIMIT 1
) lx ON TRUE
WHERE l.match_confidence >= 0.85
  AND l.needs_review = FALSE
GROUP BY d.canonical_name, lx.json_output->>'possible_ai_relatedness'
ORDER BY d.canonical_name, records DESC;

-- 2) Candidate false positives: cases classified possible/likely but with hardware-heavy language.
SELECT
    d.canonical_name,
    ae.report_number,
    ae.date_received,
    ae.event_type,
    ae.brand_name,
    lx.json_output->>'possible_ai_relatedness' AS ai_relatedness,
    lx.json_output->>'classifier_note' AS classifier_note,
    lx.json_output->'failure_modes' AS failure_modes,
    LEFT(ae.narrative_text, 380) AS narrative_preview
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
JOIN LATERAL (
    SELECT json_output, created_at
    FROM llm_extractions x
    WHERE x.source_table = 'adverse_events'
      AND x.source_id = ae.id
      AND x.extraction_type = 'adverse_event_failure_mode'
    ORDER BY x.created_at DESC
    LIMIT 1
) lx ON TRUE
WHERE l.match_confidence >= 0.85
  AND l.needs_review = FALSE
  AND lx.json_output->>'possible_ai_relatedness' IN ('likely','possible')
ORDER BY ae.date_received DESC NULLS LAST
LIMIT 50;

-- 3) Link-gating summary for the current seed devices.
SELECT
    d.canonical_name,
    SUM(CASE WHEN l.match_confidence >= 0.85 AND l.needs_review = FALSE THEN 1 ELSE 0 END) AS high_conf_events,
    SUM(CASE WHEN l.match_confidence < 0.85 OR l.needs_review = TRUE THEN 1 ELSE 0 END) AS review_events,
    COUNT(*) AS total_events
FROM devices d
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY d.id, d.canonical_name
ORDER BY high_conf_events DESC, review_events DESC, d.canonical_name;
