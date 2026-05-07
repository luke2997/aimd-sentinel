-- AIMD Sentinel starter schema
-- PostgreSQL 16 + pgvector recommended.
-- Run: psql "$DATABASE_URL" -f sql/schema.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------
-- Ingestion metadata + raw provenance
-- -----------------------------

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    source_url TEXT,
    query TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    records_seen INTEGER NOT NULL DEFAULT 0,
    records_upserted INTEGER NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    CHECK (status IN ('running', 'completed', 'failed', 'partial'))
);

CREATE TABLE IF NOT EXISTS source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    source_url TEXT,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_hash TEXT NOT NULL,
    raw_json JSONB NOT NULL,
    UNIQUE (source_name, source_record_key)
);

CREATE INDEX IF NOT EXISTS idx_source_records_source_name ON source_records (source_name);
CREATE INDEX IF NOT EXISTS idx_source_records_raw_json_gin ON source_records USING GIN (raw_json);

-- -----------------------------
-- FDA AI device list entities
-- -----------------------------

CREATE TABLE IF NOT EXISTS devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL,
    manufacturer TEXT,
    panel TEXT,
    primary_product_code TEXT,
    latest_submission_number TEXT,
    latest_decision_date DATE,
    fda_database_url TEXT,
    fda_ai_list_source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (latest_submission_number)
);

CREATE INDEX IF NOT EXISTS idx_devices_product_code ON devices (primary_product_code);
CREATE INDEX IF NOT EXISTS idx_devices_panel ON devices (panel);
CREATE INDEX IF NOT EXISTS idx_devices_name_trgm_like ON devices (lower(canonical_name));
CREATE INDEX IF NOT EXISTS idx_devices_manufacturer_like ON devices (lower(manufacturer));

CREATE TABLE IF NOT EXISTS device_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'manual',
    source TEXT,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, alias, alias_type)
);

CREATE INDEX IF NOT EXISTS idx_device_aliases_alias ON device_aliases (lower(alias));

-- -----------------------------
-- Premarket authorization records
-- -----------------------------

CREATE TABLE IF NOT EXISTS authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    authorization_type TEXT NOT NULL DEFAULT '510k',
    submission_number TEXT NOT NULL,
    device_name TEXT,
    applicant TEXT,
    product_code TEXT,
    advisory_committee TEXT,
    decision_date DATE,
    date_received DATE,
    decision_description TEXT,
    clearance_url TEXT,
    summary_url TEXT,
    reviewed_by_third_party TEXT,
    raw_source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (authorization_type, submission_number)
);

CREATE INDEX IF NOT EXISTS idx_authorizations_submission_number ON authorizations (submission_number);
CREATE INDEX IF NOT EXISTS idx_authorizations_product_code ON authorizations (product_code);
CREATE INDEX IF NOT EXISTS idx_authorizations_applicant ON authorizations (lower(applicant));

CREATE TABLE IF NOT EXISTS device_authorization_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    authorization_id UUID NOT NULL REFERENCES authorizations(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL,
    match_confidence NUMERIC(4,3) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, authorization_id)
);

-- -----------------------------
-- openFDA MAUDE adverse-event records
-- -----------------------------

CREATE TABLE IF NOT EXISTS adverse_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_number TEXT,
    mdr_report_key TEXT,
    event_type TEXT,
    date_received DATE,
    event_date DATE,
    report_date DATE,
    manufacturer_name TEXT,
    brand_name TEXT,
    generic_name TEXT,
    model_number TEXT,
    catalog_number TEXT,
    product_code TEXT,
    device_sequence_number TEXT,
    narrative_text TEXT,
    source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mdr_report_key, device_sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_adverse_events_report_number ON adverse_events (report_number);
CREATE INDEX IF NOT EXISTS idx_adverse_events_mdr_report_key ON adverse_events (mdr_report_key);
CREATE INDEX IF NOT EXISTS idx_adverse_events_product_code ON adverse_events (product_code);
CREATE INDEX IF NOT EXISTS idx_adverse_events_brand_name ON adverse_events (lower(brand_name));
CREATE INDEX IF NOT EXISTS idx_adverse_events_manufacturer ON adverse_events (lower(manufacturer_name));
CREATE INDEX IF NOT EXISTS idx_adverse_events_date_received ON adverse_events (date_received);
CREATE INDEX IF NOT EXISTS idx_adverse_events_narrative_tsv ON adverse_events USING GIN (to_tsvector('english', coalesce(narrative_text, '')));

CREATE TABLE IF NOT EXISTS device_adverse_event_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    adverse_event_id UUID NOT NULL REFERENCES adverse_events(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL,
    matched_on TEXT,
    match_confidence NUMERIC(4,3) NOT NULL,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, adverse_event_id)
);

-- -----------------------------
-- openFDA enforcement / recall records
-- -----------------------------

CREATE TABLE IF NOT EXISTS enforcement_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recall_number TEXT,
    event_id TEXT,
    status TEXT,
    classification TEXT,
    product_type TEXT,
    recalling_firm TEXT,
    product_description TEXT,
    product_code TEXT,
    reason_for_recall TEXT,
    code_info TEXT,
    distribution_pattern TEXT,
    initial_firm_notification TEXT,
    report_date DATE,
    recall_initiation_date DATE,
    termination_date DATE,
    source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recall_number, event_id)
);

CREATE INDEX IF NOT EXISTS idx_enforcement_recall_number ON enforcement_actions (recall_number);
CREATE INDEX IF NOT EXISTS idx_enforcement_product_code ON enforcement_actions (product_code);
CREATE INDEX IF NOT EXISTS idx_enforcement_firm ON enforcement_actions (lower(recalling_firm));
CREATE INDEX IF NOT EXISTS idx_enforcement_product_tsv ON enforcement_actions USING GIN (to_tsvector('english', coalesce(product_description, '') || ' ' || coalesce(reason_for_recall, '')));

CREATE TABLE IF NOT EXISTS device_enforcement_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    enforcement_action_id UUID NOT NULL REFERENCES enforcement_actions(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL,
    matched_on TEXT,
    match_confidence NUMERIC(4,3) NOT NULL,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, enforcement_action_id)
);

CREATE TABLE IF NOT EXISTS recall_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recall_number TEXT,
    res_event_number TEXT,
    product_code TEXT,
    product_description TEXT,
    root_cause_description TEXT,
    action TEXT,
    recall_status TEXT,
    recall_classification TEXT,
    recalling_firm TEXT,
    date_posted DATE,
    date_terminated DATE,
    source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recall_number, res_event_number)
);

CREATE INDEX IF NOT EXISTS idx_recall_records_product_code ON recall_records (product_code);
CREATE INDEX IF NOT EXISTS idx_recall_records_firm ON recall_records (lower(recalling_firm));
CREATE INDEX IF NOT EXISTS idx_recall_records_product_tsv ON recall_records USING GIN (to_tsvector('english', coalesce(product_description, '') || ' ' || coalesce(root_cause_description, '')));

CREATE TABLE IF NOT EXISTS device_recall_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    recall_record_id UUID NOT NULL REFERENCES recall_records(id) ON DELETE CASCADE,
    match_method TEXT NOT NULL,
    matched_on TEXT,
    match_confidence NUMERIC(4,3) NOT NULL,
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, recall_record_id)
);

-- -----------------------------
-- Documents, chunks, LLM outputs, and report layer
-- -----------------------------

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
    doc_type TEXT NOT NULL,
    title TEXT,
    url TEXT,
    local_path TEXT,
    source_record_id UUID REFERENCES source_records(id) ON DELETE SET NULL,
    text_content TEXT,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    token_count INTEGER,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS llm_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_table TEXT NOT NULL,
    source_id UUID NOT NULL,
    extraction_type TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    json_output JSONB NOT NULL,
    confidence NUMERIC(4,3),
    needs_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_table, source_id, extraction_type, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_llm_extractions_json_gin ON llm_extractions USING GIN (json_output);

CREATE TABLE IF NOT EXISTS evidence_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    source_table TEXT NOT NULL,
    source_id UUID NOT NULL,
    source_quote TEXT,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 0.500,
    is_supported BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (claim_type IN ('FACTUAL_SOURCE_BACKED', 'INFERRED_FROM_MULTIPLE_SOURCES', 'RECOMMENDATION', 'UNSUPPORTED_DO_NOT_SHOW'))
);

CREATE TABLE IF NOT EXISTS governance_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL DEFAULT 'governance_dossier',
    report_version TEXT NOT NULL DEFAULT 'v0.1',
    html_content TEXT,
    pdf_path TEXT,
    json_content JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS watchlists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_email TEXT,
    watch_type TEXT NOT NULL,
    device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
    manufacturer TEXT,
    product_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (watch_type IN ('device', 'manufacturer', 'product_code'))
);

COMMIT;
