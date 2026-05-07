# AIMD Sentinel starter pack

A practical MVP scaffold for an LLM-powered AI-enabled medical-device governance tool.

This starter pack gives you:

- `data/seed_devices.csv`: 20 recent FDA AI-enabled radiology devices.
- `sql/schema.sql`: PostgreSQL schema with provenance, device, authorization, adverse-event, enforcement, recall, document, LLM extraction, evidence-claim, and report tables.
- `src/ingest_fda_ai_list.py`: fetches/parses the FDA AI-enabled medical devices list and loads a filtered seed set.
- `src/ingest_seed_devices.py`: loads the included fixed seed CSV.
- `src/ingest_openfda.py`: pulls 510(k), MAUDE adverse-event, enforcement, and recall data from openFDA for seeded devices.
- `sql/example_queries.sql`: quick checks after ingestion.

## 1) Setup

```bash
cd aimd_sentinel_starter
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Start Postgres with pgvector:

```bash
docker compose up -d
```

The schema is mounted into the Docker init directory. If you already have a database, run:

```bash
psql "$DATABASE_URL" -f sql/schema.sql
```

## 2) Load the 20-device seed list

Use the fixed seed list included in this pack:

```bash
python -m src.ingest_seed_devices --path data/seed_devices.csv
```

Or fetch the FDA AI-enabled medical device list directly and take the first 20 radiology rows:

```bash
python -m src.ingest_fda_ai_list --panel Radiology --limit 20 --out data/fda_ai_list_radiology_latest.csv
```

If the FDA page blocks scripted access, use `data/seed_devices.csv` as the fallback seed. It was copied from the FDA page table current as of 2026-03-04.

## 3) Ingest openFDA data

Recommended first run:

```bash
python -m src.ingest_openfda \
  --sources 510k,event,enforcement,recall \
  --max-devices 20 \
  --max-event-records-per-device 100 \
  --max-recall-records-per-device 50
```

If you want broader but noisier event coverage, allow product-code-only links. These are marked as needing review:

```bash
python -m src.ingest_openfda \
  --sources event \
  --max-devices 20 \
  --max-event-records-per-device 500 \
  --include-product-code-only
```

## 4) Inspect results

```bash
psql "$DATABASE_URL" -f sql/example_queries.sql
```

Important tables:

- `devices`: canonical FDA AI-list device rows.
- `device_aliases`: search aliases for messy matching.
- `authorizations`: 510(k) records.
- `adverse_events`: normalized MAUDE/openFDA event-device rows.
- `device_adverse_event_links`: matching confidence between seeded AI device and adverse event.
- `enforcement_actions`: openFDA enforcement records.
- `recall_records`: openFDA device recall records.
- `source_records`: raw source JSON for every source-backed record.
- `evidence_claims`: future home for source-cited report claims.

## 5) Design notes

The system is deliberately conservative. It stores raw JSON in `source_records`, normalizes key fields into relational tables, then links records to devices through confidence-scored joins.

For MAUDE/adverse-event records, do not treat counts as true incidence rates. Passive adverse-event reports can be incomplete, duplicated, biased, unverified, and do not include denominator usage data. The MVP should present these as narrative clusters or potential signals requiring human review.

## 6) Next step after this scaffold

Build the LLM extraction layer on top of `adverse_events`:

```json
{
  "possible_ai_relatedness": "likely | possible | unlikely | insufficient_info",
  "failure_modes": [
    "false_negative_or_missed_finding",
    "false_positive_or_overalert",
    "input_data_quality_issue",
    "workflow_integration_issue",
    "human_ai_interaction_issue",
    "model_update_or_version_issue",
    "generalizability_or_drift_concern",
    "insufficient_information"
  ],
  "source_quote": "short quote from narrative",
  "confidence": 0.0,
  "needs_human_review": true
}
```

Write those outputs to `llm_extractions`, then turn supported claims into `evidence_claims` before generating dossiers.
