from __future__ import annotations

import argparse
from typing import Any

from tqdm import tqdm

from .db import get_conn
from .regrade_links import norm, manufacturer_hit, product_code_hit


def should_demote_enforcement(row: dict[str, Any]) -> tuple[bool, str]:
    method = str(row.get("match_method") or "")
    conf = float(row.get("match_confidence") or 0)
    needs_review = bool(row.get("needs_review"))
    if needs_review or conf < 0.85:
        return False, "already review/low confidence"

    pc_hit = product_code_hit(row.get("device_product_code"), row.get("record_product_code"))
    firm_hit = manufacturer_hit(
        row.get("device_manufacturer"),
        row.get("record_firm"),
        " ".join(str(row.get(k) or "") for k in ["product_description", "reason", "extra_text"]),
    )

    # Enforcement/recall descriptions often contain generic brand phrases, unlike MAUDE brand_name.
    # For public-facing high confidence, require either product-code agreement or firm/manufacturer agreement.
    high_by_alias_only = (
        "specific_brand_or_model_alias" in method
        or "specific_text_alias" in method
        or method == "alias"
    ) and not (pc_hit or firm_hit)

    if high_by_alias_only:
        return True, "alias hit without matching product code or manufacturer/firm"

    # Product code alone is still broad for enforcement/recall records.
    if "product_code_only" in method and not firm_hit:
        return True, "product-code-only enforcement/recall link"

    return False, "kept"


def gate_table(conn, *, table: str, record_table: str, record_id_col: str, apply: bool) -> tuple[int, int]:
    if table == "device_enforcement_links":
        select_sql = """
        SELECT
            l.id AS link_id,
            l.match_method,
            l.match_confidence,
            l.needs_review,
            d.canonical_name,
            d.manufacturer AS device_manufacturer,
            d.primary_product_code AS device_product_code,
            ea.product_code AS record_product_code,
            ea.recalling_firm AS record_firm,
            ea.product_description,
            ea.reason_for_recall AS reason,
            ea.code_info AS extra_text
        FROM device_enforcement_links l
        JOIN devices d ON d.id = l.device_id
        JOIN enforcement_actions ea ON ea.id = l.enforcement_action_id
        """
    else:
        select_sql = """
        SELECT
            l.id AS link_id,
            l.match_method,
            l.match_confidence,
            l.needs_review,
            d.canonical_name,
            d.manufacturer AS device_manufacturer,
            d.primary_product_code AS device_product_code,
            rr.product_code AS record_product_code,
            rr.recalling_firm AS record_firm,
            rr.product_description,
            rr.root_cause_description AS reason,
            rr.action AS extra_text
        FROM device_recall_links l
        JOIN devices d ON d.id = l.device_id
        JOIN recall_records rr ON rr.id = l.recall_record_id
        """

    rows = conn.execute(select_sql).fetchall()
    changed = 0
    for row in tqdm(rows, desc=f"Strict-gating {table}"):
        demote, reason = should_demote_enforcement(dict(row))
        if not demote:
            continue
        changed += 1
        if apply:
            conn.execute(
                f"""
                UPDATE {table}
                SET needs_review = true,
                    match_confidence = LEAST(match_confidence, 0.740),
                    match_method = 'review_only_alias_without_product_code_or_manufacturer',
                    matched_on = COALESCE(matched_on, '')
                WHERE id = %s
                """,
                (row["link_id"],),
            )
    return len(rows), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Demote weak alias-only enforcement/recall links to review-only.")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Without this, dry run only.")
    parser.add_argument("--only", choices=["all", "enforcement", "recall"], default="all")
    args = parser.parse_args()

    results = []
    with get_conn() as conn:
        if args.only in {"all", "enforcement"}:
            results.append(("enforcement", *gate_table(conn, table="device_enforcement_links", record_table="enforcement_actions", record_id_col="enforcement_action_id", apply=args.apply)))
        if args.only in {"all", "recall"}:
            results.append(("recall", *gate_table(conn, table="device_recall_links", record_table="recall_records", record_id_col="recall_record_id", apply=args.apply)))

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"\n{mode} strict enforcement/recall gate summary")
    for name, total, changed in results:
        print(f"- {name}: {changed} / {total} links {'updated' if args.apply else 'would be demoted'}")
    if not args.apply:
        print("Run again with --apply to update the database.")


if __name__ == "__main__":
    main()
