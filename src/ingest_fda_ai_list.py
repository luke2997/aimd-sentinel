from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from .config import settings
from .db import get_conn, start_ingestion_run, finish_ingestion_run, upsert_source_record, upsert_device_from_seed, add_device_alias
from .utils import parse_date, short_alias


COLUMN_MAP = {
    "date of final decision": "decision_date",
    "submission number": "submission_number",
    "device": "device_name",
    "company": "company",
    "panel (lead)": "panel",
    "panel": "panel",
    "primary product code": "primary_product_code",
}


def database_url_for_submission(submission_number: str | None) -> str | None:
    if not submission_number:
        return None
    sub = submission_number.strip().upper()
    # The FDA AI list uses these links for 510(k) and De Novo entries.
    if sub.startswith(("K", "DEN")):
        return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm?ID={sub}"
    if sub.startswith("P"):
        return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMA/pma.cfm?id={sub}"
    return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm?ID={sub}"


def clean_column_name(col: Any) -> str:
    text = str(col).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_fda_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    rename = {}
    for col in df.columns:
        c = clean_column_name(col)
        if c in COLUMN_MAP:
            rename[col] = COLUMN_MAP[c]
    df = df.rename(columns=rename)
    required = {"decision_date", "submission_number", "device_name", "company", "panel", "primary_product_code"}
    if not required.issubset(set(df.columns)):
        raise ValueError(f"Could not identify FDA AI-list columns. Found: {list(df.columns)}")

    records: list[dict[str, Any]] = []
    for raw in df[list(required)].to_dict(orient="records"):
        sub = str(raw.get("submission_number") or "").strip()
        if not sub or sub.lower() == "nan":
            continue
        row = {
            "decision_date": parse_date(raw.get("decision_date")),
            "submission_number": sub,
            "device_name": str(raw.get("device_name") or "").strip(),
            "company": str(raw.get("company") or "").strip(),
            "panel": str(raw.get("panel") or "").strip(),
            "primary_product_code": str(raw.get("primary_product_code") or "").strip(),
            "fda_database_url": database_url_for_submission(sub),
        }
        # Convert dates to ISO string for JSON/CSV friendliness.
        if row["decision_date"]:
            row["decision_date"] = row["decision_date"].isoformat()
        records.append(row)
    return records


def fetch_fda_ai_list(url: str) -> list[dict[str, Any]]:
    response = httpx.get(url, timeout=60.0, headers={"User-Agent": "aimd-sentinel-mvp/0.1"})
    response.raise_for_status()
    tables = pd.read_html(response.text)
    for table in tables:
        try:
            return normalize_fda_table(table)
        except Exception:
            continue
    raise RuntimeError("No usable FDA AI-enabled medical devices table found on the page.")


def write_csv(records: list[dict[str, Any]], path: str | Path) -> None:
    if not records:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)


def ingest_records(records: list[dict[str, Any]], source_url: str, source_name: str = "FDA_AI_LIST") -> None:
    with get_conn() as conn:
        run_id = start_ingestion_run(
            conn,
            source_name=source_name,
            source_url=source_url,
            meta={"record_count": len(records)},
        )
        upserted = 0
        try:
            for row in records:
                source_id = upsert_source_record(
                    conn,
                    source_name=source_name,
                    source_record_key=row["submission_number"],
                    raw_json=row,
                    source_url=row.get("fda_database_url"),
                )
                device_id = upsert_device_from_seed(conn, row, source_id)
                alias = short_alias(row.get("device_name") or "")
                if alias and alias != row.get("device_name"):
                    add_device_alias(conn, device_id, alias, "short_name", source_name, 0.92)
                if row.get("company"):
                    add_device_alias(conn, device_id, row.get("company"), "manufacturer_name", source_name, 0.70)
                upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=len(records), records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=len(records), records_upserted=upserted, error=str(exc))
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest FDA AI-enabled medical device list.")
    parser.add_argument("--url", default=settings.fda_ai_list_url)
    parser.add_argument("--panel", default="Radiology", help="Filter panel, e.g. Radiology. Use ALL for no filter.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", default="data/fda_ai_list_radiology_latest.csv")
    parser.add_argument("--no-db", action="store_true", help="Only write CSV; do not upsert into database.")
    args = parser.parse_args()

    records = fetch_fda_ai_list(args.url)
    if args.panel.upper() != "ALL":
        records = [r for r in records if str(r.get("panel", "")).strip().lower() == args.panel.lower()]
    if args.limit:
        records = records[: args.limit]
    write_csv(records, args.out)
    if not args.no_db:
        ingest_records(records, args.url)
    print(f"Wrote {len(records)} rows to {args.out}")


if __name__ == "__main__":
    main()
