from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

VerdictLabel = Literal["primary", "chronic", "rejected", "inconclusive"]
Direction = Literal["supports", "contradicts", "context"]
EvidenceKind = Literal["metric", "conversation", "policy", "model"]
ActionType = Literal["alert_rule", "followup_tasks", "manager_note"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Evidence(BaseModel):
    kind: EvidenceKind
    direction: Direction
    text: str
    source: str = ""


class Verdict(BaseModel):
    label: VerdictLabel
    confidence: int = Field(ge=0, le=100)
    components: dict[str, float] = {}


class Impact(BaseModel):
    points: float | None = None
    orders: float | None = None
    revenue: float | None = None
    basis: str = ""


class Hypothesis(BaseModel):
    id: str
    title: str
    statement: str
    dimension: str | None = None
    verdict: Verdict
    reasoning: str = ""
    evidence: list[Evidence] = []
    impact: Impact | None = None
    factor: dict[str, Any] | None = None


class Action(BaseModel):
    type: ActionType
    label: str
    payload: dict[str, Any] = {}


class Recommendation(BaseModel):
    id: str
    title: str
    rationale: str
    hypothesis_id: str | None = None
    effort: Literal["low", "medium", "high"] = "medium"
    impact: Impact | None = None
    action: Action | None = None


class Event(BaseModel):
    seq: int
    at: str = Field(default_factory=now)
    agent: str
    kind: Literal["stage", "note", "tool", "hypothesis", "verdict", "recommendation", "done", "error"]
    title: str
    detail: dict[str, Any] | None = None


class RunStats(BaseModel):
    leads_examined: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0


class Report(BaseModel):
    id: str
    dataset: str
    question: str
    engine: str
    current: str
    baseline: str
    situation: dict[str, Any]
    summary: str
    hypotheses: list[Hypothesis]
    recommendations: list[Recommendation]
    stats: RunStats
    created_at: str = Field(default_factory=now)
