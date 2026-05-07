from __future__ import annotations

import argparse
import csv
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from tqdm import tqdm

# AIMD Sentinel candidate discovery
# Purpose: find FDA AI radiology devices that actually have exact public MAUDE/openFDA mentions.
# This is useful because many software-first AI devices have no device-specific adverse-event records,
# while broad scanner families can dominate public MAUDE results.

OPENFDA_BASE = "https://api.fda.gov"

OUTPUT_COLUMNS = [
    "seed_rank",
    "decision_date",
    "submission_number",
    "device_name",
    "company",
    "panel",
    "primary_product_code",
    "fda_database_url",
    "cohort",
    "dataset_v2_score",
    "seed_reason",
    "exact_brand_event_count",
    "exact_text_event_count",
    "best_alias",
]

SOFTWARE_TERMS = [
    "ai", "artificial intelligence", "algorithm", "software", "cad", "cadx", "cade", "detect", "detection",
    "triage", "notification", "alert", "flag", "prioritization", "assist", "assistant", "analysis", "viewer",
    "suite", "platform", "quant", "quantification", "segmentation", "contour", "reconstruction", "recon",
    "stroke", "lvo", "hemorrhage", "ich", "aneurysm", "pulmonary embolism", "embolism", "pe",
    "lung", "nodule", "pneumothorax", "fracture", "spine", "vertebra", "mammography", "breast",
    "density", "cardiac", "calcium", "brain", "liver", "lesion", "bone", "ct", "mri",
]

HARDWARE_TERMS = [
    "magnetom", "signa", "somatom", "scanner", "scanners", "diagnostic ultrasound system", "ultrasound system",
    "portable mr imaging system", "mr imaging system", "magnetic resonance diagnostic system", "ct system",
    "x-ray system", "radiography system", "fluoroscopy", "c-arm", "mobile c-arm", "pet/ct", "pet mr",
    "imaging system", "tomography system", "acuson", "epiq", "affiniti", "aplio", "canon", "sequoia",
]

WEAK_TOKENS = {
    "ai", "air", "dl", "ct", "mr", "mri", "cad", "cadx", "system", "systems", "software", "device", "devices",
    "platform", "imaging", "diagnostic", "medical", "image", "images", "viewer", "suite", "version", "v", "plus",
    "pro", "web", "app", "the", "and", "for", "with", "inc", "llc", "ltd", "co", "company", "diagnostics",
}


def norm_col(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def find_col(fieldnames: list[str], candidates: list[str]) -> str | None:
    normalized = {norm_col(c): c for c in fieldnames}
    for cand in candidates:
        if norm_col(cand) in normalized:
            return normalized[norm_col(cand)]
    return None


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", str(value))
    return int(m.group(1)) if m else None


def database_url(submission: str) -> str:
    sub = (submission or "").strip().upper()
    if sub.startswith(("K", "DEN")):
        return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm?ID={sub}"
    if sub.startswith("P"):
        return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMA/pma.cfm?id={sub}"
    return f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm?ID={sub}"


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        col_decision = find_col(fieldnames, ["decision_date", "date of final decision", "decision date"])
        col_submission = find_col(fieldnames, ["submission_number", "submission number", "submission"])
        col_device = find_col(fieldnames, ["device_name", "device", "device name"])
        col_company = find_col(fieldnames, ["company", "manufacturer", "applicant"])
        col_panel = find_col(fieldnames, ["panel", "panel (lead)", "medical specialty"])
        col_code = find_col(fieldnames, ["primary_product_code", "primary product code", "product_code", "product code"])
        col_url = find_col(fieldnames, ["fda_database_url", "fda database url", "url"])
        required = [col_decision, col_submission, col_device, col_company, col_panel, col_code]
        if any(c is None for c in required):
            raise SystemExit(f"Could not map input columns. Found columns: {fieldnames}")

        out: list[dict[str, Any]] = []
        for raw in reader:
            sub = (raw.get(col_submission) or "").strip().upper()
            name = (raw.get(col_device) or "").strip()
            if not sub or not name:
                continue
            row = {
                "decision_date": (raw.get(col_decision) or "").strip(),
                "submission_number": sub,
                "device_name": name,
                "company": (raw.get(col_company) or "").strip(),
                "panel": (raw.get(col_panel) or "").strip() or "Radiology",
                "primary_product_code": (raw.get(col_code) or "").strip().upper(),
                "fda_database_url": (raw.get(col_url) or "").strip() or database_url(sub),
            }
            out.append(row)
        return out


def strong_tokens(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9]+", text.lower())
    return [t for t in toks if len(t) > 2 and t not in WEAK_TOKENS]


def contains_any(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return [t for t in terms if t in low]


def clean_alias(alias: str) -> str:
    alias = re.sub(r"\b(v|version)\s*\d+(\.\d+)*\b", "", alias, flags=re.I)
    alias = re.sub(r"\bsoftware\s+version\s*\d+(\.\d+)*\b", "", alias, flags=re.I)
    alias = re.sub(r"\([^)]*\)", " ", alias)
    alias = re.sub(r"\s+", " ", alias.replace("®", "").replace("™", "")).strip(" ,-_/;")
    return alias


def alias_candidates(device_name: str) -> list[str]:
    # Split long family names, but preserve full specific software names.
    parts = re.split(r"\s*;\s*|\s+\/\s+", device_name)
    aliases = [device_name] + parts
    # Also remove trailing version suffixes.
    aliases += [clean_alias(a) for a in aliases]
    # Remove parenthetical descriptors and duplicate.
    out: list[str] = []
    seen: set[str] = set()
    for a in aliases:
        a = clean_alias(a)
        if not a:
            continue
        toks = strong_tokens(a)
        if len(toks) < 2:
            continue
        # Avoid aliases that are just broad imaging/hardware phrases.
        if a.lower() in {"diagnostic ultrasound system", "mr imaging system", "imaging system"}:
            continue
        key = a.lower()
        if key not in seen:
            seen.add(key)
            out.append(a)
    # Shorter specific aliases first often match openFDA brand_name better.
    return sorted(out, key=lambda x: (len(x.split()), len(x)))[:5]


def openfda_count(client: httpx.Client, endpoint: str, search: str, api_key: str | None = None) -> int:
    params = {"limit": 1, "search": search}
    if api_key:
        params["api_key"] = api_key
    try:
        r = client.get(f"{OPENFDA_BASE}/{endpoint}.json", params=params, timeout=30)
        if r.status_code in (400, 404):
            return 0
        r.raise_for_status()
        data = r.json()
        return int(data.get("meta", {}).get("results", {}).get("total", 0) or 0)
    except Exception:
        return 0


def row_base_score(row: dict[str, Any]) -> tuple[int, str]:
    text = f"{row['device_name']} {row.get('company','')} {row.get('primary_product_code','')}"
    year = parse_year(row.get("decision_date"))
    sw = contains_any(text, SOFTWARE_TERMS)
    hw = contains_any(text, HARDWARE_TERMS)
    toks = strong_tokens(row["device_name"])
    score = 0
    reasons: list[str] = []
    if year and year <= 2022:
        score += 25
        reasons.append("older_clearance_<=2022")
    elif year and year <= 2024:
        score += 10
        reasons.append("moderately_old_clearance")
    else:
        score -= 8
        reasons.append("recent_or_unknown_clearance")
    if sw:
        score += min(30, 5 * len(set(sw)))
        reasons.append("software_terms:" + "/".join(sorted(set(sw))[:5]))
    if len(toks) >= 3:
        score += 12
        reasons.append("specific_name")
    elif len(toks) <= 1:
        score -= 12
        reasons.append("weak_name")
    if hw:
        score -= 35
        reasons.append("hardware_terms:" + "/".join(sorted(set(hw))[:5]))
    if len(row["device_name"]) > 90 or ";" in row["device_name"]:
        score -= 8
        reasons.append("long_family_name")
    return score, "; ".join(reasons)


def select_candidate_pool(rows: list[dict[str, Any]], max_candidates: int) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for row in rows:
        if row.get("panel", "").lower() != "radiology":
            continue
        base, reason = row_base_score(row)
        row = dict(row)
        row["base_score"] = base
        row["base_reason"] = reason
        pool.append(row)
    # Keep a wide pool: software-ish rows plus some hardware controls.
    return sorted(pool, key=lambda r: r["base_score"], reverse=True)[:max_candidates]


def discover(rows: list[dict[str, Any]], max_candidates: int, sleep_s: float, api_key: str | None) -> list[dict[str, Any]]:
    selected_pool = select_candidate_pool(rows, max_candidates)
    results: list[dict[str, Any]] = []
    with httpx.Client(headers={"User-Agent": "AIMD-Sentinel-prototype/0.1"}) as client:
        for row in tqdm(selected_pool, desc="Exact openFDA discovery"):
            aliases = alias_candidates(row["device_name"])
            best_alias = aliases[0] if aliases else row["device_name"]
            best_brand = 0
            best_text = 0
            best_total = -1
            for alias in aliases:
                safe = alias.replace('"', '')
                brand_search = f'device.brand_name:"{safe}"'
                text_search = f'mdr_text.text:"{safe}"'
                brand_count = openfda_count(client, "device/event", brand_search, api_key=api_key)
                text_count = openfda_count(client, "device/event", text_search, api_key=api_key)
                total = brand_count * 3 + text_count
                if total > best_total:
                    best_total = total
                    best_brand = brand_count
                    best_text = text_count
                    best_alias = alias
                if sleep_s:
                    time.sleep(sleep_s)
            text_all = f"{row['device_name']} {row.get('company','')}"
            hw = contains_any(text_all, HARDWARE_TERMS)
            base = int(row.get("base_score", 0))
            demo_score = base + min(200, best_brand * 8 + best_text * 2)
            if hw:
                cohort = "negative_control_hardware_family"
            elif best_brand > 0 or best_text > 0:
                cohort = "software_exact_match_candidate"
            else:
                cohort = "software_sparse_candidate"
            row = dict(row)
            row.update({
                "cohort": cohort,
                "dataset_v2_score": demo_score,
                "seed_reason": f"{row.get('base_reason','')}; best_alias={best_alias}; exact_brand_events={best_brand}; exact_text_events={best_text}",
                "exact_brand_event_count": best_brand,
                "exact_text_event_count": best_text,
                "best_alias": best_alias,
            })
            results.append(row)
    return sorted(results, key=lambda r: (r["cohort"] != "software_exact_match_candidate", -int(r["dataset_v2_score"])))


def write_discovery(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = OUTPUT_COLUMNS + ["base_score", "base_reason"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            row = dict(row)
            row["seed_rank"] = i
            writer.writerow(row)


def write_seed(rows: list[dict[str, Any]], path: Path, target_exact: int, target_controls: int, target_sparse: int) -> list[dict[str, Any]]:
    exact = [r for r in rows if r["cohort"] == "software_exact_match_candidate"][:target_exact]
    controls = sorted([r for r in rows if r["cohort"] == "negative_control_hardware_family"], key=lambda r: int(r["dataset_v2_score"]), reverse=True)[:target_controls]
    sparse = sorted([r for r in rows if r["cohort"] == "software_sparse_candidate"], key=lambda r: int(r["dataset_v2_score"]), reverse=True)[:target_sparse]
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in exact + controls + sparse:
        sub = r["submission_number"]
        if sub in seen:
            continue
        seen.add(sub)
        combined.append(dict(r))
    for i, row in enumerate(combined, 1):
        row["seed_rank"] = i
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in combined:
            writer.writerow(row)
    return combined


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Discover FDA AI radiology devices with exact openFDA event mentions.")
    parser.add_argument("--input", default="data/fda_ai_list_full.csv")
    parser.add_argument("--discovery-out", default="data/demo_candidate_discovery.csv")
    parser.add_argument("--seed-out", default="data/seed_devices_v21.csv")
    parser.add_argument("--max-candidates", type=int, default=180)
    parser.add_argument("--target-exact", type=int, default=40)
    parser.add_argument("--target-controls", type=int, default=10)
    parser.add_argument("--target-sparse", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    api_key = os.getenv("OPENFDA_API_KEY") or os.getenv("FDA_API_KEY")
    rows = load_rows(Path(args.input))
    discovered = discover(rows, args.max_candidates, args.sleep, api_key)
    write_discovery(discovered, Path(args.discovery_out))
    seed = write_seed(discovered, Path(args.seed_out), args.target_exact, args.target_controls, args.target_sparse)

    counts: dict[str, int] = {}
    for r in seed:
        counts[r["cohort"]] = counts.get(r["cohort"], 0) + 1
    print(f"Wrote discovery table: {args.discovery_out}")
    print(f"Wrote v2.1 seed: {args.seed_out}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print("\nOpen the discovery CSV and seed CSV before resetting/re-ingesting. Remove obvious weak/generic rows manually if needed.")


if __name__ == "__main__":
    main()
