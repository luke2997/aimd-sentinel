\pset pager off

-- Shows current extraction counts for the strongest software demo candidates.
SELECT
  d.canonical_name,
  COUNT(*) FILTER (WHERE l.needs_review = false AND l.match_confidence >= 0.85) AS high_conf_events,
  COUNT(*) FILTER (WHERE l.needs_review = true OR l.match_confidence < 0.85) AS review_events,
  COUNT(*) AS total_events
FROM devices d
LEFT JOIN device_adverse_event_links l ON l.device_id = d.id
GROUP BY d.id
ORDER BY high_conf_events DESC, review_events ASC, d.canonical_name
LIMIT 25;

-- AI/software-relatedness counts after extraction.
SELECT
  d.canonical_name,
  lx.json_output->>'possible_ai_relatedness' AS relatedness,
  COUNT(*) AS records
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
JOIN LATERAL (
  SELECT json_output
  FROM llm_extractions lx
  WHERE lx.source_table = 'adverse_events'
    AND lx.source_id = ae.id
    AND lx.extraction_type = 'adverse_event_failure_mode'
  ORDER BY lx.created_at DESC
  LIMIT 1
) lx ON TRUE
WHERE l.needs_review = false
  AND l.match_confidence >= 0.85
GROUP BY d.canonical_name, lx.json_output->>'possible_ai_relatedness'
ORDER BY d.canonical_name, records DESC;

-- Failure mode counts after extraction.
SELECT
  d.canonical_name,
  mode AS failure_mode,
  COUNT(*) AS records
FROM devices d
JOIN device_adverse_event_links l ON l.device_id = d.id
JOIN adverse_events ae ON ae.id = l.adverse_event_id
JOIN LATERAL (
  SELECT json_output
  FROM llm_extractions lx
  WHERE lx.source_table = 'adverse_events'
    AND lx.source_id = ae.id
    AND lx.extraction_type = 'adverse_event_failure_mode'
  ORDER BY lx.created_at DESC
  LIMIT 1
) lx ON TRUE
CROSS JOIN LATERAL jsonb_array_elements_text(lx.json_output->'failure_modes') AS mode
WHERE l.needs_review = false
  AND l.match_confidence >= 0.85
GROUP BY d.canonical_name, mode
ORDER BY d.canonical_name, records DESC;
