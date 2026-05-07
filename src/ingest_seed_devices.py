from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from .db import get_conn, start_ingestion_run, finish_ingestion_run, upsert_device_from_seed, upsert_source_record, add_device_alias
from .utils import short_alias


def read_seed_csv(path: str | Path) -> list[dict[str, Any]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ingest_seed_devices(path: str | Path) -> None:
    rows = read_seed_csv(path)
    with get_conn() as conn:
        run_id = start_ingestion_run(
            conn,
            source_name="FDA_AI_LIST_SEED",
            source_url="https://www.fda.gov/medical-devices/software-medical-device-samd/artificial-intelligence-enabled-medical-devices",
            query=str(path),
            meta={"seed_count": len(rows)},
        )
        upserted = 0
        try:
            for row in rows:
                key = row["submission_number"]
                source_id = upsert_source_record(
                    conn,
                    source_name="FDA_AI_LIST_SEED",
                    source_record_key=key,
                    raw_json=row,
                    source_url=row.get("fda_database_url"),
                )
                device_id = upsert_device_from_seed(conn, row, source_id)

                # Add useful aliases for matching noisy FDA / MAUDE records.
                device_name = row.get("device_name") or ""
                alias = short_alias(device_name)
                if alias != device_name:
                    add_device_alias(conn, device_id, alias, "short_name", "AIMD_SENTINEL_SEED", 0.92)
                company = row.get("company")
                if company:
                    add_device_alias(conn, device_id, company, "manufacturer_name", "AIMD_SENTINEL_SEED", 0.70)
                upserted += 1
            finish_ingestion_run(conn, run_id, status="completed", records_seen=len(rows), records_upserted=upserted)
        except Exception as exc:
            finish_ingestion_run(conn, run_id, status="failed", records_seen=len(rows), records_upserted=upserted, error=str(exc))
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load AIMD Sentinel seed devices into Postgres.")
    parser.add_argument("--path", default="data/seed_devices.csv")
    args = parser.parse_args()
    ingest_seed_devices(args.path)
