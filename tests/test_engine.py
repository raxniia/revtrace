from __future__ import annotations

import json
import re

from revtrace.engine.agents import AgenticStrategy
from revtrace.engine.baseline import BaselineStrategy
from revtrace.engine.investigation import Investigation
from revtrace.llm import Completion, ToolCall

QUESTION = "Why did sales drop in October?"


def by_dimension(report):
    return {h.dimension: h for h in report.hypotheses if h.dimension}


def test_baseline_finds_causes_and_rejects_price(ctx):
    report = Investigation(ctx, QUESTION, BaselineStrategy()).run()
    found = by_dimension(report)
    assert found["response_time"].verdict.label == "primary"
    assert found["followups"].verdict.label == "primary"
    assert found["product"].verdict.label == "chronic"
    assert found["price_band"].verdict.label == "rejected"
    assert found["qualified"].verdict.label == "rejected"
    assert report.hypotheses[0].verdict.confidence >= report.hypotheses[1].verdict.confidence
    assert report.stats.llm_calls == 0 and report.stats.tool_calls > 10


def test_baseline_evidence_cites_policy_and_customers(ctx):
    report = Investigation(ctx, QUESTION, BaselineStrategy()).run()
    slow = by_dimension(report)["response_time"]
    kinds = {e.kind for e in slow.evidence}
    assert {"metric", "conversation", "policy", "model"} <= kinds
    assert any("30 minutes" in e.text for e in slow.evidence if e.kind == "policy")
    assert slow.impact and slow.impact.revenue > 0


def test_recommendations_carry_actions_awaiting_approval(ctx):
    report = Investigation(ctx, QUESTION, BaselineStrategy()).run()
    actions = {r.action.type for r in report.recommendations if r.action}
    assert {"alert_rule", "followup_tasks"} <= actions
    tasks = next(r.action for r in report.recommendations if r.action and r.action.type == "followup_tasks")
    assert 0 < len(tasks.payload["lead_ids"]) <= 25
    assert any(r.title.startswith("Hold prices") and r.action is None for r in report.recommendations)


class ScriptedProvider:
    name = "scripted"
    model = "test"

    def __init__(self):
        self.forced: list[str] = []

    def complete(self, system, messages, tools=None, force_tool=None, max_tokens=2000):
        names = [t.name for t in tools or []]
        task = messages[0].content
        used_tool = any(m.role == "tool" for m in messages)
        if force_tool:
            self.forced.append(force_tool)

        def call(name, **arguments):
            return Completion("", [ToolCall(f"call-{len(messages)}", name, arguments)], 10, 5)

        if force_tool == "propose_hypotheses":
            return call(
                "propose_hypotheses",
                hypotheses=[
                    {
                        "title": "Slow replies",
                        "statement": "Replies got slower.",
                        "dimension": "response_time",
                        "policy_query": "délai de première réponse",
                    },
                    {
                        "title": "Too expensive",
                        "statement": "Prices scare buyers.",
                        "dimension": "price_band",
                        "policy_query": "politique de prix",
                    },
                    {
                        "title": "Seasonality",
                        "statement": "October is always slow.",
                        "dimension": "none",
                        "policy_query": "",
                    },
                ],
            )
        if "submit_findings" in names:
            hinted = re.search(r"dimension '(\w+)'", task)
            if not used_tool and hinted:
                return call("test_factor", dimension=hinted.group(1), current="2026-10", baseline="2026-09")
            return call(
                "submit_findings", summary="Numbers checked.", dimension=hinted.group(1) if hinted else "none"
            )
        if "submit_quotes" in names:
            if not used_tool:
                return call("search_conversations", query="ghali, cher", status="lost", limit=2)
            found = json.loads(messages[-1].content)
            return call("submit_quotes", summary="Customers were heard.", quotes=found["examples"][:1])
        if force_tool == "write_reasoning":
            return call("write_reasoning", reasoning="Explained from the evidence.")
        if force_tool == "propose_actions":
            return call(
                "propose_actions",
                summary="Slow replies caused the drop.",
                recommendations=[
                    {
                        "title": "Alert on slow replies",
                        "rationale": "It is the main cause.",
                        "hypothesis_id": "H1",
                        "effort": "low",
                        "action": "alert_rule",
                    },
                    {
                        "title": "Chase stale leads",
                        "rationale": "They were touched once.",
                        "hypothesis_id": "H1",
                        "effort": "low",
                        "action": "followup_tasks",
                        "message": "Salam, mazal intéressé ?",
                    },
                ],
            )
        raise AssertionError(f"Unexpected request: tools={names} force={force_tool}")


def test_agents_plan_use_tools_and_respect_computed_verdicts(ctx):
    provider = ScriptedProvider()
    events = []
    report = Investigation(ctx, QUESTION, AgenticStrategy(provider), emit=events.append).run()

    assert report.engine == "scripted:test"
    assert [h.title for h in report.hypotheses] == ["Slow replies", "Seasonality", "Too expensive"]
    slow, seasonal, price = report.hypotheses
    assert slow.verdict.label == "primary" and slow.reasoning == "Explained from the evidence."
    assert seasonal.verdict.label == "inconclusive" and seasonal.dimension is None
    assert price.verdict.label == "rejected"
    assert any(e.kind == "conversation" and e.source.startswith("lead ") for e in price.evidence)

    assert report.summary == "Slow replies caused the drop."
    assert [r.action.type for r in report.recommendations] == ["alert_rule", "followup_tasks"]
    assert report.recommendations[1].action.payload["message"] == "Salam, mazal intéressé ?"

    assert provider.forced.count("write_reasoning") == 3
    assert report.stats.llm_calls == 16
    agents = {e.agent for e in events}
    assert {
        "Orchestrator",
        "Investigator",
        "Data Analyst",
        "Conversation Agent",
        "Recommendation Agent",
    } <= agents
    assert events[-1].kind == "done"


def test_agents_fall_back_when_the_model_returns_nothing(ctx):
    class Silent:
        name, model = "silent", "test"

        def complete(self, *args, **kwargs):
            return Completion("", [])

    report = Investigation(ctx, QUESTION, AgenticStrategy(Silent())).run()
    assert by_dimension(report)["response_time"].verdict.label == "primary"
    assert report.recommendations and report.summary.startswith("Conversion fell")
