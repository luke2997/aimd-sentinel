from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from psycopg.types.json import Jsonb
from tqdm import tqdm

from .db import get_conn

PROMPT_VERSION = "adverse_event_failure_modes_v0_4_software_aware"
EXTRACTION_TYPE = "adverse_event_failure_mode"

AI_RELATEDNESS = {"likely", "possible", "unlikely", "insufficient_info"}
FAILURE_MODES = {
    "false_negative_or_missed_finding",
    "false_positive_or_overalert",
    "localization_or_labeling_error",
    "input_data_quality_issue",
    "workflow_integration_issue",
    "human_ai_interaction_issue",
    "model_update_or_version_issue",
    "generalizability_or_drift_concern",
    "cybersecurity_or_access_issue",
    "device_or_hardware_malfunction",
    "software_anomaly_or_calculation_error",
    "clinical_measurement_or_classification_error",
    "software_system_synchronization_or_registration_issue",
    "insufficient_information",
}

# Conservative principle:
# Physical MRI/US/X-ray problems are NOT AI-related simply because the device is on the FDA AI list.
# Require explicit evidence of algorithm/AI/reconstruction/CAD/alert/segmentation/workflow software.
STRONG_AI_PATTERNS = [
    r"\bartificial intelligence\b",
    r"\bmachine learning\b",
    r"\bdeep learning\b",
    r"\bneural network\b",
    r"\bAI[- ]enabled\b",
    r"\bAI\b",
    r"\balgorithm(?:ic)?\b",
    r"\bmodel output\b",
    r"\bsoftware model\b",
    r"\bCAD\b",
    r"\bcomputer[- ]aided\b",
    r"\bautomated detection\b",
    r"\btriage\b",
    r"\bworklist\b",
    r"\balert(?:ed|ing|s)?\b",
    r"\bnotification(?:s)?\b",
    r"\bsegmentation\b",
    r"\breconstruction\b",
    r"\bAIR Recon DL\b",
]

WEAK_DIGITAL_PATTERNS = [
    r"\bsoftware\b",
    r"\bfirmware\b",
    r"\bversion\b",
    r"\bupdate(?:d|s)?\b",
    r"\bupgrade(?:d|s)?\b",
    r"\bpatch(?:ed|es)?\b",
    r"\brollback\b",
    r"\bserver\b",
    r"\bcloud\b",
    r"\bPACS\b",
    r"\bRIS\b",
    r"\bEHR\b",
    r"\bDICOM\b",
    r"\binterface\b",
    r"\bintegration\b",
    r"\btransfer\b",
    r"\brouting\b",
]

SOFTWARE_ANOMALY_PATTERNS = [
    r"\bsoftware device analysis\b",
    r"\bsoftware anomaly\b",
    r"\bsoftware analyzer\b",
    r"\bsoftware calculated\b",
    r"\bsoftware calculation\b",
    r"\bsoftware output\b",
    r"\bincorrect calculation(?:s)?\b",
    r"\bcalculation error\b",
    r"\bcalculated value(?:s)?\b",
    r"\bvalues differ\b",
    r"\bwrong value(?:s)?\b",
    r"\bwrong classification\b",
    r"\bincorrect classification\b",
    r"\bmiscalculation\b",
    r"\bCAPA\b",
    r"\bLenke classification\b",
    r"\bRoussouly classification\b",
    r"\bRousouly classification\b",
    r"\bBarrey Ratio\b",
    r"\bLumbar Lordosis\b",
    r"\bThoracic Kyphosis\b",
    r"\bSW3002\b",
]

SYSTEM_REGISTRATION_PATTERNS = [
    r"\bfalse .*error message",
    r"\berror message(?:s)?\b",
    r"\bout of sync\b",
    r"\bhard shutdown\b",
    r"\btablet and main unit\b",
    r"\bmain unit\b",
    r"\bregistration\b",
    r"\bnavigation\b",
    r"\btracking\b",
    r"\bCABT\b",
]

AI_OUTPUT_PATTERNS = [
    r"\bfalse negative\b",
    r"\bfalse positive\b",
    r"\bmiss(?:ed|ing)?\b",
    r"\bfailed to detect\b",
    r"\bdid not detect\b",
    r"\bnot detected\b",
    r"\bfailed to identify\b",
    r"\bincorrect(?:ly)?\b",
    r"\bwrong\b",
    r"\bmislabeled\b",
    r"\bincorrect label\b",
    r"\bwrong side\b",
    r"\bwrong anatomy\b",
    r"\bwrong location\b",
    r"\boutput\b",
    r"\bprediction\b",
    r"\bclassification\b",
    r"\bresult\b",
]

PHYSICAL_MR_PATTERNS = [
    r"\bburn(?:ed|s|ing)?\b",
    r"\bSAR\b",
    r"\bcoil\b",
    r"\bmagnet(?:ic)?\b",
    r"\bquench(?:ed)?\b",
    r"\boxygen tank\b",
    r"\bprojectile\b",
    r"\btable(?:top)?\b",
    r"\bheadphone\b",
    r"\bheadset\b",
    r"\bhearing loss\b",
    r"\btinnitus\b",
    r"\bacoustic\b",
    r"\bnoise\b",
    r"\bcaster\b",
    r"\block(?:ed|s)?\b",
    r"\bmechanical\b",
    r"\bcable\b",
    r"\bgantry\b",
    r"\bcollimator\b",
    r"\bradiation\b",
    r"\bx-ray\b",
    r"\bdetector\b",
    r"\blead tape\b",
    r"\bc-arm\b",
    r"\bbattery\b",
    r"\bfire\b",
    r"\bsmoke\b",
    r"\boverheat(?:ing)?\b",
    r"\bfield engineer\b",
    r"\breplacement\b",
    r"\bmaintenance\b",
    r"\bpart(?:s)?\b",
]

WORKFLOW_PATTERNS = [
    r"\bdelay(?:ed|s)?\b",
    r"\bnot notified\b",
    r"\bmissed notification\b",
    r"\balert(?:ed|ing|s)?\b",
    r"\brouting\b",
    r"\bworklist\b",
    r"\bPACS\b",
    r"\bRIS\b",
    r"\bEHR\b",
    r"\binterface\b",
    r"\bintegration\b",
    r"\bdowntime\b",
]

INPUT_QUALITY_PATTERNS = [
    r"\bimage quality\b",
    r"\bmotion artifact\b",
    r"\bartifact(?:s)?\b",
    r"\blow quality\b",
    r"\bprotocol\b",
    r"\bacquisition\b",
    r"\bDICOM\b",
    r"\bmetadata\b",
    r"\bslice\b",
]

CYBER_PATTERNS = [
    r"\bcyber\b",
    r"\bvulnerabilit(?:y|ies)\b",
    r"\bcredential(?:s)?\b",
    r"\blogin\b",
    r"\bpassword\b",
    r"\bunauthorized\b",
    r"\bauthentication\b",
    r"\bmalware\b",
    r"\baccess\b",
]

GENERALIZATION_PATTERNS = [
    r"\bdrift\b",
    r"\bgeneralizab(?:ility|le)\b",
    r"\bpopulation\b",
    r"\bsubgroup\b",
    r"\bscanner\b",
    r"\bsite\b",
    r"\bprotocol\b",
    r"\bsequence\b",
    r"\blocal configuration\b",
]

HUMAN_AI_PATTERNS = [
    r"\boverride\b",
    r"\bignored\b",
    r"\bmisinterpret(?:ed|ation)?\b",
    r"\buser accepted\b",
    r"\bradiologist accepted\b",
    r"\bclinician accepted\b",
    r"\brecommended\b",
    r"\bsuggestion\b",
]

UPDATE_PATTERNS = [
    r"\bsoftware update\b",
    r"\bsoftware change\b",
    r"\bmodel update\b",
    r"\balgorithm update\b",
    r"\bversion\b",
    r"\bupgrade(?:d|s)?\b",
    r"\bpatch(?:ed|es)?\b",
    r"\brollback\b",
]


def normalise_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def regex_hits(text: str, patterns: list[str]) -> list[str]:
    hits: list[str] = []
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return list(dict.fromkeys(hits))


def first_quote(text: str, hits: list[str], max_chars: int = 420) -> str:
    text = normalise_text(text)
    if not text:
        return ""
    low = text.lower()
    positions = []
    for h in hits:
        pos = low.find(h.lower())
        if pos >= 0:
            positions.append(pos)
    start = max(0, min(positions) - 140) if positions else 0
    quote = text[start:start + max_chars]
    if start > 0:
        quote = "..." + quote
    if start + max_chars < len(text):
        quote += "..."
    return quote


def clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 3)


def add_mode(modes: list[str], mode: str) -> None:
    if mode in FAILURE_MODES and mode not in modes:
        modes.append(mode)


def heuristic_extract(row: dict[str, Any]) -> dict[str, Any]:
    narrative = normalise_text(row.get("narrative_text"))
    event_type = (row.get("event_type") or "").lower()

    if not narrative or len(narrative) < 30:
        return validate_output({
            "possible_ai_relatedness": "insufficient_info",
            "failure_modes": ["insufficient_information"],
            "source_quote": narrative[:420],
            "confidence": 0.2,
            "needs_human_review": True,
            "limitations": ["Narrative was empty or too short to classify reliably."],
            "matched_keywords": [],
            "classifier_note": "insufficient_narrative",
            "device_context": _device_context(row),
        })

    strong_ai_hits = regex_hits(narrative, STRONG_AI_PATTERNS)
    weak_digital_hits = regex_hits(narrative, WEAK_DIGITAL_PATTERNS)
    ai_output_hits = regex_hits(narrative, AI_OUTPUT_PATTERNS)
    physical_hits = regex_hits(narrative, PHYSICAL_MR_PATTERNS)
    workflow_hits = regex_hits(narrative, WORKFLOW_PATTERNS)
    input_hits = regex_hits(narrative, INPUT_QUALITY_PATTERNS)
    cyber_hits = regex_hits(narrative, CYBER_PATTERNS)
    generalization_hits = regex_hits(narrative, GENERALIZATION_PATTERNS)
    human_ai_hits = regex_hits(narrative, HUMAN_AI_PATTERNS)
    update_hits = regex_hits(narrative, UPDATE_PATTERNS)
    software_anomaly_hits = regex_hits(narrative, SOFTWARE_ANOMALY_PATTERNS)
    system_registration_hits = regex_hits(narrative, SYSTEM_REGISTRATION_PATTERNS)

    matched_keywords = list(dict.fromkeys(
        strong_ai_hits + ai_output_hits + software_anomaly_hits + system_registration_hits + weak_digital_hits + physical_hits + workflow_hits + input_hits + cyber_hits + generalization_hits + human_ai_hits + update_hits
    ))

    has_strong_ai = bool(strong_ai_hits)
    has_weak_digital = bool(weak_digital_hits)
    has_software_anomaly = bool(software_anomaly_hits)
    has_system_registration = bool(system_registration_hits)
    has_physical = bool(physical_hits)

    modes: list[str] = []
    classifier_note = ""

    # Software-first medical devices often report "malfunctions" that are not physical hardware failures.
    # Treat explicit software anomaly / calculation / classification / registration-sync language as
    # candidate software-output evidence even when the narrative does not literally say "AI".
    if has_software_anomaly or has_system_registration:
        if has_software_anomaly:
            add_mode(modes, "software_anomaly_or_calculation_error")
        if regex_hits(narrative, [r"\bclassification\b", r"\bLenke\b", r"\bRoussouly\b", r"\bRousouly\b", r"\bBarrey\b", r"\bLordosis\b", r"\bKyphosis\b", r"\bvalues differ\b", r"\bcalculated\b", r"\bcalculation\b"]):
            add_mode(modes, "clinical_measurement_or_classification_error")
        if has_system_registration:
            add_mode(modes, "software_system_synchronization_or_registration_issue")
            add_mode(modes, "workflow_integration_issue")
        if update_hits or regex_hits(narrative, [r"\bversion\b", r"\bV\d", r"\bSW3002\b", r"\bCAPA\b"]):
            add_mode(modes, "model_update_or_version_issue")
        if regex_hits(narrative, [r"\bsurgeon disagreed\b", r"\bclinician\b", r"\buser\b", r"\bhealthcare provider\b"]):
            add_mode(modes, "human_ai_interaction_issue")
        relatedness = "possible"
        confidence = 0.72
        classifier_note = "explicit_software_anomaly_or_clinical_calculation_issue"

    # Explicit physical MR/device safety cases: keep as non-AI unless the narrative also explicitly says AI/CAD/algorithm/reconstruction/alert/software anomaly etc.
    elif has_physical and not has_strong_ai:
        add_mode(modes, "device_or_hardware_malfunction")
        relatedness = "unlikely"
        confidence = 0.82
        classifier_note = "physical_device_event_without_explicit_ai_or_software_output_evidence"
    else:
        if has_physical:
            add_mode(modes, "device_or_hardware_malfunction")

        if cyber_hits and (has_strong_ai or has_weak_digital):
            add_mode(modes, "cybersecurity_or_access_issue")

        if workflow_hits and (has_strong_ai or has_weak_digital):
            add_mode(modes, "workflow_integration_issue")

        if input_hits and has_strong_ai:
            add_mode(modes, "input_data_quality_issue")

        # Require explicit AI/reconstruction/algorithm/model context for update/version issues.
        if update_hits and (has_strong_ai or re.search(r"\b(software|firmware|algorithm|reconstruction)\b", narrative, re.I)):
            add_mode(modes, "model_update_or_version_issue")

        if generalization_hits and has_strong_ai:
            add_mode(modes, "generalizability_or_drift_concern")

        if human_ai_hits and has_strong_ai:
            add_mode(modes, "human_ai_interaction_issue")

        # AI output errors only count when an AI/digital output context exists.
        if ai_output_hits and has_strong_ai:
            if regex_hits(narrative, [r"\bfalse negative\b", r"\bmiss(?:ed|ing)?\b", r"\bfailed to detect\b", r"\bdid not detect\b", r"\bnot detected\b", r"\bfailed to identify\b"]):
                add_mode(modes, "false_negative_or_missed_finding")
            if regex_hits(narrative, [r"\bfalse positive\b", r"\bincorrect alert\b", r"\bwrong alert\b", r"\bunnecessary alert\b"]):
                add_mode(modes, "false_positive_or_overalert")
            if regex_hits(narrative, [r"\bmislabeled\b", r"\bincorrect label\b", r"\bwrong side\b", r"\bwrong anatomy\b", r"\bwrong location\b", r"\bsegmentation error\b"]):
                add_mode(modes, "localization_or_labeling_error")

        if has_strong_ai and any(m in modes for m in [
            "false_negative_or_missed_finding",
            "false_positive_or_overalert",
            "localization_or_labeling_error",
        ]):
            relatedness = "likely"
            confidence = 0.78
            classifier_note = "explicit_ai_output_failure_language"
        elif has_strong_ai and any(m in modes for m in [
            "workflow_integration_issue",
            "input_data_quality_issue",
            "model_update_or_version_issue",
            "generalizability_or_drift_concern",
            "human_ai_interaction_issue",
            "software_anomaly_or_calculation_error",
            "clinical_measurement_or_classification_error",
            "software_system_synchronization_or_registration_issue",
        ]):
            relatedness = "possible"
            confidence = 0.66
            classifier_note = "explicit_ai_or_algorithm_context_with_relevant_failure_theme"
        elif cyber_hits and has_weak_digital:
            relatedness = "possible"
            confidence = 0.58
            classifier_note = "digital_infrastructure_issue_may_affect_ai_workflow"
        elif modes:
            relatedness = "unlikely" if modes == ["device_or_hardware_malfunction"] or "device_or_hardware_malfunction" in modes else "insufficient_info"
            confidence = 0.58 if relatedness == "unlikely" else 0.34
            classifier_note = "no_explicit_ai_failure_evidence"
        else:
            relatedness = "insufficient_info"
            confidence = 0.28
            modes = ["insufficient_information"]
            classifier_note = "no_clear_failure_mode"

    # Do not pollute unlikely hardware cases with speculative AI-like modes.
    if relatedness == "unlikely" and "device_or_hardware_malfunction" in modes:
        modes = ["device_or_hardware_malfunction"]

    needs_review = relatedness in {"likely", "possible"} or event_type in {"death", "injury"} or bool(row.get("link_needs_review"))

    return validate_output({
        "possible_ai_relatedness": relatedness,
        "failure_modes": modes,
        "source_quote": first_quote(narrative, matched_keywords),
        "confidence": clamp(confidence),
        "needs_human_review": bool(needs_review),
        "limitations": [
            "Conservative heuristic fallback, not a validated clinical or regulatory judgement.",
            "MAUDE/openFDA reports are passive public reports and cannot establish causality or incidence.",
            "Physical device events are marked unlikely AI-related unless explicit AI/algorithm/reconstruction/workflow/software-output evidence appears in the narrative.",
        ],
        "matched_keywords": matched_keywords[:16],
        "classifier_note": classifier_note,
        "device_context": _device_context(row),
    })


def _device_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": str(row.get("device_id")),
        "canonical_name": row.get("canonical_name"),
        "brand_name_in_event": row.get("brand_name"),
        "event_manufacturer": row.get("manufacturer_name"),
        "link_match_method": row.get("match_method"),
        "link_match_confidence": float(row.get("match_confidence") or 0),
        "link_needs_review": bool(row.get("link_needs_review")),
    }


def validate_output(output: dict[str, Any]) -> dict[str, Any]:
    relatedness = output.get("possible_ai_relatedness")
    if relatedness not in AI_RELATEDNESS:
        relatedness = "insufficient_info"
    modes = output.get("failure_modes") or []
    if isinstance(modes, str):
        modes = [modes]
    modes = [m for m in modes if m in FAILURE_MODES]
    if not modes:
        modes = ["insufficient_information"]
    output["possible_ai_relatedness"] = relatedness
    output["failure_modes"] = list(dict.fromkeys(modes))
    output["source_quote"] = str(output.get("source_quote") or "")[:900]
    output["confidence"] = clamp(float(output.get("confidence") or 0.0))
    output["needs_human_review"] = bool(output.get("needs_human_review", True))
    output.setdefault("limitations", [])
    output.setdefault("matched_keywords", [])
    output.setdefault("classifier_note", "")
    output.setdefault("extraction_version", PROMPT_VERSION)
    return output


def openai_extract(row: dict[str, Any], model: str) -> dict[str, Any]:
    # Import lazily so heuristic mode works without OpenAI installed.
    from openai import OpenAI
    from pydantic import BaseModel, Field

    class FailureModeExtraction(BaseModel):
        possible_ai_relatedness: str = Field(description="likely, possible, unlikely, or insufficient_info")
        failure_modes: list[str]
        source_quote: str
        confidence: float
        needs_human_review: bool
        limitations: list[str]
        matched_keywords: list[str] = []
        classifier_note: str = ""

    client = OpenAI()
    system = (
        "You classify public medical-device adverse-event narratives for AI-enabled medical-device governance. "
        "Be very conservative. Do not infer causality. A device being on the FDA AI-enabled list does NOT make every report AI-related. "
        "Physical MRI/ultrasound/x-ray events such as burns, coils, SAR, acoustic noise, quench, table movement, projectile incidents, batteries, cables, collimators, or maintenance are usually unlikely AI-related unless the narrative explicitly mentions an AI algorithm, CAD, automated detection, segmentation, reconstruction, alert, notification, triage, model output, software anomaly, incorrect calculation, wrong classification, or registration/synchronization software failure. "
        "Return only schema-valid JSON."
    )
    user = f"""
Target FDA AI-enabled device: {row.get('canonical_name')}
Target manufacturer: {row.get('manufacturer')}
Link method: {row.get('match_method')} confidence={row.get('match_confidence')} needs_review={row.get('link_needs_review')}
Event brand name: {row.get('brand_name')}
Event manufacturer: {row.get('manufacturer_name')}
Event type: {row.get('event_type')}
Date received: {row.get('date_received')}

Allowed relatedness values: likely, possible, unlikely, insufficient_info.
Allowed failure modes: {sorted(FAILURE_MODES)}.

Classification rules:
- likely: explicit AI/algorithm/CAD/segmentation/reconstruction/triage/alert/model-output failure, e.g. false negative, false positive, wrong output, wrong label, missed finding.
- possible: explicit AI/digital-workflow/software-output context with plausible contribution, e.g. alert routing, PACS/RIS integration, model/software update, reconstruction/input quality issue, software anomaly, incorrect calculation/classification, or registration/synchronization error.
- unlikely: physical device or operational event without explicit AI/software-output evidence.
- insufficient_info: too vague to determine.

Narrative:
{normalise_text(row.get('narrative_text'))[:5000]}
""".strip()

    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        text_format=FailureModeExtraction,
    )
    parsed = response.output_parsed.model_dump()
    parsed["device_context"] = _device_context(row)
    return validate_output(parsed)


def fetch_candidate_events(
    conn,
    *,
    limit: int,
    device_name: str | None,
    only_unprocessed: bool,
    min_match_confidence: float,
    include_review_links: bool,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ["ae.narrative_text IS NOT NULL", "length(ae.narrative_text) > 0"]

    if device_name:
        where.append("d.canonical_name ILIKE %s")
        params.append(f"%{device_name}%")

    if only_unprocessed:
        where.append(
            """NOT EXISTS (
                SELECT 1 FROM llm_extractions lx
                WHERE lx.source_table = 'adverse_events'
                  AND lx.source_id = ae.id
                  AND lx.extraction_type = %s
                  AND lx.prompt_version = %s
            )"""
        )
        params.extend([EXTRACTION_TYPE, PROMPT_VERSION])

    where.append("l.match_confidence >= %s")
    params.append(min_match_confidence)
    if not include_review_links:
        where.append("l.needs_review = FALSE")

    sql = f"""
        SELECT
            ae.id AS adverse_event_id,
            ae.report_number,
            ae.mdr_report_key,
            ae.event_type,
            ae.date_received,
            ae.event_date,
            ae.manufacturer_name,
            ae.brand_name,
            ae.generic_name,
            ae.product_code,
            ae.narrative_text,
            d.id AS device_id,
            d.canonical_name,
            d.manufacturer,
            l.match_method,
            l.match_confidence,
            l.needs_review AS link_needs_review
        FROM adverse_events ae
        JOIN device_adverse_event_links l ON l.adverse_event_id = ae.id
        JOIN devices d ON d.id = l.device_id
        WHERE {' AND '.join(where)}
        ORDER BY
            l.match_confidence DESC,
            ae.date_received DESC NULLS LAST,
            ae.report_number
        LIMIT %s
    """
    params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def upsert_extraction(conn, row: dict[str, Any], output: dict[str, Any], *, model_name: str, dry_run: bool) -> None:
    if dry_run:
        return
    conn.execute(
        """
        INSERT INTO llm_extractions (
            source_table, source_id, extraction_type, model_name, prompt_version,
            json_output, confidence, needs_human_review
        )
        VALUES ('adverse_events', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_table, source_id, extraction_type, prompt_version)
        DO UPDATE SET
            model_name = EXCLUDED.model_name,
            json_output = EXCLUDED.json_output,
            confidence = EXCLUDED.confidence,
            needs_human_review = EXCLUDED.needs_human_review,
            created_at = now()
        """,
        (
            row["adverse_event_id"],
            EXTRACTION_TYPE,
            model_name,
            PROMPT_VERSION,
            Jsonb(output),
            output.get("confidence"),
            output.get("needs_human_review", True),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify adverse-event narratives into AI-device failure modes.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum number of adverse events to process.")
    parser.add_argument("--device-name", type=str, default=None, help="Optional device name filter, e.g. 'MAGNETOM'.")
    parser.add_argument("--mode", choices=["auto", "openai", "heuristic"], default="auto")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--include-processed", action="store_true", help="Reprocess rows that already have an extraction for this prompt version.")
    parser.add_argument("--min-match-confidence", type=float, default=0.85, help="Default keeps only stronger device-event links.")
    parser.add_argument("--include-review-links", action="store_true", help="Include broad/low-confidence links. Not recommended for public demos.")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to database.")
    args = parser.parse_args()

    use_openai = args.mode == "openai" or (args.mode == "auto" and bool(os.getenv("OPENAI_API_KEY")))
    model_name = args.model if use_openai else "heuristic_rules_v0_3_conservative"

    with get_conn() as conn:
        rows = fetch_candidate_events(
            conn,
            limit=args.limit,
            device_name=args.device_name,
            only_unprocessed=not args.include_processed,
            min_match_confidence=args.min_match_confidence,
            include_review_links=args.include_review_links,
        )
        if not rows:
            print("No candidate adverse-event rows found under the current strict matching filters.")
            print("Try --include-review-links only for internal QA, not public demos.")
            return

        print(f"Processing {len(rows)} adverse events using {model_name}...")
        for row in tqdm(rows):
            if use_openai:
                try:
                    output = openai_extract(row, args.model)
                    model_for_row = args.model
                except Exception as exc:
                    print(f"OpenAI extraction failed for {row.get('report_number')}: {exc}. Falling back to heuristic.")
                    output = heuristic_extract(row)
                    model_for_row = "heuristic_rules_v0_3_after_openai_error"
            else:
                output = heuristic_extract(row)
                model_for_row = model_name

            output = validate_output(output)
            if args.dry_run:
                print("\n---")
                print(f"Device: {row.get('canonical_name')} | Brand: {row.get('brand_name')} | Report: {row.get('report_number')} | Event: {row.get('event_type')} | match={row.get('match_confidence')} review={row.get('link_needs_review')}")
                print(json.dumps(output, indent=2))
            upsert_extraction(conn, row, output, model_name=model_for_row, dry_run=args.dry_run)

        if not args.dry_run:
            print("Saved extractions to llm_extractions.")


if __name__ == "__main__":
    main()
