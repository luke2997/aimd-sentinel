from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from .db import get_conn


def main() -> None:
    parser = argparse.ArgumentParser(description="Export adverse-event rows for manual QA/labelling.")
    parser.add_argument("--device-name", type=str, default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--out", type=str, default="data/manual_label_set.csv")
    parser.add_argument("--include-review-links", action="store_true", help="Include broad/low-confidence links. Useful for link-validation QA.")
    parser.add_argument("--min-match-confidence", type=float, default=0.85)
    args = parser.parse_args()

    where = ["ae.narrative_text IS NOT NULL", "length(ae.narrative_text) > 0"]
    params: list[Any] = []
    if args.device_name:
        where.append("d.canonical_name ILIKE %s")
        params.append(f"%{args.device_name}%")
    if not args.include_review_links:
        where.append("l.match_confidence >= %s AND l.needs_review = FALSE")
        params.append(args.min_match_confidence)

    sql = f"""
        SELECT
          d.canonical_name,
          d.manufacturer AS device_manufacturer,
          ae.report_number,
          ae.date_received,
          ae.event_type,
          ae.brand_name,
          ae.manufacturer_name AS event_manufacturer,
          ae.product_code,
          l.match_method,
          l.matched_on,
          l.match_confidence,
          l.needs_review AS link_needs_review,
          LEFT(REGEXP_REPLACE(COALESCE(ae.narrative_text,''), '\\s+', ' ', 'g'), 2500) AS narrative_text,
          COALESCE(lx.json_output->>'possible_ai_relatedness','') AS model_ai_relatedness,
          COALESCE(lx.json_output->>'failure_modes','') AS model_failure_modes,
          '' AS human_link_valid,
          '' AS human_ai_relatedness,
          '' AS human_failure_modes,
          '' AS human_notes
        FROM devices d
        JOIN device_adverse_event_links l ON l.device_id = d.id
        JOIN adverse_events ae ON ae.id = l.adverse_event_id
        LEFT JOIN llm_extractions lx
          ON lx.source_table = 'adverse_events'
         AND lx.source_id = ae.id
         AND lx.extraction_type = 'adverse_event_failure_mode'
        WHERE {' AND '.join(where)}
        ORDER BY ae.date_received DESC NULLS LAST, ae.report_number
        LIMIT %s
    """
    params.append(args.limit)

    with get_conn() as conn:
        rows = list(conn.execute(sql, params).fetchall())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out.write_text("", encoding="utf-8")
        print(f"No rows. Wrote empty file: {out}")
        return

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
