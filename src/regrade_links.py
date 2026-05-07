from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Any, Iterable

from rapidfuzz import fuzz
from tqdm import tqdm

from .db import get_conn

GENERIC_ALIAS_STOPWORDS = {
    "ai", "air", "dl", "recon", "system", "software", "station", "web", "diagnostic",
    "ultrasound", "processing", "assistant", "guidance", "medical", "device", "imaging",
    "mr", "mri", "ct", "cad", "plus", "v1", "v2", "v3", "fit", "mobile",
}

MANUFACTURER_WORDS = {
    "inc", "llc", "ltd", "gmbh", "sas", "co", "company", "corporation", "medical",
    "healthcare", "health", "systems", "system", "technologies", "technology", "limited",
}


@dataclass(frozen=True)
class Grade:
    score: float
    method: str
    matched_on: str | None
    needs_review: bool
    reason: str


def norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("®", " ").replace("™", " ")
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def compact(value: Any) -> str:
    return norm(value).replace(" ", "")


def split_family_name(value: str | None) -> list[str]:
    if not value:
        return []
    raw = str(value).replace("®", "").replace("™", "")
    parts = re.split(r"[;|]", raw)
    aliases: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        variants = [part, re.sub(r"\([^)]*\)", " ", part)]
        for variant in variants:
            cleaned = re.sub(r"[^A-Za-z0-9]+", " ", variant)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                aliases.append(cleaned)
    return list(dict.fromkeys(aliases))


def alias_quality(alias: str) -> tuple[bool, str]:
    """Return whether an alias is specific enough to support a high-confidence link."""
    a = norm(alias)
    if not a:
        return False, "empty"
    tokens = [t for t in a.split() if t]
    useful = [t for t in tokens if t not in GENERIC_ALIAS_STOPWORDS and t not in MANUFACTURER_WORDS]

    # Never allow a single generic token like "AIR" or "AI" to create a high-confidence link.
    if len(tokens) == 1:
        t = tokens[0]
        if t in GENERIC_ALIAS_STOPWORDS or len(t) < 5:
            return False, "single generic/short token"
        # Single brand-family tokens like MAGNETOM can be useful but still need review unless paired with model/family context.
        if t in {"magnetom", "signa", "lumify"}:
            return True, "recognized product-family token"
        return len(t) >= 6, "single specific token" if len(t) >= 6 else "single short token"

    if len(a) < 6:
        return False, "short phrase"

    # Good aliases usually contain at least two tokens and at least one non-generic token.
    if len(tokens) >= 2 and useful:
        return True, "specific multi-token alias"

    return False, "all-generic alias"


def get_aliases(conn, device_id: str, canonical_name: str | None) -> list[str]:
    rows = conn.execute(
        "SELECT alias FROM device_aliases WHERE device_id = %s ORDER BY confidence DESC, length(alias) DESC",
        (device_id,),
    ).fetchall()
    raw = [r["alias"] for r in rows] + split_family_name(canonical_name)
    # Add canonical as a whole only if it is not a long semicolon family string.
    if canonical_name and ";" not in canonical_name:
        raw.append(canonical_name)
    aliases: list[str] = []
    for alias in raw:
        for part in split_family_name(alias):
            ok, _ = alias_quality(part)
            if ok and norm(part) not in {norm(x) for x in aliases}:
                aliases.append(part)
    # Sort longest first so "AIR Recon DL" beats "AIR" and "MAGNETOM Sola" beats "MAGNETOM".
    aliases.sort(key=lambda x: len(norm(x)), reverse=True)
    return aliases


def exact_phrase_hit(alias: str, text: str) -> bool:
    a = norm(alias)
    h = norm(text)
    if not a or not h:
        return False
    # Word-boundary-ish phrase match after punctuation normalization.
    return f" {a} " in f" {h} "


def compact_hit(alias: str, text: str) -> bool:
    """Catch forms like Flow.Elite vs Flow Elite while avoiding tiny aliases."""
    a = compact(alias)
    h = compact(text)
    return bool(a and len(a) >= 8 and a in h)


def best_alias_hit(aliases: list[str], text: str) -> tuple[str | None, str | None]:
    for alias in aliases:
        if exact_phrase_hit(alias, text):
            return alias, "phrase"
        if compact_hit(alias, text):
            return alias, "compact"
    return None, None


def manufacturer_hit(device_manufacturer: str | None, record_firm: str | None, text: str = "") -> bool:
    if not device_manufacturer:
        return False
    dm = norm(device_manufacturer)
    hay = norm(f"{record_firm or ''} {text or ''}")
    if not dm or not hay:
        return False
    if dm in hay:
        return True
    # Also compare without corporate suffix noise.
    dm_core = " ".join(t for t in dm.split() if t not in MANUFACTURER_WORDS)
    hay_core = " ".join(t for t in hay.split() if t not in MANUFACTURER_WORDS)
    return bool(dm_core and (dm_core in hay_core or fuzz.partial_ratio(dm_core, hay_core) >= 92))


def product_code_hit(device_product_code: str | None, record_product_code: str | None) -> bool:
    return bool(device_product_code and record_product_code and norm(device_product_code) == norm(record_product_code))


def grade_record(
    *,
    aliases: list[str],
    device_product_code: str | None,
    device_manufacturer: str | None,
    record_product_code: str | None,
    record_firm: str | None,
    brand_text: str,
    descriptive_text: str,
) -> Grade:
    """Conservative evidence-link grading.

    The key rule: product code + weak alias is NOT enough for public-facing high confidence.
    A high-confidence link needs a specific device/family alias in brand/model/catalog or a clear
    specific alias in narrative/product-description text.
    """
    pc_hit = product_code_hit(device_product_code, record_product_code)
    firm_hit = manufacturer_hit(device_manufacturer, record_firm, descriptive_text)

    brand_alias, brand_kind = best_alias_hit(aliases, brand_text)
    desc_alias, desc_kind = best_alias_hit(aliases, descriptive_text)

    if brand_alias and pc_hit:
        return Grade(0.990, "specific_brand_or_model_alias+product_code", brand_alias, False, f"specific alias in brand/model ({brand_kind}) and product-code match")
    if brand_alias:
        return Grade(0.930, "specific_brand_or_model_alias", brand_alias, False, f"specific alias in brand/model ({brand_kind})")
    if desc_alias and pc_hit:
        return Grade(0.900, "specific_text_alias+product_code", desc_alias, False, f"specific alias in descriptive text ({desc_kind}) and product-code match")
    if desc_alias and firm_hit:
        return Grade(0.860, "specific_text_alias+manufacturer", desc_alias, False, f"specific alias in descriptive text ({desc_kind}) and manufacturer match")
    if desc_alias:
        return Grade(0.800, "specific_text_alias", desc_alias, True, f"specific alias only in descriptive text ({desc_kind}); review recommended")
    if pc_hit and firm_hit:
        return Grade(0.620, "broad_product_code+manufacturer", device_product_code, True, "product code and manufacturer only; not device/version specific")
    if pc_hit:
        return Grade(0.480, "product_code_only", device_product_code, True, "product code only; broad class match")
    if firm_hit:
        return Grade(0.350, "manufacturer_only", device_manufacturer, True, "manufacturer only; broad firm match")
    return Grade(0.0, "no_specific_match", None, True, "no specific alias, product-code, or firm match")


def update_link(conn, table: str, link_id: str, grade: Grade, apply: bool) -> None:
    if not apply:
        return
    conn.execute(
        f"""
        UPDATE {table}
        SET match_confidence = %s,
            match_method = %s,
            matched_on = %s,
            needs_review = %s
        WHERE id = %s
        """,
        (grade.score, grade.method, grade.matched_on, grade.needs_review, link_id),
    )


def regrade_adverse_events(conn, *, apply: bool) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT
            l.id AS link_id,
            d.id AS device_id,
            d.canonical_name,
            d.manufacturer,
            d.primary_product_code,
            ae.product_code,
            ae.manufacturer_name,
            ae.brand_name,
            ae.generic_name,
            ae.model_number,
            ae.catalog_number,
            ae.narrative_text,
            l.match_method AS old_method,
            l.match_confidence AS old_confidence,
            l.needs_review AS old_needs_review
        FROM device_adverse_event_links l
        JOIN devices d ON d.id = l.device_id
        JOIN adverse_events ae ON ae.id = l.adverse_event_id
        ORDER BY d.canonical_name, ae.date_received DESC NULLS LAST
        """
    ).fetchall()
    changed = 0
    for row in tqdm(rows, desc="Regrading adverse-event links"):
        aliases = get_aliases(conn, str(row["device_id"]), row["canonical_name"])
        brand_text = " ".join(str(row.get(k) or "") for k in ["brand_name", "generic_name", "model_number", "catalog_number"])
        descriptive_text = str(row.get("narrative_text") or "")
        grade = grade_record(
            aliases=aliases,
            device_product_code=row.get("primary_product_code"),
            device_manufacturer=row.get("manufacturer"),
            record_product_code=row.get("product_code"),
            record_firm=row.get("manufacturer_name"),
            brand_text=brand_text,
            descriptive_text=descriptive_text,
        )
        if (
            float(row.get("old_confidence") or 0) != grade.score
            or row.get("old_method") != grade.method
            or bool(row.get("old_needs_review")) != grade.needs_review
        ):
            changed += 1
            update_link(conn, "device_adverse_event_links", str(row["link_id"]), grade, apply)
    return len(rows), changed


def regrade_enforcement(conn, *, apply: bool) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT
            l.id AS link_id,
            d.id AS device_id,
            d.canonical_name,
            d.manufacturer,
            d.primary_product_code,
            ea.product_code,
            ea.recalling_firm,
            ea.product_description,
            ea.reason_for_recall,
            ea.code_info,
            l.match_method AS old_method,
            l.match_confidence AS old_confidence,
            l.needs_review AS old_needs_review
        FROM device_enforcement_links l
        JOIN devices d ON d.id = l.device_id
        JOIN enforcement_actions ea ON ea.id = l.enforcement_action_id
        ORDER BY d.canonical_name, ea.recall_initiation_date DESC NULLS LAST
        """
    ).fetchall()
    changed = 0
    for row in tqdm(rows, desc="Regrading enforcement links"):
        aliases = get_aliases(conn, str(row["device_id"]), row["canonical_name"])
        descriptive_text = " ".join(str(row.get(k) or "") for k in ["product_description", "reason_for_recall", "code_info"])
        grade = grade_record(
            aliases=aliases,
            device_product_code=row.get("primary_product_code"),
            device_manufacturer=row.get("manufacturer"),
            record_product_code=row.get("product_code"),
            record_firm=row.get("recalling_firm"),
            brand_text=row.get("product_description") or "",
            descriptive_text=descriptive_text,
        )
        if (
            float(row.get("old_confidence") or 0) != grade.score
            or row.get("old_method") != grade.method
            or bool(row.get("old_needs_review")) != grade.needs_review
        ):
            changed += 1
            update_link(conn, "device_enforcement_links", str(row["link_id"]), grade, apply)
    return len(rows), changed


def regrade_recalls(conn, *, apply: bool) -> tuple[int, int]:
    rows = conn.execute(
        """
        SELECT
            l.id AS link_id,
            d.id AS device_id,
            d.canonical_name,
            d.manufacturer,
            d.primary_product_code,
            rr.product_code,
            rr.recalling_firm,
            rr.product_description,
            rr.root_cause_description,
            rr.action,
            l.match_method AS old_method,
            l.match_confidence AS old_confidence,
            l.needs_review AS old_needs_review
        FROM device_recall_links l
        JOIN devices d ON d.id = l.device_id
        JOIN recall_records rr ON rr.id = l.recall_record_id
        ORDER BY d.canonical_name, rr.date_posted DESC NULLS LAST
        """
    ).fetchall()
    changed = 0
    for row in tqdm(rows, desc="Regrading recall links"):
        aliases = get_aliases(conn, str(row["device_id"]), row["canonical_name"])
        descriptive_text = " ".join(str(row.get(k) or "") for k in ["product_description", "root_cause_description", "action"])
        grade = grade_record(
            aliases=aliases,
            device_product_code=row.get("primary_product_code"),
            device_manufacturer=row.get("manufacturer"),
            record_product_code=row.get("product_code"),
            record_firm=row.get("recalling_firm"),
            brand_text=row.get("product_description") or "",
            descriptive_text=descriptive_text,
        )
        if (
            float(row.get("old_confidence") or 0) != grade.score
            or row.get("old_method") != grade.method
            or bool(row.get("old_needs_review")) != grade.needs_review
        ):
            changed += 1
            update_link(conn, "device_recall_links", str(row["link_id"]), grade, apply)
    return len(rows), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Regrade existing device-record links using stricter alias specificity rules.")
    parser.add_argument("--apply", action="store_true", help="Actually update database links. Without this, dry-run summary only.")
    parser.add_argument("--only", choices=["all", "events", "enforcement", "recall"], default="all")
    args = parser.parse_args()

    with get_conn() as conn:
        results = []
        if args.only in {"all", "events"}:
            results.append(("adverse events", *regrade_adverse_events(conn, apply=args.apply)))
        if args.only in {"all", "enforcement"}:
            results.append(("enforcement", *regrade_enforcement(conn, apply=args.apply)))
        if args.only in {"all", "recall"}:
            results.append(("recall", *regrade_recalls(conn, apply=args.apply)))

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"\n{mode} link regrade summary")
    for label, total, changed in results:
        print(f"- {label}: {changed} / {total} links would change" if not args.apply else f"- {label}: {changed} / {total} links updated")
    if not args.apply:
        print("\nRun again with --apply to update the database.")


if __name__ == "__main__":
    main()
