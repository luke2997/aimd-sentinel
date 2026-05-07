from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .db import get_conn

PROMPT_VERSION = "latest"  # generator now joins the latest adverse-event extraction


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value or "device"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def get_one_device(conn, name: str | None, device_id: str | None) -> dict[str, Any]:
    if device_id:
        row = conn.execute("SELECT * FROM devices WHERE id = %s", (device_id,)).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM devices
            WHERE canonical_name ILIKE %s
            ORDER BY latest_decision_date DESC NULLS LAST
            LIMIT 1
            """,
            (f"%{name}%",),
        ).fetchone()
    if not row:
        raise SystemExit("Device not found. Try a broader --device-name value.")
    return row


def rows(conn, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return list(conn.execute(sql, params).fetchall())


def vendor_questions(device: dict[str, Any], mode_counts: Counter[str], evidence_counts: dict[str, int], review_link_count: int) -> list[str]:
    questions = [
        "What exact clinical workflow and user role was the device validated for, and does that match our proposed deployment?",
        "What patient populations, scanner/protocol types, and site types were included in validation?",
        "What is the required human oversight step before clinical action is taken?",
        "How are software/model updates validated, communicated, and rolled back if problems occur?",
        "What local performance-monitoring dashboard or export does the vendor provide after deployment?",
    ]
    if review_link_count:
        questions.append(
            "Several public records are broad manufacturer/product-code matches rather than clean device-name matches. Can the vendor confirm which public complaints, field actions, or recalls are relevant to this exact product/version?"
        )
    if mode_counts.get("software_anomaly_or_calculation_error", 0) or mode_counts.get("clinical_measurement_or_classification_error", 0):
        questions.extend([
            "Which software versions were affected by the reported calculation/classification anomalies, and what CAPA or field action closed them?",
            "What validation set and acceptance criteria are used for clinical measurements/classifications after each software release?",
            "How should users verify or override questionable calculated outputs before they affect clinical or procedural decisions?",
        ])
    if mode_counts.get("software_system_synchronization_or_registration_issue", 0):
        questions.append("What safeguards detect tablet/main-unit, registration, tracking, or navigation synchronization failures during a case?")
    if mode_counts.get("workflow_integration_issue", 0):
        questions.append("Linked narratives suggest workflow/integration themes. How are alerts, registration states, messages, and outputs routed, logged, escalated, and audited?")
    if mode_counts.get("false_negative_or_missed_finding", 0):
        questions.append("What known false-negative patterns exist, and what human review process is recommended to catch misses?")
    if mode_counts.get("false_positive_or_overalert", 0):
        questions.append("What false-positive rate should we expect locally, and how should we monitor alert fatigue?")
    if evidence_counts.get("events", 0) == 0:
        questions.append("No high-confidence adverse-event narratives were found in this dataset. What post-market complaints or field actions has the vendor observed outside public FDA/openFDA data?")
    return questions

def monitoring_plan(mode_counts: Counter[str]) -> list[str]:
    plan = [
        "Monthly case volume processed by the AI device.",
        "Number and proportion of failed/errored cases.",
        "Clinician override, disagreement, or feedback events.",
        "Representative false-positive and false-negative review sample.",
        "Turnaround-time or notification-latency before and after deployment.",
        "Scanner/protocol/site distribution of processed cases, where applicable.",
        "All software/model version changes with pre/post-change checks.",
    ]
    if mode_counts.get("software_anomaly_or_calculation_error", 0) or mode_counts.get("clinical_measurement_or_classification_error", 0):
        plan.extend([
            "Track calculated-output disagreements by software version, measurement type, user, and case type.",
            "Review a sample of software-generated measurements/classifications against expert manual review after each release.",
            "Maintain a local log of vendor CAPA/field-action notices and confirm installed versions are not affected.",
        ])
    if mode_counts.get("software_system_synchronization_or_registration_issue", 0):
        plan.append("Track registration/synchronization errors, hard shutdowns, restart sequences, and cases completed after system error messages.")
    if mode_counts.get("workflow_integration_issue", 0):
        plan.append("Audit alert/message delivery timestamps and missed/delayed notifications across connected systems.")
    if mode_counts.get("input_data_quality_issue", 0):
        plan.append("Track rejected or low-quality inputs by acquisition protocol, scanner, operator, and site.")
    return plan

def summarise_events(events: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], Counter[str]]:
    mode_counts: Counter[str] = Counter()
    relatedness_counts: Counter[str] = Counter()
    event_type_counts: Counter[str] = Counter()
    for ev in events:
        event_type_counts[ev.get("event_type") or "unknown"] += 1
        extraction = ev.get("json_output") or {}
        if extraction:
            relatedness_counts[extraction.get("possible_ai_relatedness", "unclassified")] += 1
            for mode in extraction.get("failure_modes") or []:
                mode_counts[mode] += 1
        else:
            relatedness_counts["not_extracted"] += 1
    return mode_counts, relatedness_counts, event_type_counts



def interpretation_summary(evidence_counts: dict[str, int], mode_counts: Counter[str], relatedness_counts: Counter[str]) -> str:
    events = evidence_counts.get("events", 0)
    review_events = evidence_counts.get("review_events", 0)
    likely = relatedness_counts.get("likely", 0)
    possible = relatedness_counts.get("possible", 0)
    unlikely = relatedness_counts.get("unlikely", 0)
    not_extracted = relatedness_counts.get("not_extracted", 0)
    hardware = mode_counts.get("device_or_hardware_malfunction", 0)
    software_calc = mode_counts.get("software_anomaly_or_calculation_error", 0) + mode_counts.get("clinical_measurement_or_classification_error", 0)
    system_sync = mode_counts.get("software_system_synchronization_or_registration_issue", 0)

    if events == 0 and review_events > 0:
        return (
            f"No high-confidence device-specific adverse-event records were found under the strict link filter. "
            f"There are {review_events} broad public records that may be useful leads, but they should not be treated as device-specific until manually reviewed. "
            "This is a positive evidence-discipline result, not a safety clearance."
        )
    if events == 0:
        return (
            "No high-confidence public adverse-event records were found in the current dataset. "
            "The next step is to ask the vendor for post-market complaint summaries, known limitations, update history, and local monitoring guidance."
        )
    if not_extracted == events:
        return (
            f"{events} high-confidence event links are present, but classifier extraction has not been run for them yet. "
            "Run extract_failure_modes.py and regenerate this dossier before using the AI-specific classification section."
        )
    if software_calc or system_sync:
        return (
            f"The high-confidence records contain software-specific malfunction language. Current extraction found {possible} possible and {likely} likely AI/software-related records, "
            f"including {software_calc} calculation/classification/software-anomaly themes and {system_sync} registration/synchronization themes. "
            "Treat these as source-backed candidate governance themes requiring human review, not as confirmed causality or incidence."
        )
    if hardware >= max(1, int(events * 0.70)) and likely == 0 and possible == 0:
        return (
            f"The high-confidence public event records appear dominated by physical device, hardware, or operational events. "
            f"Current classifier output shows {unlikely} unlikely AI-related records. "
            "For external demos, frame this as a governance/evidence-gating example, not as evidence of an AI safety signal."
        )
    if hardware >= max(1, int(events * 0.70)) and likely == 0:
        return (
            f"The high-confidence public event records are mostly physical device, hardware, or operational reports, with {possible} possible software/workflow themes requiring manual review. "
            "Do not describe this as an AI safety signal without validation."
        )
    if likely or possible:
        return (
            f"The classifier found {likely} likely and {possible} possible AI/software-related records among high-confidence links. "
            "These should be manually validated before any external claim is made. Treat them as candidate narrative themes, not confirmed causality."
        )
    return (
        "High-confidence public event links exist, but current extraction does not show a clear AI-specific safety signal. "
        "Use the dossier to guide procurement questions and local monitoring rather than to make a safety conclusion."
    )

def build_html(
    device: dict[str, Any],
    authorizations: list[dict[str, Any]],
    events: list[dict[str, Any]],
    review_events: list[dict[str, Any]],
    enforcements: list[dict[str, Any]],
    review_enforcements: list[dict[str, Any]],
    recalls: list[dict[str, Any]],
    review_recalls: list[dict[str, Any]],
    *,
    min_match_confidence: float,
    include_review_links: bool,
) -> tuple[str, dict[str, Any]]:
    mode_counts, relatedness_counts, event_type_counts = summarise_events(events)
    review_mode_counts, review_relatedness_counts, _ = summarise_events(review_events)

    evidence_counts = {
        "authorizations": len(authorizations),
        "events": len(events),
        "review_events": len(review_events),
        "enforcements": len(enforcements),
        "review_enforcements": len(review_enforcements),
        "recalls": len(recalls),
        "review_recalls": len(review_recalls),
    }
    interpretation = interpretation_summary(evidence_counts, mode_counts, relatedness_counts)
    questions = vendor_questions(device, mode_counts, evidence_counts, len(review_events))
    monitoring = monitoring_plan(mode_counts)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    auth_rows = "".join(
        f"<tr><td>{esc(a.get('submission_number'))}</td><td>{esc(a.get('decision_date'))}</td><td>{esc(a.get('product_code'))}</td><td>{esc(a.get('decision_description'))}</td><td>{esc(a.get('applicant'))}</td></tr>"
        for a in authorizations
    ) or "<tr><td colspan='5'>No linked authorization records.</td></tr>"

    mode_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in mode_counts.most_common()
    ) or "<tr><td colspan='2'>No high-confidence failure-mode extractions yet.</td></tr>"

    relatedness_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in relatedness_counts.most_common()
    ) or "<tr><td colspan='2'>No high-confidence adverse-event rows.</td></tr>"

    review_relatedness_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in review_relatedness_counts.most_common()
    ) or "<tr><td colspan='2'>No review-only records included.</td></tr>"

    def event_row(ev: dict[str, Any]) -> str:
        extraction = ev.get("json_output") or {}
        quote = extraction.get("source_quote") or (ev.get("narrative_text") or "")[:260]
        return f"""
        <tr>
          <td>{esc(ev.get('report_number'))}</td>
          <td>{esc(ev.get('date_received'))}</td>
          <td>{esc(ev.get('event_type'))}</td>
          <td>{esc(ev.get('brand_name'))}</td>
          <td>{esc(ev.get('match_method'))}</td>
          <td>{esc(ev.get('match_confidence'))}</td>
          <td>{esc('yes' if ev.get('link_needs_review') else 'no')}</td>
          <td>{esc(extraction.get('possible_ai_relatedness', 'not_extracted'))}</td>
          <td>{esc(', '.join(extraction.get('failure_modes', [])))}</td>
          <td>{esc(quote)}</td>
        </tr>
        """

    recent_event_rows = "".join(event_row(ev) for ev in events[:15]) or "<tr><td colspan='10'>No high-confidence linked adverse-event records.</td></tr>"
    review_event_rows = "".join(event_row(ev) for ev in review_events[:15]) or "<tr><td colspan='10'>No broad/review linked adverse-event records.</td></tr>"

    enf_rows = "".join(
        f"<tr><td>{esc(e.get('recall_number'))}</td><td>{esc(e.get('classification'))}</td><td>{esc(e.get('recall_initiation_date'))}</td><td>{esc(e.get('reason_for_recall'))}</td></tr>"
        for e in enforcements[:20]
    ) or "<tr><td colspan='4'>No linked enforcement records.</td></tr>"

    rec_rows = "".join(
        f"<tr><td>{esc(r.get('recall_number'))}</td><td>{esc(r.get('recall_classification'))}</td><td>{esc(r.get('date_posted'))}</td><td>{esc(r.get('root_cause_description'))}</td></tr>"
        for r in recalls[:20]
    ) or "<tr><td colspan='4'>No high-confidence linked recall records.</td></tr>"

    review_enf_rows = "".join(
        f"<tr><td>{esc(e.get('recall_number'))}</td><td>{esc(e.get('classification'))}</td><td>{esc(e.get('recall_initiation_date'))}</td><td>{esc(e.get('match_method'))}</td><td>{esc(e.get('match_confidence'))}</td><td>{esc(e.get('reason_for_recall'))}</td></tr>"
        for e in review_enforcements[:20]
    ) or "<tr><td colspan='6'>No broad/review enforcement records.</td></tr>"

    review_rec_rows = "".join(
        f"<tr><td>{esc(r.get('recall_number'))}</td><td>{esc(r.get('recall_classification'))}</td><td>{esc(r.get('date_posted'))}</td><td>{esc(r.get('match_method'))}</td><td>{esc(r.get('match_confidence'))}</td><td>{esc(r.get('root_cause_description'))}</td></tr>"
        for r in review_recalls[:20]
    ) or "<tr><td colspan='6'>No broad/review recall records.</td></tr>"

    question_items = "".join(f"<li>{esc(q)}</li>" for q in questions)
    monitoring_items = "".join(f"<li>{esc(m)}</li>" for m in monitoring)

    review_note = ""
    caution_parts = []
    if review_events:
        caution_parts.append(f"{len(review_events)} adverse-event records")
    if review_enforcements:
        caution_parts.append(f"{len(review_enforcements)} enforcement records")
    if review_recalls:
        caution_parts.append(f"{len(review_recalls)} recall records")
    if caution_parts:
        review_note = f"""
        <div class="warning soft">
          <strong>Record-linking caution:</strong> {', '.join(caution_parts)} are broad or low-confidence matches and require human review.
          They are shown separately and are not counted as high-confidence device-specific evidence. This avoids overclaiming when public records match only product code, manufacturer, generic product phrases, or device family.
        </div>
        """

    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>AIMD Sentinel Dossier - {esc(device.get('canonical_name'))}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.45; max-width: 1180px; margin: 40px auto; padding: 0 24px; color: #111; }}
    h1, h2, h3 {{ line-height: 1.2; }}
    .meta {{ color: #555; }}
    .badge {{ display: inline-block; padding: 3px 8px; border: 1px solid #999; border-radius: 999px; font-size: 12px; margin-right: 5px; margin-bottom: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 28px; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
    th {{ background: #f6f6f6; text-align: left; }}
    .warning {{ border-left: 4px solid #666; background: #f7f7f7; padding: 12px 16px; margin: 18px 0; }}
    .soft {{ border-left-color: #aaa; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 14px; }}
    .big {{ font-size: 28px; font-weight: 700; }}
    .small {{ font-size: 12px; color: #555; }}
  </style>
</head>
<body>
  <h1>AI Medical Device Governance Dossier</h1>
  <h2>{esc(device.get('canonical_name'))}</h2>
  <p class="meta">Generated by AIMD Sentinel prototype at {generated_at}. Public-data review only.</p>

  <p>
    <span class="badge">Manufacturer: {esc(device.get('manufacturer'))}</span>
    <span class="badge">Panel: {esc(device.get('panel'))}</span>
    <span class="badge">Product code: {esc(device.get('primary_product_code'))}</span>
    <span class="badge">Latest submission: {esc(device.get('latest_submission_number'))}</span>
    <span class="badge">Event filter: confidence ≥ {min_match_confidence}, review links {'included' if include_review_links else 'separated'}</span>
  </p>

  <div class="warning">
    <strong>Important limitation:</strong> This dossier is for procurement, governance, and safety-review support. It does not establish clinical or legal causality, does not estimate incidence rates, and does not replace FDA, regulatory, clinical, or legal review. MAUDE/openFDA reports are passive reports and may be incomplete, duplicate, inaccurate, or unverified.
  </div>
  {review_note}

  <h2>1. Evidence snapshot</h2>
  <div class="grid">
    <div class="card"><div class="big">{len(authorizations)}</div><div>authorization records</div></div>
    <div class="card"><div class="big">{len(events)}</div><div>high-confidence linked adverse events</div></div>
    <div class="card"><div class="big">{len(review_events)}</div><div>broad/review adverse-event links</div></div>
    <div class="card"><div class="big">{len(enforcements)}</div><div>high-confidence enforcement actions</div></div>
    <div class="card"><div class="big">{len(review_enforcements)}</div><div>broad/review enforcement links</div></div>
    <div class="card"><div class="big">{len(recalls)}</div><div>high-confidence recall records</div></div>
    <div class="card"><div class="big">{len(review_recalls)}</div><div>broad/review recall links</div></div>
  </div>

  <h2>1A. Product interpretation</h2>
  <div class="warning soft">{esc(interpretation)}</div>

  <h2>2. Authorization records</h2>
  <table><tr><th>Submission</th><th>Decision date</th><th>Product code</th><th>Decision</th><th>Applicant</th></tr>{auth_rows}</table>

  <h2>3. AI-specific adverse-event classification</h2>
  <h3>High-confidence AI-relatedness counts</h3>
  <table><tr><th>Classification</th><th>Count</th></tr>{relatedness_rows}</table>
  <h3>High-confidence failure-mode counts</h3>
  <table><tr><th>Failure mode</th><th>Count</th></tr>{mode_rows}</table>

  <h3>Recent high-confidence adverse-event examples</h3>
  <table>
    <tr><th>Report</th><th>Date</th><th>Event type</th><th>Brand</th><th>Match method</th><th>Confidence</th><th>Review?</th><th>AI-relatedness</th><th>Failure modes</th><th>Evidence quote / narrative preview</th></tr>
    {recent_event_rows}
  </table>

  <h3>Broad or low-confidence adverse-event links requiring review</h3>
  <p class="small">These are useful leads, but should not be presented as device-specific until checked.</p>
  <table><tr><th>Report</th><th>Date</th><th>Event type</th><th>Brand</th><th>Match method</th><th>Confidence</th><th>Review?</th><th>AI-relatedness</th><th>Failure modes</th><th>Evidence quote / narrative preview</th></tr>{review_event_rows}</table>

  <h2>4. Enforcement and recall history</h2>
  <h3>High-confidence enforcement actions</h3>
  <table><tr><th>Recall number</th><th>Classification</th><th>Initiation date</th><th>Reason</th></tr>{enf_rows}</table>
  <h3>Broad/review enforcement records</h3>
  <p class="small">These are useful leads, but should not be presented as device-specific until checked.</p>
  <table><tr><th>Recall number</th><th>Classification</th><th>Initiation date</th><th>Match method</th><th>Confidence</th><th>Reason</th></tr>{review_enf_rows}</table>
  <h3>High-confidence recall records</h3>
  <table><tr><th>Recall number</th><th>Classification</th><th>Date posted</th><th>Root cause</th></tr>{rec_rows}</table>
  <h3>Broad/review recall records</h3>
  <p class="small">These are useful leads, but should not be presented as device-specific until checked.</p>
  <table><tr><th>Recall number</th><th>Classification</th><th>Date posted</th><th>Match method</th><th>Confidence</th><th>Root cause</th></tr>{review_rec_rows}</table>

  <h2>5. Vendor due-diligence questions</h2><ol>{question_items}</ol>
  <h2>6. Suggested local monitoring plan</h2><ol>{monitoring_items}</ol>
  <h2>7. Current prototype verdict</h2>
  <p>This is a <strong>governance review dossier</strong>, not a safety verdict. The next human-review step is to inspect low-confidence device-event links, validate source quotes, and decide which vendor questions are relevant to the hospital's actual use case.</p>
</body>
</html>
"""

    json_summary = {
        "device_id": str(device.get("id")),
        "device_name": device.get("canonical_name"),
        "generated_at": generated_at,
        "min_match_confidence": min_match_confidence,
        "include_review_links": include_review_links,
        "evidence_counts": evidence_counts,
        "ai_relatedness_counts": dict(relatedness_counts),
        "review_ai_relatedness_counts": dict(review_relatedness_counts),
        "failure_mode_counts": dict(mode_counts),
        "interpretation": interpretation,
        "vendor_questions": questions,
        "monitoring_plan": monitoring,
    }
    return html_doc, json_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a quality-gated HTML AI-device governance dossier.")
    parser.add_argument("--device-name", type=str, default=None, help="Device name filter, e.g. 'AIR Recon DL'.")
    parser.add_argument("--device-id", type=str, default=None)
    parser.add_argument("--out-dir", type=str, default="reports")
    parser.add_argument("--max-events", type=int, default=250)
    parser.add_argument("--min-match-confidence", type=float, default=0.85, help="Default excludes broad product-code/manufacturer links.")
    parser.add_argument("--include-review-links", action="store_true", help="Count review links as high-confidence events. Not recommended for public demos.")
    args = parser.parse_args()

    if not args.device_name and not args.device_id:
        raise SystemExit("Provide --device-name or --device-id")

    with get_conn() as conn:
        device = get_one_device(conn, args.device_name, args.device_id)
        device_id = device["id"]

        authorizations = rows(conn, """
            SELECT a.*
            FROM authorizations a
            JOIN device_authorization_links l ON l.authorization_id = a.id
            WHERE l.device_id = %s
            ORDER BY a.decision_date DESC NULLS LAST
        """, (device_id,))

        base_event_sql = f"""
            SELECT ae.*, lx.json_output, l.match_method, l.matched_on, l.match_confidence, l.needs_review AS link_needs_review
            FROM adverse_events ae
            JOIN device_adverse_event_links l ON l.adverse_event_id = ae.id
            LEFT JOIN LATERAL (
                SELECT json_output
                FROM llm_extractions lx
                WHERE lx.source_table = 'adverse_events'
                  AND lx.source_id = ae.id
                  AND lx.extraction_type = 'adverse_event_failure_mode'
                ORDER BY lx.created_at DESC
                LIMIT 1
            ) lx ON TRUE
            WHERE l.device_id = %s
              AND {{filter_clause}}
            ORDER BY ae.date_received DESC NULLS LAST
            LIMIT %s
        """

        if args.include_review_links:
            event_filter = "l.match_confidence >= %s"
            event_params = (device_id, args.min_match_confidence, args.max_events)
            review_filter = "FALSE"
            review_params = (device_id, args.max_events)
        else:
            event_filter = "l.match_confidence >= %s AND l.needs_review = FALSE"
            event_params = (device_id, args.min_match_confidence, args.max_events)
            review_filter = "(l.match_confidence < %s OR l.needs_review = TRUE)"
            review_params = (device_id, args.min_match_confidence, args.max_events)

        events = rows(conn, base_event_sql.replace("{filter_clause}", event_filter), event_params)
        review_events = rows(conn, base_event_sql.replace("{filter_clause}", review_filter), review_params)

        link_filter = "l.match_confidence >= %s AND l.needs_review = FALSE"
        review_link_filter = "(l.match_confidence < %s OR l.needs_review = TRUE)"

        enforcements = rows(conn, f"""
            SELECT ea.*, l.match_method, l.matched_on, l.match_confidence, l.needs_review AS link_needs_review
            FROM enforcement_actions ea
            JOIN device_enforcement_links l ON l.enforcement_action_id = ea.id
            WHERE l.device_id = %s AND {link_filter}
            ORDER BY ea.recall_initiation_date DESC NULLS LAST
        """, (device_id, args.min_match_confidence))

        review_enforcements = rows(conn, f"""
            SELECT ea.*, l.match_method, l.matched_on, l.match_confidence, l.needs_review AS link_needs_review
            FROM enforcement_actions ea
            JOIN device_enforcement_links l ON l.enforcement_action_id = ea.id
            WHERE l.device_id = %s AND {review_link_filter}
            ORDER BY ea.recall_initiation_date DESC NULLS LAST
        """, (device_id, args.min_match_confidence))

        recalls = rows(conn, f"""
            SELECT rr.*, l.match_method, l.matched_on, l.match_confidence, l.needs_review AS link_needs_review
            FROM recall_records rr
            JOIN device_recall_links l ON l.recall_record_id = rr.id
            WHERE l.device_id = %s AND {link_filter}
            ORDER BY rr.date_posted DESC NULLS LAST
        """, (device_id, args.min_match_confidence))

        review_recalls = rows(conn, f"""
            SELECT rr.*, l.match_method, l.matched_on, l.match_confidence, l.needs_review AS link_needs_review
            FROM recall_records rr
            JOIN device_recall_links l ON l.recall_record_id = rr.id
            WHERE l.device_id = %s AND {review_link_filter}
            ORDER BY rr.date_posted DESC NULLS LAST
        """, (device_id, args.min_match_confidence))

        html_doc, json_summary = build_html(
            device, authorizations, events, review_events, enforcements, review_enforcements, recalls, review_recalls,
            min_match_confidence=args.min_match_confidence,
            include_review_links=args.include_review_links,
        )

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = "strict" if not args.include_review_links else "review-included"
        path = out_dir / f"{slugify(device['canonical_name'])}_governance_dossier_{suffix}.html"
        path.write_text(html_doc, encoding="utf-8")

        conn.execute(
            """
            INSERT INTO governance_reports (device_id, report_type, report_version, html_content, pdf_path, json_content)
            VALUES (%s, 'governance_dossier', 'v0.6_software_aware_classifier', %s, %s, %s)
            """,
            (device_id, html_doc, str(path), Jsonb(json_summary)),
        )

    print(f"Wrote dossier: {path}")


if __name__ == "__main__":
    main()
