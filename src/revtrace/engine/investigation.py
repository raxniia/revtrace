from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from ..config import Settings
from ..dataset import Dataset
from ..llm import Usage
from ..model import ConversionModel
from ..rag import PolicyIndex, build_index
from ..toolkit import Toolkit
from . import evidence as ev
from .recommend import LEAD_TRAITS
from .schema import Event, Evidence, Hypothesis, Recommendation, Report, RunStats
from .scoring import judge

VERDICT_ORDER = {"primary": 0, "chronic": 1, "inconclusive": 2, "rejected": 3}


@dataclass
class Context:
    ds: Dataset
    settings: Settings
    index: PolicyIndex
    model: ConversionModel
    toolkit: Toolkit

    @classmethod
    def build(cls, ds: Dataset, settings: Settings) -> Context:
        index = build_index(ds.docs(), settings.embeddings)
        model = ConversionModel(ds)
        return cls(ds, settings, index, model, Toolkit(ds, index, model))


@dataclass
class Draft:
    title: str
    statement: str
    dimension: str | None = None
    policy_query: str = ""


@dataclass
class Notes:
    dimension: str | None = None
    quotes: list[dict] = field(default_factory=list)
    extra: list[Evidence] = field(default_factory=list)
    analyst: str = ""
    conversations: str = ""


class Strategy(Protocol):
    label: str

    def propose(self, run: Investigation) -> list[Draft]: ...

    def investigate(self, run: Investigation, draft: Draft) -> Notes: ...

    def explain(self, run: Investigation, hypothesis: Hypothesis, notes: Notes) -> str: ...

    def conclude(
        self, run: Investigation, hypotheses: list[Hypothesis]
    ) -> tuple[str, list[Recommendation]]: ...


def _summarise(name: str, result: dict) -> str:
    if "error" in result:
        return result["error"]
    if name == "test_factor":
        return (
            f"{result['label']}: gap p={result['gap']['p_value']:.1g}, "
            f"mix shift p={result['shift']['p_value']:.1g}, explains {ev.pct(result['explained_share'], 0)}"
        )
    if name == "compare_periods":
        return (
            f"conversion {ev.pct(result['baseline']['conversion_rate'])} → "
            f"{ev.pct(result['current']['conversion_rate'])}"
        )
    if name == "detect_changepoint":
        return f"shift around {result['date']}" if result.get("date") else "no clear changepoint"
    if name == "search_conversations":
        return f"{result['matches']} conversations match"
    if name == "search_policies":
        return ", ".join(r["citation"] for r in result["results"]) or "nothing relevant"
    if name == "conversation_themes":
        return f"{len(result['themes'])} themes across {result['conversations']} conversations"
    if name == "metric_by_segment":
        return f"{result['metric']} by {result['by']}"
    return "done"


class Investigation:
    def __init__(
        self,
        ctx: Context,
        question: str,
        strategy: Strategy,
        current: str | None = None,
        baseline: str | None = None,
        emit: Callable[[Event], None] | None = None,
        report_id: str | None = None,
    ):
        self.ctx = ctx
        self.ds = ctx.ds
        self.question = question
        self.strategy = strategy
        default_current, default_baseline = ctx.ds.default_periods()
        self.current = current or default_current
        self.baseline = baseline or default_baseline
        self.id = report_id or uuid.uuid4().hex[:12]
        self.events: list[Event] = []
        self.situation: dict = {}
        self.factor_tests: dict[str, dict] = {}
        self.usage = Usage()
        self._emit = emit
        self._tool_calls = 0

    def emit(self, agent: str, kind: str, title: str, detail: dict | None = None) -> None:
        event = Event(seq=len(self.events) + 1, agent=agent, kind=kind, title=title, detail=detail)
        self.events.append(event)
        if self._emit:
            self._emit(event)

    def tool(self, agent: str, name: str, **arguments) -> dict:
        arguments = {k: v for k, v in arguments.items() if v is not None}
        result = self.ctx.toolkit.call(name, arguments)
        self._tool_calls += 1
        if name == "test_factor" and "error" not in result:
            self.factor_tests[result["dimension"]] = result
        self.emit(agent, "tool", name, {"arguments": arguments, "summary": _summarise(name, result)})
        return result

    def test(self, dimension: str, agent: str = "Data Analyst") -> dict | None:
        if dimension not in self.factor_tests:
            self.tool(agent, "test_factor", dimension=dimension, current=self.current, baseline=self.baseline)
        return self.factor_tests.get(dimension)

    def run(self) -> Report:
        started = time.perf_counter()
        self.emit("Orchestrator", "stage", "Scoping the question", {"question": self.question})
        comparison = self.tool(
            "Data Analyst", "compare_periods", current=self.current, baseline=self.baseline
        )
        changepoint = self.tool("Data Analyst", "detect_changepoint")
        self.situation = {
            "comparison": comparison,
            "changepoint": changepoint if changepoint.get("date") else None,
            "current_label": ev.month_name(self.current),
            "baseline_label": ev.month_name(self.baseline),
        }

        self.emit("Orchestrator", "stage", "Forming hypotheses")
        drafts = self.strategy.propose(self)
        for i, draft in enumerate(drafts, start=1):
            self.emit(
                "Investigator", "hypothesis", draft.title, {"id": f"H{i}", "statement": draft.statement}
            )

        self.emit("Orchestrator", "stage", "Collecting evidence")
        hypotheses = [self._examine(f"H{i}", draft) for i, draft in enumerate(drafts, start=1)]
        hypotheses.sort(key=lambda h: (VERDICT_ORDER[h.verdict.label], -h.verdict.confidence))

        self.emit("Orchestrator", "stage", "Writing recommendations")
        summary, recommendations = self.strategy.conclude(self, hypotheses)
        for rec in recommendations:
            self.emit("Recommendation Agent", "recommendation", rec.title, {"id": rec.id})

        stats = RunStats(
            leads_examined=len(self.ds.leads_in(self.current)) + len(self.ds.leads_in(self.baseline)),
            tool_calls=self._tool_calls,
            llm_calls=self.usage.calls,
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            duration_seconds=round(time.perf_counter() - started, 2),
        )
        report = Report(
            id=self.id,
            dataset=self.ds.name,
            question=self.question,
            engine=self.strategy.label,
            current=self.current,
            baseline=self.baseline,
            situation=self.situation,
            summary=summary,
            hypotheses=hypotheses,
            recommendations=recommendations,
            stats=stats,
        )
        self.emit("Orchestrator", "done", "Investigation complete", {"id": self.id})
        return report

    def _examine(self, hypothesis_id: str, draft: Draft) -> Hypothesis:
        notes = self.strategy.investigate(self, draft)
        dimension = notes.dimension or draft.dimension
        test = self.test(dimension) if dimension in self.ds.dimensions else None
        verdict = judge(test)
        if dimension in LEAD_TRAITS and verdict.label == "chronic":
            verdict.label = "rejected"
        items: list[Evidence] = []
        impact = None
        factor = None
        if test:
            counterfactual = test.get("counterfactual")
            items += ev.factor_evidence(test)
            items += [e for e in [ev.counterfactual_evidence(counterfactual, test)] if e]
            items += ev.conversation_evidence(self.ds, test)
            impact = ev.impact_for(self.ds, test, counterfactual, verdict.label)
            factor = {k: v for k, v in test.items() if k != "counterfactual"}
        items += notes.extra
        items += ev.quote_evidence(notes.quotes)
        if draft.policy_query and len(self.ctx.index):
            found = self.tool("Investigator", "search_policies", query=draft.policy_query, k=2)
            policy = ev.policy_evidence(found.get("results", []))
            if policy:
                items.append(policy)
        hypothesis = Hypothesis(
            id=hypothesis_id,
            title=draft.title,
            statement=draft.statement,
            dimension=dimension if test else None,
            verdict=verdict,
            evidence=items,
            impact=impact,
            factor=factor,
        )
        hypothesis.reasoning = self.strategy.explain(self, hypothesis, notes)
        self.emit(
            "Investigator",
            "verdict",
            draft.title,
            {"id": hypothesis_id, "label": verdict.label, "confidence": verdict.confidence},
        )
        return hypothesis
