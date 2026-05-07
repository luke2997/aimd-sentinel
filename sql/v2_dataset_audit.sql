\pset pager off

\echo '1) Dataset cohort breakdown from FDA AI seed source records'
SELECT
  COALESCE(sr.raw_json->>'cohort', 'unlabelled_or_v1') AS cohort,
  COUNT(*) AS devices
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
GROUP BY 1
ORDER BY devices DESC;

\echo '2) Link quality by cohort: adverse events'
SELECT
  COALESCE(sr.raw_json->>'cohort', 'unlabelled_or_v1') AS cohort,
  COUNT(DISTINCT d.id) AS devices,
  COUNT(l.id) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.id) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  COUNT(l.id) AS total_events
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY 1
ORDER BY high_conf_events DESC, review_events DESC;

\echo '3) Candidate public demos: high-confidence events, low review leakage'
SELECT
  d.canonical_name,
  d.manufacturer,
  d.latest_submission_number,
  d.latest_decision_date,
  d.primary_product_code,
  COALESCE(sr.raw_json->>'cohort', 'unlabelled_or_v1') AS cohort,
  COUNT(l.id) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.id) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events
FROM devices d
LEFT JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY d.id, sr.raw_json
HAVING COUNT(l.id) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) >= 5
ORDER BY high_conf_events DESC, review_events ASC
LIMIT 30;

\echo '4) Negative controls: should be mostly hardware / unlikely AI-related after extraction'
SELECT
  d.canonical_name,
  d.manufacturer,
  COUNT(l.id) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(l.id) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events
FROM devices d
JOIN source_records sr ON sr.id = d.fda_ai_list_source_record_id
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
WHERE sr.raw_json->>'cohort' = 'negative_control_hardware_family'
GROUP BY d.id
ORDER BY high_conf_events DESC, review_events DESC;

\echo '5) Weak aliases to review manually'
SELECT
  d.canonical_name,
  da.alias,
  da.alias_type,
  da.confidence
FROM device_aliases da
JOIN devices d ON d.id = da.device_id
WHERE length(da.alias) <= 4
   OR lower(da.alias) IN ('ai','air','dl','mr','mri','ct','system','software','device','imaging')
ORDER BY d.canonical_name, da.alias;
