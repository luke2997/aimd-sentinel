from __future__ import annotations

import argparse
from typing import Any

from rapidfuzz import fuzz
from tqdm import tqdm

from .db import (
    get_conn,
    get_seed_devices,
    get_device_aliases,
    start_ingestion_run,
    finish_ingestion_run,
    upsert_source_record,
    upsert_authorization,
    link_device_authorization,
    upsert_adverse_event,
    link_device_adverse_event,
    upsert_enforcement_action,
    link_device_enforcement,
    upsert_recall_record,
    link_device_recall,
)
from .openfda_client import OpenFDAClient
from .utils import (
    and_query,
    field_term,
    first_nonempty,
    flatten_mdr_text,
    normalize_text,
    or_query,
    parse_date,
    quote_openfda_term,
    record_key,
    short_alias,
    split_search_aliases,
)


def k510_pdf_url(k_number: str | None) -> str | None:
    if not k_number or not k_number.upper().startswith("K") or len(k_number) < 3:
        return None
    yy = k_number[1:3]
    return f"https://www.accessdata.fda.gov/cdrh_docs/pdf{yy}/{k_number.upper()}.pdf"


def k510_database_url(k_number: str | None) -> str | None:
    if not k_number:
        return None
    return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm?ID={k_number.upper()}"


def build_search_aliases(device: dict[str, Any], aliases: list[str], *, max_aliases: int = 8) -> list[str]:
    """Build a deduplicated list of openFDA-safe aliases for one device."""
    candidates = aliases + [device.get("canonical_name"), short_alias(device.get("canonical_name") or "")]
    clean_aliases: list[str] = []

    for candidate in candidates:
        for alias in split_search_aliases(candidate, max_aliases=max_aliases):
            # Avoid generic company-only queries in device-name slots.
            if len(alias) >= 3 and alias not in clean_aliases:
                clean_aliases.append(alias)
            if len(clean_aliases) >= max_aliases:
                return clean_aliases

    return clean_aliases


def extract_510k(record: dict[str, Any], fallback_submission: str | None = None) -> dict[str, Any]:
    k_number = first_nonempty(record.get("k_number"), record.get("submission_number"), fallback_submission)
    return {
        "authorization_type": "510k",
        "submission_number": k_number,
        "device_name": record.get("device_name"),
        "applicant": first_nonempty(record.get("applicant"), record.get("sponsor")),
        "product_code": record.get("product_code"),
        "advisory_committee": first_nonempty(record.get("advisory_committee"), record.get("review_advisory_committee")),
        "decision_date": parse_date(record.get("decision_date")),
        "date_received": parse_date(record.get("date_received")),
        "decision_description": first_nonempty(record.get("decision_description"), record.get("decision")),
        "clearance_url": k510_database_url(k_number),
        "summary_url": k510_pdf_url(k_number),
        "reviewed_by_third_party": first_nonempty(record.get("third_party_flag"), record.get("reviewed_by_third_party")),
    }


def event_search_queries(device: dict[str, Any], aliases: list[str]) -> list[str]:
    product_code = device.get("primary_product_code")
    manufacturer = device.get("manufacturer")
    clean_aliases = build_search_aliases(device, aliases, max_aliases=8)

    queries: list[str] = []
    # High-specificity: product code + device phrase in brand or narrative.
    if product_code:
        for alias in clean_aliases[:5]:
            alias_part = or_query([field_term("device.brand_name", alias), field_term("mdr_text.text", alias)])
            queries.append(and_query([field_term("device.device_report_product_code", product_code), alias_part]))
        if manufacturer:
            queries.append(and_query([field_term("device.device_report_product_code", product_code), field_term("device.manufacturer_d_name", manufacturer)]))
    else:
        for alias in clean_aliases[:3]:
            queries.append(or_query([field_term("device.brand_name", alias), field_term("mdr_text.text", alias)]))
    # De-duplicate while preserving order.
    return list(dict.fromkeys([q for q in queries if q]))


def enforcement_search_queries(device: dict[str, Any], aliases: list[str]) -> list[str]:
    manufacturer = device.get("manufacturer")
    clean_aliases = build_search_aliases(device, aliases, max_aliases=8)

    queries: list[str] = []
    for alias in clean_aliases[:5]:
        queries.append(or_query([field_term("product_description", alias), field_term("reason_for_recall", alias)]))
    if manufacturer:
        queries.append(field_term("recalling_firm", manufacturer))
    return list(dict.fromkeys([q for q in queries if q]))


def recall_search_queries(device: dict[str, Any], aliases: list[str]) -> list[str]:
    product_code = device.get("primary_product_code")
    manufacturer = device.get("manufacturer")
    clean_aliases = build_search_aliases(device, aliases, max_aliases=8)

    queries: list[str] = []
    if product_code:
        for alias in clean_aliases[:5]:
            queries.append(and_query([field_term("product_code", product_code), field_term("product_description", alias)]))
        queries.append(field_term("product_code", product_code))
    else:
        for alias in clean_aliases[:3]:
            queries.append(field_term("product_description", alias))
    if manufacturer:
        queries.append(field_term("firm_fei_number", manufacturer))  # may not hit; kept as a harmless fallback candidate
    return list(dict.fromkeys([q for q in queries if q]))


def score_text_match(device: dict[str, Any], aliases: list[str], text: str, product_code: str | None = None, firm: str | None = None) -> tuple[float, str, str | None, bool]:
    """Heuristic record-device matching. Conservative by design."""
    hay = normalize_text(text)
    canonical = device.get("canonical_name") or ""
    manufacturer = device.get("manufacturer") or ""
    device_product_code = device.get("primary_product_code")

    alias_hits = []
    for alias in aliases + [canonical, short_alias(canonical)]:
        nalias = normalize_text(alias)
        if len(nalias) >= 4 and nalias in hay:
            alias_hits.append(alias)

    manufacturer_hit = False
    if manufacturer:
        nman = normalize_text(manufacturer)
        firm_hay = normalize_text(firm) + " " + hay
        manufacturer_hit = nman in firm_hay or fuzz.partial_ratio(nman, firm_hay) >= 88

    product_hit = bool(device_product_code and product_code and normalize_text(device_product_code) == normalize_text(product_code))

    if product_hit and alias_hits:
        return 0.950, "product_code+alias", alias_hits[0], False
    if alias_hits:
        return 0.850, "alias", alias_hits[0], False
    if product_hit and manufacturer_hit:
        return 0.760, "product_code+manufacturer", device_product_code, True
    if product_hit:
        return 0.550, "product_code_only", device_product_code, True
    if manufacturer_hit:
        return 0.450, "manufacturer_only", manufacturer, True
    return 0.0, "no_match", None, True


def extract_event_device_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    narrative = flatten_mdr_text(record)
    devices = record.get("device") or [{}]
    rows = []
    for idx, dev in enumerate(devices, start=1):
        if not isinstance(dev, dict):
            dev = {}
        rows.append({
            "report_number": record.get("report_number"),
            "mdr_report_key": first_nonempty(record.get("mdr_report_key"), record.get("report_number")),
            "event_type": record.get("event_type"),
            "date_received": parse_date(record.get("date_received")),
            "event_date": parse_date(first_nonempty(record.get("date_of_event"), record.get("event_date"))),
            "report_date": parse_date(first_nonempty(record.get("date_report"), record.get("date_report_to_fda"))),
            "manufacturer_name": first_nonempty(dev.get("manufacturer_d_name"), dev.get("manufacturer_name")),
            "brand_name": dev.get("brand_name"),
            "generic_name": dev.get("generic_name"),
            "model_number": dev.get("model_number"),
            "catalog_number": dev.get("catalog_number"),
            "product_code": first_nonempty(dev.get("device_report_product_code"), dev.get("product_code")),
            "device_sequence_number": first_nonempty(dev.get("device_sequence_number"), str(idx)),
            "narrative_text": narrative,
        })
    return rows


def extract_enforcement(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall_number": record.get("recall_number"),
        "event_id": record.get("event_id"),
        "status": record.get("status"),
        "classification": record.get("classification"),
        "product_type": record.get("product_type"),
        "recalling_firm": record.get("recalling_firm"),
        "product_description": record.get("product_description"),
        "product_code": record.get("product_code"),
        "reason_for_recall": record.get("reason_for_recall"),
        "code_info": record.get("code_info"),
        "distribution_pattern": record.get("distribution_pattern"),
        "initial_firm_notification": record.get("initial_firm_notification"),
        "report_date": parse_date(record.get("report_date")),
        "recall_initiation_date": parse_date(record.get("recall_initiation_date")),
        "termination_date": parse_date(record.get("termination_date")),
    }


def extract_recall(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall_number": record.get("recall_number"),
        "res_event_number": first_nonempty(record.get("res_event_number"), record.get("event_id")),
        "product_code": record.get("product_code"),
        "product_description": record.get("product_description"),
        "root_cause_description": record.get("root_cause_description"),
        "action": record.get("action"),
        "recall_status": first_nonempty(record.get("recall_status"), record.get("status")),
        "recall_classification": first_nonempty(record.get("recall_classification"), record.get("classification")),
        "recalling_firm": record.get("recalling_firm"),
        "date_posted": parse_date(first_nonempty(record.get("date_posted"), record.get("report_date"))),
        "date_terminated": parse_date(record.get("date_terminated")),
    }


def ingest_510k_for_devices(client: OpenFDAClient, max_devices: int | None = None) -> None:
    with get_conn() as conn:
        devices = get_seed_devices(conn, max_devices)
        run_id = start_ingestion_run(conn, source_name="OPENFDA_510K", source_url="https://api.fda.gov/device/510k.json")
        seen = upserted = 0
        try:
            for device in tqdm(devices, desc="510(k)"):
                k_number = device.get("latest_submission_number")
                if not k_number:
                    continue
                query = f"k_number:{quote_openfda_term(k_number)}"
                records = list(client.iter_search("device/510k", search=query, max_records=5))
                seen += len(records)
                for record in records:
                    key = record_key(record, ["k_number"], f"510k:{k_number}")
                    source_id = upsert_source_record(
                        conn,
                        source_name="OPENFDA_510K",
                        source_record_key=key,
                        raw_json=record,
                        source_url=k510_database_url(key),
                    )
                    values = extract_510k(record, fallback_submission=k_number)
                    auth_id = upsert_authorization(conn, values, source_id)
                    link_device_authorization(
                        conn,
                        str(device["id"]),
                        auth_id,
                        match_method="submission_number_exact",
                        match_confidence=1.0,
                        is_primary=True,
                        needs_review=False,
                    )
                    upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=seen, records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=seen, records_upserted=upserted, error=str(exc))
            raise


def ingest_events_for_devices(client: OpenFDAClient, max_devices: int | None = None, max_records_per_device: int = 200, include_product_code_only: bool = False) -> None:
    with get_conn() as conn:
        devices = get_seed_devices(conn, max_devices)
        run_id = start_ingestion_run(
            conn,
            source_name="OPENFDA_EVENT",
            source_url="https://api.fda.gov/device/event.json",
            meta={"max_records_per_device": max_records_per_device},
        )
        seen = upserted = 0
        try:
            for device in tqdm(devices, desc="MAUDE events"):
                aliases = get_device_aliases(conn, str(device["id"]))
                fetched_keys: set[str] = set()
                for query in event_search_queries(device, aliases):
                    for record in client.iter_search("device/event", search=query, max_records=max_records_per_device):
                        key = record_key(record, ["mdr_report_key", "report_number"], "event")
                        if key in fetched_keys:
                            continue
                        fetched_keys.add(key)
                        seen += 1
                        source_id = upsert_source_record(
                            conn,
                            source_name="OPENFDA_EVENT",
                            source_record_key=key,
                            raw_json=record,
                            source_url="https://api.fda.gov/device/event.json",
                        )
                        for event_row in extract_event_device_rows(record):
                            text = " ".join([
                                str(event_row.get("brand_name") or ""),
                                str(event_row.get("generic_name") or ""),
                                str(event_row.get("manufacturer_name") or ""),
                                str(event_row.get("narrative_text") or ""),
                            ])
                            score, method, matched_on, needs_review = score_text_match(
                                device,
                                aliases,
                                text,
                                product_code=event_row.get("product_code"),
                                firm=event_row.get("manufacturer_name"),
                            )
                            if score < 0.70 and not (include_product_code_only and score >= 0.55):
                                continue
                            event_id = upsert_adverse_event(conn, event_row, source_id)
                            link_device_adverse_event(
                                conn,
                                str(device["id"]),
                                event_id,
                                match_method=method,
                                matched_on=matched_on,
                                match_confidence=score,
                                needs_review=needs_review,
                            )
                            upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=seen, records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=seen, records_upserted=upserted, error=str(exc))
            raise


def ingest_enforcement_for_devices(client: OpenFDAClient, max_devices: int | None = None, max_records_per_device: int = 100) -> None:
    with get_conn() as conn:
        devices = get_seed_devices(conn, max_devices)
        run_id = start_ingestion_run(
            conn,
            source_name="OPENFDA_ENFORCEMENT",
            source_url="https://api.fda.gov/device/enforcement.json",
            meta={"max_records_per_device": max_records_per_device},
        )
        seen = upserted = 0
        try:
            for device in tqdm(devices, desc="Enforcement"):
                aliases = get_device_aliases(conn, str(device["id"]))
                fetched_keys: set[str] = set()
                for query in enforcement_search_queries(device, aliases):
                    for record in client.iter_search("device/enforcement", search=query, max_records=max_records_per_device):
                        key = record_key(record, ["recall_number", "event_id"], "enforcement")
                        if key in fetched_keys:
                            continue
                        fetched_keys.add(key)
                        seen += 1
                        source_id = upsert_source_record(
                            conn,
                            source_name="OPENFDA_ENFORCEMENT",
                            source_record_key=key,
                            raw_json=record,
                            source_url="https://api.fda.gov/device/enforcement.json",
                        )
                        values = extract_enforcement(record)
                        text = " ".join([
                            str(values.get("product_description") or ""),
                            str(values.get("reason_for_recall") or ""),
                            str(values.get("recalling_firm") or ""),
                        ])
                        score, method, matched_on, needs_review = score_text_match(
                            device,
                            aliases,
                            text,
                            product_code=values.get("product_code"),
                            firm=values.get("recalling_firm"),
                        )
                        if score < 0.70:
                            continue
                        action_id = upsert_enforcement_action(conn, values, source_id)
                        link_device_enforcement(
                            conn,
                            str(device["id"]),
                            action_id,
                            match_method=method,
                            matched_on=matched_on,
                            match_confidence=score,
                            needs_review=needs_review,
                        )
                        upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=seen, records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=seen, records_upserted=upserted, error=str(exc))
            raise


def ingest_recall_for_devices(client: OpenFDAClient, max_devices: int | None = None, max_records_per_device: int = 100) -> None:
    with get_conn() as conn:
        devices = get_seed_devices(conn, max_devices)
        run_id = start_ingestion_run(
            conn,
            source_name="OPENFDA_RECALL",
            source_url="https://api.fda.gov/device/recall.json",
            meta={"max_records_per_device": max_records_per_device},
        )
        seen = upserted = 0
        try:
            for device in tqdm(devices, desc="Recall"):
                aliases = get_device_aliases(conn, str(device["id"]))
                fetched_keys: set[str] = set()
                for query in recall_search_queries(device, aliases):
                    for record in client.iter_search("device/recall", search=query, max_records=max_records_per_device):
                        key = record_key(record, ["recall_number", "res_event_number"], "recall")
                        if key in fetched_keys:
                            continue
                        fetched_keys.add(key)
                        seen += 1
                        source_id = upsert_source_record(
                            conn,
                            source_name="OPENFDA_RECALL",
                            source_record_key=key,
                            raw_json=record,
                            source_url="https://api.fda.gov/device/recall.json",
                        )
                        values = extract_recall(record)
                        text = " ".join([
                            str(values.get("product_description") or ""),
                            str(values.get("root_cause_description") or ""),
                            str(values.get("recalling_firm") or ""),
                        ])
                        score, method, matched_on, needs_review = score_text_match(
                            device,
                            aliases,
                            text,
                            product_code=values.get("product_code"),
                            firm=values.get("recalling_firm"),
                        )
                        if score < 0.70:
                            continue
                        recall_id = upsert_recall_record(conn, values, source_id)
                        link_device_recall(
                            conn,
                            str(device["id"]),
                            recall_id,
                            match_method=method,
                            matched_on=matched_on,
                            match_confidence=score,
                            needs_review=needs_review,
                        )
                        upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=seen, records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=seen, records_upserted=upserted, error=str(exc))
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest openFDA data for seeded AI radiology devices.")
    parser.add_argument("--sources", default="510k,event,enforcement,recall", help="Comma-separated: 510k,event,enforcement,recall")
    parser.add_argument("--max-devices", type=int, default=None)
    parser.add_argument("--max-event-records-per-device", type=int, default=200)
    parser.add_argument("--max-recall-records-per-device", type=int, default=100)
    parser.add_argument("--include-product-code-only", action="store_true", help="Also link product-code-only event matches at low confidence; review manually.")
    args = parser.parse_args()

    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
    client = OpenFDAClient()
    try:
        if "510k" in sources:
            ingest_510k_for_devices(client, max_devices=args.max_devices)
        if "event" in sources:
            ingest_events_for_devices(
                client,
                max_devices=args.max_devices,
                max_records_per_device=args.max_event_records_per_device,
                include_product_code_only=args.include_product_code_only,
            )
        if "enforcement" in sources:
            ingest_enforcement_for_devices(client, max_devices=args.max_devices, max_records_per_device=args.max_recall_records_per_device)
        if "recall" in sources:
            ingest_recall_for_devices(client, max_devices=args.max_devices, max_records_per_device=args.max_recall_records_per_device)
    finally:
        client.close()


if __name__ == "__main__":
    main()
