-- Optional cleanup after testing heuristic extraction on broad/review-only links.
-- This removes generated classifier outputs and old reports, but keeps FDA/openFDA ingested data.
DELETE FROM evidence_claims;
DELETE FROM governance_reports;
DELETE FROM llm_extractions
WHERE extraction_type = 'adverse_event_failure_mode';
