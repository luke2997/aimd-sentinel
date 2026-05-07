from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings
from .utils import stable_hash


@contextmanager
def get_conn():
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_source_record(
    conn: psycopg.Connection,
    *,
    source_name: str,
    source_record_key: str,
    raw_json: dict[str, Any],
    source_url: str | None = None,
) -> str:
    raw_hash = stable_hash(raw_json)
    row = conn.execute(
        """
        INSERT INTO source_records (source_name, source_record_key, source_url, raw_hash, raw_json)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (source_name, source_record_key)
        DO UPDATE SET
            source_url = EXCLUDED.source_url,
            fetched_at = now(),
            raw_hash = EXCLUDED.raw_hash,
            raw_json = EXCLUDED.raw_json
        RETURNING id
        """,
        (source_name, source_record_key, source_url, raw_hash, Jsonb(raw_json)),
    ).fetchone()
    return str(row["id"])


def start_ingestion_run(
    conn: psycopg.Connection,
    *,
    source_name: str,
    source_url: str | None = None,
    query: str | None = None,
    meta: dict[str, Any] | None = None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO ingestion_runs (source_name, source_url, query, meta)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (source_name, source_url, query, Jsonb(meta or {})),
    ).fetchone()
    return str(row["id"])


def finish_ingestion_run(
    conn: psycopg.Connection,
    run_id: str,
    *,
    status: str,
    records_seen: int,
    records_upserted: int,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ingestion_runs
        SET completed_at = now(), status = %s, records_seen = %s, records_upserted = %s,
            error = %s, meta = coalesce(meta, '{}'::jsonb) || %s::jsonb
        WHERE id = %s
        """,
        (status, records_seen, records_upserted, error, Jsonb(meta or {}), run_id),
    )


def upsert_device_from_seed(
    conn: psycopg.Connection,
    row: dict[str, Any],
    source_record_id: str | None,
) -> str:
    result = conn.execute(
        """
        INSERT INTO devices (
            canonical_name, manufacturer, panel, primary_product_code,
            latest_submission_number, latest_decision_date, fda_database_url,
            fda_ai_list_source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (latest_submission_number)
        DO UPDATE SET
            canonical_name = EXCLUDED.canonical_name,
            manufacturer = EXCLUDED.manufacturer,
            panel = EXCLUDED.panel,
            primary_product_code = EXCLUDED.primary_product_code,
            latest_decision_date = EXCLUDED.latest_decision_date,
            fda_database_url = EXCLUDED.fda_database_url,
            fda_ai_list_source_record_id = EXCLUDED.fda_ai_list_source_record_id,
            updated_at = now()
        RETURNING id
        """,
        (
            row.get("device_name"),
            row.get("company"),
            row.get("panel"),
            row.get("primary_product_code"),
            row.get("submission_number"),
            row.get("decision_date"),
            row.get("fda_database_url"),
            source_record_id,
        ),
    ).fetchone()
    device_id = str(result["id"])
    add_device_alias(conn, device_id, row.get("device_name"), "fda_device_name", "FDA_AI_LIST", 1.0)
    return device_id


def add_device_alias(
    conn: psycopg.Connection,
    device_id: str,
    alias: str | None,
    alias_type: str,
    source: str,
    confidence: float,
) -> None:
    if not alias:
        return
    conn.execute(
        """
        INSERT INTO device_aliases (device_id, alias, alias_type, source, confidence)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (device_id, alias, alias_type)
        DO UPDATE SET source = EXCLUDED.source, confidence = EXCLUDED.confidence
        """,
        (device_id, alias, alias_type, source, confidence),
    )


def get_seed_devices(conn: psycopg.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM devices ORDER BY latest_decision_date DESC NULLS LAST, canonical_name"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def get_device_aliases(conn: psycopg.Connection, device_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT alias FROM device_aliases WHERE device_id = %s ORDER BY confidence DESC",
        (device_id,),
    ).fetchall()
    return [r["alias"] for r in rows]


def upsert_authorization(
    conn: psycopg.Connection,
    values: dict[str, Any],
    source_record_id: str | None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO authorizations (
            authorization_type, submission_number, device_name, applicant, product_code,
            advisory_committee, decision_date, date_received, decision_description,
            clearance_url, summary_url, reviewed_by_third_party, raw_source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (authorization_type, submission_number)
        DO UPDATE SET
            device_name = EXCLUDED.device_name,
            applicant = EXCLUDED.applicant,
            product_code = EXCLUDED.product_code,
            advisory_committee = EXCLUDED.advisory_committee,
            decision_date = EXCLUDED.decision_date,
            date_received = EXCLUDED.date_received,
            decision_description = EXCLUDED.decision_description,
            clearance_url = EXCLUDED.clearance_url,
            summary_url = EXCLUDED.summary_url,
            reviewed_by_third_party = EXCLUDED.reviewed_by_third_party,
            raw_source_record_id = EXCLUDED.raw_source_record_id,
            updated_at = now()
        RETURNING id
        """,
        (
            values.get("authorization_type", "510k"),
            values.get("submission_number"),
            values.get("device_name"),
            values.get("applicant"),
            values.get("product_code"),
            values.get("advisory_committee"),
            values.get("decision_date"),
            values.get("date_received"),
            values.get("decision_description"),
            values.get("clearance_url"),
            values.get("summary_url"),
            values.get("reviewed_by_third_party"),
            source_record_id,
        ),
    ).fetchone()
    return str(row["id"])


def link_device_authorization(
    conn: psycopg.Connection,
    device_id: str,
    authorization_id: str,
    *,
    match_method: str,
    match_confidence: float,
    is_primary: bool = False,
    needs_review: bool = False,
) -> None:
    conn.execute(
        """
        INSERT INTO device_authorization_links
            (device_id, authorization_id, match_method, match_confidence, is_primary, needs_review)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, authorization_id)
        DO UPDATE SET
            match_method = EXCLUDED.match_method,
            match_confidence = EXCLUDED.match_confidence,
            is_primary = EXCLUDED.is_primary,
            needs_review = EXCLUDED.needs_review
        """,
        (device_id, authorization_id, match_method, match_confidence, is_primary, needs_review),
    )


def upsert_adverse_event(
    conn: psycopg.Connection,
    values: dict[str, Any],
    source_record_id: str | None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO adverse_events (
            report_number, mdr_report_key, event_type, date_received, event_date, report_date,
            manufacturer_name, brand_name, generic_name, model_number, catalog_number,
            product_code, device_sequence_number, narrative_text, source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (mdr_report_key, device_sequence_number)
        DO UPDATE SET
            report_number = EXCLUDED.report_number,
            event_type = EXCLUDED.event_type,
            date_received = EXCLUDED.date_received,
            event_date = EXCLUDED.event_date,
            report_date = EXCLUDED.report_date,
            manufacturer_name = EXCLUDED.manufacturer_name,
            brand_name = EXCLUDED.brand_name,
            generic_name = EXCLUDED.generic_name,
            model_number = EXCLUDED.model_number,
            catalog_number = EXCLUDED.catalog_number,
            product_code = EXCLUDED.product_code,
            narrative_text = EXCLUDED.narrative_text,
            source_record_id = EXCLUDED.source_record_id,
            updated_at = now()
        RETURNING id
        """,
        (
            values.get("report_number"),
            values.get("mdr_report_key"),
            values.get("event_type"),
            values.get("date_received"),
            values.get("event_date"),
            values.get("report_date"),
            values.get("manufacturer_name"),
            values.get("brand_name"),
            values.get("generic_name"),
            values.get("model_number"),
            values.get("catalog_number"),
            values.get("product_code"),
            values.get("device_sequence_number") or "1",
            values.get("narrative_text"),
            source_record_id,
        ),
    ).fetchone()
    return str(row["id"])


def link_device_adverse_event(
    conn: psycopg.Connection,
    device_id: str,
    adverse_event_id: str,
    *,
    match_method: str,
    matched_on: str | None,
    match_confidence: float,
    needs_review: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO device_adverse_event_links
            (device_id, adverse_event_id, match_method, matched_on, match_confidence, needs_review)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, adverse_event_id)
        DO UPDATE SET
            match_method = EXCLUDED.match_method,
            matched_on = EXCLUDED.matched_on,
            match_confidence = EXCLUDED.match_confidence,
            needs_review = EXCLUDED.needs_review
        """,
        (device_id, adverse_event_id, match_method, matched_on, match_confidence, needs_review),
    )


def upsert_enforcement_action(
    conn: psycopg.Connection,
    values: dict[str, Any],
    source_record_id: str | None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO enforcement_actions (
            recall_number, event_id, status, classification, product_type, recalling_firm,
            product_description, product_code, reason_for_recall, code_info, distribution_pattern,
            initial_firm_notification, report_date, recall_initiation_date, termination_date,
            source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (recall_number, event_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            classification = EXCLUDED.classification,
            product_type = EXCLUDED.product_type,
            recalling_firm = EXCLUDED.recalling_firm,
            product_description = EXCLUDED.product_description,
            product_code = EXCLUDED.product_code,
            reason_for_recall = EXCLUDED.reason_for_recall,
            code_info = EXCLUDED.code_info,
            distribution_pattern = EXCLUDED.distribution_pattern,
            initial_firm_notification = EXCLUDED.initial_firm_notification,
            report_date = EXCLUDED.report_date,
            recall_initiation_date = EXCLUDED.recall_initiation_date,
            termination_date = EXCLUDED.termination_date,
            source_record_id = EXCLUDED.source_record_id,
            updated_at = now()
        RETURNING id
        """,
        (
            values.get("recall_number"),
            values.get("event_id"),
            values.get("status"),
            values.get("classification"),
            values.get("product_type"),
            values.get("recalling_firm"),
            values.get("product_description"),
            values.get("product_code"),
            values.get("reason_for_recall"),
            values.get("code_info"),
            values.get("distribution_pattern"),
            values.get("initial_firm_notification"),
            values.get("report_date"),
            values.get("recall_initiation_date"),
            values.get("termination_date"),
            source_record_id,
        ),
    ).fetchone()
    return str(row["id"])


def link_device_enforcement(
    conn: psycopg.Connection,
    device_id: str,
    enforcement_action_id: str,
    *,
    match_method: str,
    matched_on: str | None,
    match_confidence: float,
    needs_review: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO device_enforcement_links
            (device_id, enforcement_action_id, match_method, matched_on, match_confidence, needs_review)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, enforcement_action_id)
        DO UPDATE SET
            match_method = EXCLUDED.match_method,
            matched_on = EXCLUDED.matched_on,
            match_confidence = EXCLUDED.match_confidence,
            needs_review = EXCLUDED.needs_review
        """,
        (device_id, enforcement_action_id, match_method, matched_on, match_confidence, needs_review),
    )


def upsert_recall_record(
    conn: psycopg.Connection,
    values: dict[str, Any],
    source_record_id: str | None,
) -> str:
    row = conn.execute(
        """
        INSERT INTO recall_records (
            recall_number, res_event_number, product_code, product_description,
            root_cause_description, action, recall_status, recall_classification,
            recalling_firm, date_posted, date_terminated, source_record_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (recall_number, res_event_number)
        DO UPDATE SET
            product_code = EXCLUDED.product_code,
            product_description = EXCLUDED.product_description,
            root_cause_description = EXCLUDED.root_cause_description,
            action = EXCLUDED.action,
            recall_status = EXCLUDED.recall_status,
            recall_classification = EXCLUDED.recall_classification,
            recalling_firm = EXCLUDED.recalling_firm,
            date_posted = EXCLUDED.date_posted,
            date_terminated = EXCLUDED.date_terminated,
            source_record_id = EXCLUDED.source_record_id,
            updated_at = now()
        RETURNING id
        """,
        (
            values.get("recall_number"),
            values.get("res_event_number"),
            values.get("product_code"),
            values.get("product_description"),
            values.get("root_cause_description"),
            values.get("action"),
            values.get("recall_status"),
            values.get("recall_classification"),
            values.get("recalling_firm"),
            values.get("date_posted"),
            values.get("date_terminated"),
            source_record_id,
        ),
    ).fetchone()
    return str(row["id"])


def link_device_recall(
    conn: psycopg.Connection,
    device_id: str,
    recall_record_id: str,
    *,
    match_method: str,
    matched_on: str | None,
    match_confidence: float,
    needs_review: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO device_recall_links
            (device_id, recall_record_id, match_method, matched_on, match_confidence, needs_review)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (device_id, recall_record_id)
        DO UPDATE SET
            match_method = EXCLUDED.match_method,
            matched_on = EXCLUDED.matched_on,
            match_confidence = EXCLUDED.match_confidence,
            needs_review = EXCLUDED.needs_review
        """,
        (device_id, recall_record_id, match_method, matched_on, match_confidence, needs_review),
    )
