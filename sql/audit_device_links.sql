-- AIMD Sentinel QA: audit record-device linkage before showing dossiers externally.
\pset pager off

\echo '1) Link method distribution by device: adverse events'
SELECT
  d.canonical_name,
  l.match_method,
  l.needs_review,
  ROUND(l.match_confidence::numeric, 3) AS match_confidence,
  COUNT(*) AS records
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY d.canonical_name, l.match_method, l.needs_review, ROUND(l.match_confidence::numeric, 3)
ORDER BY d.canonical_name, records DESC;

\echo '2) Link method distribution by device: enforcement'
SELECT
  d.canonical_name,
  l.match_method,
  l.needs_review,
  ROUND(l.match_confidence::numeric, 3) AS match_confidence,
  COUNT(*) AS records
FROM devices d
JOIN device_enforcement_links l ON l.device_id = d.id
GROUP BY d.canonical_name, l.match_method, l.needs_review, ROUND(l.match_confidence::numeric, 3)
ORDER BY d.canonical_name, records DESC;

\echo '3) Link method distribution by device: recall'
SELECT
  d.canonical_name,
  l.match_method,
  l.needs_review,
  ROUND(l.match_confidence::numeric, 3) AS match_confidence,
  COUNT(*) AS records
FROM devices d
JOIN device_recall_links l ON l.device_id = d.id
GROUP BY d.canonical_name, l.match_method, l.needs_review, ROUND(l.match_confidence::numeric, 3)
ORDER BY d.canonical_name, records DESC;

\echo '4) Best demo candidates: high-confidence adverse events only'
WITH counts AS (
  SELECT
    d.id,
    d.canonical_name,
    d.manufacturer,
    COUNT(*) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS high_conf_events,
    COUNT(*) FILTER (WHERE l.needs_review = TRUE OR l.match_confidence < 0.85) AS review_events,
    COUNT(*) AS total_events
  FROM devices d
  LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
  GROUP BY d.id, d.canonical_name, d.manufacturer
)
SELECT *
FROM counts
ORDER BY high_conf_events DESC, review_events ASC, canonical_name;

\echo '5) Potential leakage examples: low-confidence/review adverse-event links'
SELECT
  d.canonical_name,
  ae.report_number,
  ae.date_received,
  ae.brand_name,
  ae.manufacturer_name,
  ae.product_code,
  l.match_method,
  l.match_confidence,
  l.needs_review,
  LEFT(REGEXP_REPLACE(COALESCE(ae.narrative_text,''), '\s+', ' ', 'g'), 260) AS narrative_preview
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
WHERE l.needs_review = TRUE OR l.match_confidence < 0.85
ORDER BY d.canonical_name, ae.date_received DESC NULLS LAST
LIMIT 80;

\echo '6) Extraction coverage: high-confidence adverse events only'
SELECT
  d.canonical_name,
  COUNT(DISTINCT ae.id) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS high_conf_linked_events,
  COUNT(DISTINCT lx.id) FILTER (WHERE l.match_confidence >= 0.85 AND l.needs_review = FALSE) AS extracted_high_conf_events,
  COUNT(DISTINCT ae.id) FILTER (WHERE l.needs_review = TRUE OR l.match_confidence < 0.85) AS review_events
FROM devices d
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
LEFT JOIN adverse_events ae ON ae.id = l.adverse_event_id
LEFT JOIN llm_extractions lx
  ON lx.source_table = 'adverse_events'
 AND lx.source_id = ae.id
 AND lx.extraction_type = 'adverse_event_failure_mode'
GROUP BY d.canonical_name
ORDER BY high_conf_linked_events DESC, review_events ASC;
