-- Review LLM / heuristic adverse-event failure-mode extractions.
\pset pager off

SELECT COUNT(*) AS extraction_count
FROM llm_extractions
WHERE extraction_type = 'adverse_event_failure_mode';

SELECT
  json_output->>'possible_ai_relatedness' AS possible_ai_relatedness,
  COUNT(*) AS n
FROM llm_extractions
WHERE extraction_type = 'adverse_event_failure_mode'
GROUP BY 1
ORDER BY n DESC;

SELECT
  mode.failure_mode,
  COUNT(*) AS n
FROM llm_extractions lx
CROSS JOIN LATERAL jsonb_array_elements_text(lx.json_output->'failure_modes') AS mode(failure_mode)
WHERE lx.extraction_type = 'adverse_event_failure_mode'
GROUP BY mode.failure_mode
ORDER BY n DESC;

SELECT
  d.canonical_name,
  ae.report_number,
  ae.event_type,
  ae.date_received,
  lx.json_output->>'possible_ai_relatedness' AS ai_relatedness,
  lx.json_output->'failure_modes' AS failure_modes,
  lx.confidence,
  lx.needs_human_review,
  lx.json_output->>'source_quote' AS source_quote
FROM llm_extractions lx
JOIN adverse_events ae ON ae.id = lx.source_id
JOIN device_adverse_event_links l ON l.adverse_event_id = ae.id
JOIN devices d ON d.id = l.device_id
WHERE lx.extraction_type = 'adverse_event_failure_mode'
ORDER BY lx.needs_human_review DESC, lx.confidence DESC, ae.date_received DESC NULLS LAST
LIMIT 30;
