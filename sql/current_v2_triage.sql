\pset pager off
\echo '1) Current dataset cohort counts'
SELECT sr.raw_json->>'cohort' AS cohort, COUNT(*) AS devices
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
GROUP BY 1
ORDER BY 2 DESC;

\echo ''
\echo '2) Current software-first rows with most review-only adverse-event leads'
SELECT
  d.canonical_name,
  d.manufacturer,
  d.latest_submission_number,
  d.latest_decision_date,
  d.primary_product_code,
  COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  STRING_AGG(DISTINCT LEFT(COALESCE(ae.brand_name,''), 45), ' | ') FILTER (WHERE ae.brand_name IS NOT NULL) AS example_brands
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
LEFT JOIN adverse_events ae ON ae.id = l.adverse_event_id
WHERE COALESCE(sr.raw_json->>'cohort','') LIKE '%software%'
GROUP BY d.id
ORDER BY review_events DESC, high_conf_events DESC
LIMIT 25;

\echo ''
\echo '3) High-confidence event candidates currently available'
SELECT
  d.canonical_name,
  d.manufacturer,
  sr.raw_json->>'cohort' AS cohort,
  COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  STRING_AGG(DISTINCT LEFT(COALESCE(ae.brand_name,''), 45), ' | ') FILTER (WHERE ae.brand_name IS NOT NULL) AS example_brands
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
LEFT JOIN adverse_events ae ON ae.id = l.adverse_event_id
GROUP BY d.id, sr.raw_json
HAVING COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) > 0
ORDER BY high_conf_events DESC, review_events ASC
LIMIT 25;
