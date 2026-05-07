\pset pager off
\echo '1) Dataset v2.1 cohort breakdown'
SELECT sr.raw_json->>'cohort' AS cohort, COUNT(*) AS devices
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
GROUP BY 1
ORDER BY 2 DESC;

\echo ''
\echo '2) Link quality by cohort: adverse events'
SELECT
  COALESCE(sr.raw_json->>'cohort','unknown') AS cohort,
  COUNT(DISTINCT d.id) AS devices,
  COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  COUNT(l.*) AS total_events
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY 1
ORDER BY high_conf_events DESC, total_events DESC;

\echo ''
\echo '3) Public demo candidates: high-confidence events with manageable review leakage'
SELECT
  d.canonical_name,
  d.manufacturer,
  d.latest_submission_number,
  d.latest_decision_date,
  d.primary_product_code,
  COALESCE(sr.raw_json->>'cohort','unknown') AS cohort,
  COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  STRING_AGG(DISTINCT LEFT(COALESCE(ae.brand_name,''), 55), ' | ') FILTER (WHERE ae.brand_name IS NOT NULL) AS example_brands
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
LEFT JOIN adverse_events ae ON ae.id = l.adverse_event_id
GROUP BY d.id, sr.raw_json
HAVING COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) >= 2
ORDER BY high_conf_events DESC, review_events ASC
LIMIT 30;

\echo ''
\echo '4) Software-exact candidates that still have zero high-confidence links after ingestion'
SELECT
  d.canonical_name,
  d.manufacturer,
  sr.raw_json->>'best_alias' AS best_alias,
  sr.raw_json->>'exact_brand_event_count' AS precheck_brand_count,
  sr.raw_json->>'exact_text_event_count' AS precheck_text_count,
  COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
WHERE COALESCE(sr.raw_json->>'cohort','') = 'software_exact_match_candidate'
GROUP BY d.id, sr.raw_json
HAVING COUNT(l.*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) = 0
ORDER BY review_events DESC
LIMIT 20;
