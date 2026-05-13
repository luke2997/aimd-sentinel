"""Core schemas for RouteGuard-Med.

RouteGuard-Med evaluates regulated medical-AI agent behavior by routing each
query to one of five safe actions: answer, retrieve, clarify, abstain, or
escalate.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Action(str, Enum):
    ANSWER = "answer"
    RETRIEVE = "retrieve"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class EvidenceSnippet(BaseModel):
    source_id: str
    title: str
    text: str
    url: Optional[str] = None
    device_name: Optional[str] = None
    evidence_type: Optional[str] = None
    date: Optional[str] = None
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PromptExample(BaseModel):
    prompt_id: str
    query: str
    expected_action: Action
    answerable_from_context: bool = False
    should_retrieve: bool = False
    should_clarify: bool = False
    should_abstain: bool = False
    should_escalate: bool = False
    enough_source_evidence: bool = False
    gold_sources: List[str] = Field(default_factory=list)
    language: str = "en"
    category: str = "general"
    utility_answer: float = 0.0
    utility_retrieve: float = 0.0
    utility_clarify: float = 0.0
    utility_abstain: float = 0.0
    utility_escalate: float = 0.0
    notes: str = ""


class RouterDecision(BaseModel):
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    expected_utility: Optional[float] = None
    requires_evidence: bool = False
    needs_human_review: bool = False
    citations: List[str] = Field(default_factory=list)
    debug: Dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    query: str
    router_name: str
    decision: RouterDecision
    answer: Optional[str] = None
    retrieved: List[EvidenceSnippet] = Field(default_factory=list)
    latency_ms: float = 0.0
    estimated_token_cost: float = 0.0
    warnings: List[str] = Field(default_factory=list)


class EvalRow(BaseModel):
    prompt_id: str
    router: str
    query: str
    expected_action: Action
    predicted_action: Action
    action_correct: bool
    answer: Optional[str] = None
    citations: List[str] = Field(default_factory=list)
    gold_sources: List[str] = Field(default_factory=list)
    citation_precision: Optional[float] = None
    unsupported_claim: bool = False
    retrieval_useful: Optional[bool] = None
    latency_ms: float = 0.0
    estimated_token_cost: float = 0.0
    net_utility: float = 0.0
    category: str = ""
    language: str = "en"
    failure_mode: str = ""
