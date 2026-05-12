# AIMD Sentinel

**Grounded LLM-style evidence extraction and governance dossiers for AI-enabled medical devices.**

AIMD Sentinel is a deployed prototype for **AI medical-device governance, procurement review, and post-market evidence triage**. It ingests public FDA/openFDA-style medical-device records, links them to AI-enabled devices, separates high-confidence device-specific evidence from broad public-data noise, classifies adverse-event narratives into software/workflow/hardware themes, and generates source-cited governance dossiers.

> This is not a chatbot and not a clinical decision-support tool. It is a grounded extraction and report-generation system designed for high-stakes evidence review.

---

## Live demo

**GitHub Pages demo:**  
`https://luke2997.github.io/aimd-sentinel/`

Sample dossiers:

| Demo | Purpose | Why it matters |
|---|---|---|
| **UNiD Spine Analyzer** | Positive software-governance example | Shows high-confidence device-specific adverse-event links and repeated software anomaly / calculation / classification themes. |
| **Lung Vision System** | Workflow/software example | Shows a smaller evidence base with synchronization, registration, workflow, and one hardware-style issue. |
| **Red Dot** | Evidence-gap / no-overclaiming example | Shows how generic-name enforcement leads are demoted to review-only rather than treated as device-specific evidence. |

---

## Why I built this

Hospitals and clinical AI governance teams increasingly need to evaluate AI-enabled medical devices before procurement, renewal, or deployment. Public regulatory and safety information exists, but it is scattered across sources such as:

- FDA AI-enabled medical-device listings,
- 510(k) authorization records,
- MAUDE/openFDA adverse-event reports,
- enforcement actions,
- recall records,
- vendor or public documentation.

The difficult part is not just retrieving these records. The difficult part is deciding:

- which records are actually about the target device,
- which records are broad manufacturer/product-code/generic-name matches,
- what software/workflow/hardware themes appear in the narratives,
- what evidence gaps remain,
- what questions a hospital should ask before deployment,
- how to avoid overclaiming causality or safety conclusions.

AIMD Sentinel addresses this by combining **retrieval, entity resolution, evidence gating, structured extraction, manual validation, and source-cited report generation**.

---

## What the system does

```text
FDA/openFDA-style records
        ↓
Data ingestion
        ↓
PostgreSQL provenance schema
        ↓
Device/entity matching
        ↓
Evidence-quality gating
        ↓
Failure-theme extraction
        ↓
Governance dossier generation
        ↓
Manual validation + public demo
