"""Data loading helpers for RouteGuard-Med."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List

from .schemas import Action, EvidenceSnippet, PromptExample


def load_evidence_jsonl(path: str | Path) -> List[EvidenceSnippet]:
    path = Path(path)
    rows: List[EvidenceSnippet] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(EvidenceSnippet.model_validate(json.loads(line)))
    return rows


def write_evidence_jsonl(rows: Iterable[EvidenceSnippet], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def _bool(v: str | bool | None) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _float(v: str | float | None, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def load_benchmark_csv(path: str | Path) -> List[PromptExample]:
    path = Path(path)
    examples: List[PromptExample] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gold = [s.strip() for s in row.get("gold_sources", "").split(";") if s.strip()]
            examples.append(
                PromptExample(
                    prompt_id=row.get("prompt_id", ""),
                    query=row.get("query", ""),
                    expected_action=Action(row.get("expected_action", "retrieve")),
                    answerable_from_context=_bool(row.get("answerable_from_context")),
                    should_retrieve=_bool(row.get("should_retrieve")),
                    should_clarify=_bool(row.get("should_clarify")),
                    should_abstain=_bool(row.get("should_abstain")),
                    should_escalate=_bool(row.get("should_escalate")),
                    enough_source_evidence=_bool(row.get("enough_source_evidence")),
                    gold_sources=gold,
                    language=row.get("language", "en"),
                    category=row.get("category", "general"),
                    utility_answer=_float(row.get("utility_answer")),
                    utility_retrieve=_float(row.get("utility_retrieve")),
                    utility_clarify=_float(row.get("utility_clarify")),
                    utility_abstain=_float(row.get("utility_abstain")),
                    utility_escalate=_float(row.get("utility_escalate")),
                    notes=row.get("notes", ""),
                )
            )
    return examples
