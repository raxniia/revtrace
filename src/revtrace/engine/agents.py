from __future__ import annotations

import json

from ..llm import Message, Provider, ToolSpec
from ..toolkit import Tool
from .baseline import BaselineStrategy
from .investigation import Draft, Investigation, Notes
from .recommend import LEAD_TRAITS, build_action, playbook_recommendations
from .schema import Hypothesis, Recommendation
from .scoring import evidence_grade

MAX_TOOL_OUTPUT = 6000

HOUSE_RULES = (
    "You work inside RevTrace, a system that investigates changes in sales performance.\n"
    "Every figure you state must come from a tool result or from the material you are given. "
    "Never estimate, round creatively or invent numbers.\n"
    "Be brief and concrete. Write in the language of the user's question."
)

INVESTIGATOR = (
    "You are the Investigator. You think like a detective: you form competing explanations for what "
    "happened, including the ones people in the business would blame first, so each can be tested "
    "and either supported or ruled out."
)
ANALYST = (
    "You are the Data Analyst. You test one hypothesis at a time against the numbers using your tools. "
    "Start with test_factor on the most relevant dimension, then dig one level deeper if a tool can show "
    "who or what is behind the pattern. Stop as soon as you can answer."
)
LISTENER = (
    "You are the Conversation Agent. You read what customers actually wrote. Search their messages with "
    "keywords in their own language (the customers write in Algerian Darija and French), compare lost and won "
    "customers, and bring back short verbatim quotes."
)
ADVISOR = (
    "You are the Recommendation Agent. You turn findings into a short list of actions a sales manager can "
    "approve today. Prefer actions that fix a confirmed cause. Do not recommend acting on a ruled-out hypothesis."
)


def _spec(name: str, description: str, properties: dict, required: list[str]) -> ToolSpec:
    return ToolSpec(name, description, {"type": "object", "properties": properties, "required": required})


def _tool_spec(tool: Tool) -> ToolSpec:
    return ToolSpec(tool.name, tool.description, tool.parameters)


class Agent:
    def __init__(
        self, name: str, instructions: str, provider: Provider, run: Investigation, tools: list[Tool]
    ):
        self.name = name
        self.system = f"{instructions}\n\n{HOUSE_RULES}"
        self.provider = provider
        self.run = run
        self.tools = tools

    def _complete(self, messages: list[Message], specs: list[ToolSpec], force: str | None, max_tokens: int):
        completion = self.provider.complete(self.system, messages, specs, force, max_tokens)
        self.run.usage.add(completion.input_tokens, completion.output_tokens)
        return completion

    def decide(self, task: str, submit: ToolSpec, max_tokens: int = 2500) -> dict:
        completion = self._complete([Message("user", task)], [submit], submit.name, max_tokens)
        call = next((c for c in completion.tool_calls if c.name == submit.name), None)
        return call.arguments if call else {}

    def work(self, task: str, submit: ToolSpec) -> dict:
        specs = [_tool_spec(t) for t in self.tools] + [submit]
        messages = [Message("user", task)]
        steps = self.run.ctx.settings.max_agent_steps
        for step in range(steps):
            force = submit.name if step == steps - 1 else None
            completion = self._complete(messages, specs, force, 1500)
            if not completion.tool_calls:
                messages.append(Message("assistant", completion.text))
                messages.append(Message("user", f"Call {submit.name} to hand in your findings."))
                continue
            messages.append(Message("assistant", completion.text, completion.tool_calls))
            for call in completion.tool_calls:
                if call.name == submit.name:
                    return call.arguments
                result = self.run.tool(self.name, call.name, **call.arguments)
                payload = json.dumps(result, ensure_ascii=False, default=str)[:MAX_TOOL_OUTPUT]
                messages.append(Message("tool", payload, tool_call_id=call.id))
        return {}


class AgenticStrategy:
    def __init__(self, provider: Provider):
        self.provider = provider
        self.label = f"{provider.name}:{provider.model}"
        self._fallback = BaselineStrategy()

    def _agent(self, run: Investigation, name: str, instructions: str, *groups: str) -> Agent:
        return Agent(name, instructions, self.provider, run, run.ctx.toolkit.select(*groups))

    def _brief(self, run: Investigation) -> str:
        return (
            f"Question from the sales manager: {run.question}\n"
            f"Period under investigation: {run.current}, compared with {run.baseline}.\n"
            f"Situation: {json.dumps(run.situation, ensure_ascii=False)}"
        )

    def propose(self, run: Investigation) -> list[Draft]:
        themes = {}
        if run.ds.conversations:
            themes = run.tool(
                "Conversation Agent", "conversation_themes", current=run.current, baseline=run.baseline
            )
        dimensions = run.ds.describe()["dimensions"]
        submit = _spec(
            "propose_hypotheses",
            "Submit the hypotheses to investigate.",
            {
                "hypotheses": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Three to six words"},
                            "statement": {"type": "string", "description": "One falsifiable sentence"},
                            "dimension": {
                                "type": "string",
                                "enum": [d["name"] for d in dimensions] + ["none"],
                                "description": "The dimension that would reveal it, or none",
                            },
                            "policy_query": {
                                "type": "string",
                                "description": "Search query, in the documents' language, for the company rule that applies",
                            },
                        },
                        "required": ["title", "statement", "dimension", "policy_query"],
                    },
                }
            },
            ["hypotheses"],
        )
        task = (
            f"{self._brief(run)}\n\n"
            f"Dimensions available for testing: {json.dumps(dimensions, ensure_ascii=False)}\n"
            f"Customer conversation themes: {json.dumps(themes, ensure_ascii=False)}\n"
            f"Company documents: {json.dumps(run.ctx.index.outline(), ensure_ascii=False)}\n\n"
            "Propose three to six distinct hypotheses that could explain the change. Cover operational causes "
            "(speed, follow-up, staffing), commercial causes (price, product, lead source), and include the "
            "explanation the team is most likely to assume, even if you doubt it."
        )
        answer = self._agent(run, "Investigator", INVESTIGATOR).decide(task, submit)
        drafts = []
        for item in answer.get("hypotheses", [])[:6]:
            dimension = item.get("dimension")
            drafts.append(
                Draft(
                    title=str(item.get("title", "")).strip() or "Untitled hypothesis",
                    statement=str(item.get("statement", "")).strip(),
                    dimension=dimension if dimension in run.ds.dimensions else None,
                    policy_query=str(item.get("policy_query", "")).strip(),
                )
            )
        return drafts or self._fallback.propose(run)

    def investigate(self, run: Investigation, draft: Draft) -> Notes:
        run.emit("Orchestrator", "note", f"Testing: {draft.title}")
        before = set(run.factor_tests)
        hint = f" The dimension '{draft.dimension}' is the natural starting point." if draft.dimension else ""
        findings = self._agent(run, "Data Analyst", ANALYST, "data").work(
            f"{self._brief(run)}\n\nHypothesis to test: {draft.title}. {draft.statement}{hint}",
            _spec(
                "submit_findings",
                "Hand in what the numbers say about the hypothesis.",
                {
                    "summary": {
                        "type": "string",
                        "description": "Two or three sentences with the key figures",
                    },
                    "dimension": {
                        "type": "string",
                        "description": "The tested dimension that best addresses the hypothesis, or none",
                    },
                },
                ["summary", "dimension"],
            ),
        )
        tested = [d for d in run.factor_tests if d not in before]
        dimension = findings.get("dimension")
        if dimension not in run.ds.dimensions:
            dimension = draft.dimension or (tested[0] if tested else None)
        notes = Notes(dimension=dimension, analyst=str(findings.get("summary", "")))
        if run.ds.conversations:
            heard = self._agent(run, "Conversation Agent", LISTENER, "conversations").work(
                f"{self._brief(run)}\n\nHypothesis: {draft.title}. {draft.statement}\n"
                "Find out whether customers' own words support or contradict it.",
                _spec(
                    "submit_quotes",
                    "Hand in what customers say about the hypothesis.",
                    {
                        "summary": {
                            "type": "string",
                            "description": "Two sentences with counts from your tools",
                        },
                        "quotes": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "properties": {"lead_id": {"type": "string"}, "quote": {"type": "string"}},
                                "required": ["lead_id", "quote"],
                            },
                        },
                    },
                    ["summary", "quotes"],
                ),
            )
            notes.conversations = str(heard.get("summary", ""))
            notes.quotes = [q for q in heard.get("quotes", []) if isinstance(q, dict)]
        return notes

    def explain(self, run: Investigation, hypothesis: Hypothesis, notes: Notes) -> str:
        verdict = hypothesis.verdict
        meaning = {
            "primary": "confirmed as a cause of the change",
            "chronic": "a real, standing leak that did not change between the two periods, so not a cause of the change",
            "rejected": "ruled out",
            "inconclusive": "inconclusive, because no dimension in the data could test it",
        }[verdict.label]
        task = (
            f"{self._brief(run)}\n\nHypothesis: {hypothesis.title}. {hypothesis.statement}\n"
            f"Verdict computed from the statistics (final, do not argue with it): {meaning}. "
            f"Evidence that it caused the change: {verdict.confidence}/100 ({evidence_grade(verdict.confidence)}).\n"
            f"Evidence: {json.dumps([e.model_dump() for e in hypothesis.evidence], ensure_ascii=False)}\n"
            f"Data Analyst's notes: {notes.analyst}\n"
            f"Conversation Agent's notes: {notes.conversations}\n\n"
            "Explain the verdict to the sales manager in two to four sentences. Use only figures that appear above."
        )
        answer = self._agent(run, "Investigator", INVESTIGATOR).decide(
            task,
            _spec(
                "write_reasoning", "Submit the explanation.", {"reasoning": {"type": "string"}}, ["reasoning"]
            ),
            max_tokens=700,
        )
        return str(answer.get("reasoning", "")).strip() or self._fallback.explain(run, hypothesis, notes)

    def conclude(self, run: Investigation, hypotheses: list[Hypothesis]) -> tuple[str, list[Recommendation]]:
        findings = [
            {
                "id": h.id,
                "title": h.title,
                "verdict": h.verdict.label,
                "evidence_score": h.verdict.confidence,
                "dimension": h.dimension,
                "reasoning": h.reasoning,
                "estimated_impact": h.impact.model_dump() if h.impact else None,
            }
            for h in hypotheses
        ]
        submit = _spec(
            "propose_actions",
            "Submit the executive summary and the recommended actions.",
            {
                "summary": {
                    "type": "string",
                    "description": "Three or four sentences answering the manager's question",
                },
                "recommendations": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Imperative, under twelve words"},
                            "rationale": {"type": "string", "description": "One or two sentences"},
                            "hypothesis_id": {"type": "string"},
                            "effort": {"type": "string", "enum": ["low", "medium", "high"]},
                            "action": {
                                "type": "string",
                                "enum": ["alert_rule", "followup_tasks", "manager_note", "none"],
                                "description": (
                                    "alert_rule: alert when a lead waits past the response target. "
                                    "followup_tasks: create follow-up tasks for qualified leads touched once. "
                                    "manager_note: send a written brief to the sales lead. none: guidance only."
                                ),
                            },
                            "message": {
                                "type": "string",
                                "description": "For followup_tasks: the message to send, in the customers' language",
                            },
                        },
                        "required": ["title", "rationale", "hypothesis_id", "effort", "action"],
                    },
                },
            },
            ["summary", "recommendations"],
        )
        task = (
            f"{self._brief(run)}\n\nFindings: {json.dumps(findings, ensure_ascii=False)}\n"
            f"Response-time target: {run.ctx.settings.sla_response_minutes} minutes. "
            f"Follow-ups expected per qualified lead: {run.ctx.settings.min_followups}.\n\n"
            "Write the summary, then at most five recommendations ordered by expected impact."
        )
        answer = self._agent(run, "Recommendation Agent", ADVISOR).decide(task, submit)
        by_id = {h.id: h for h in hypotheses}
        recs: list[Recommendation] = []
        for item in answer.get("recommendations", [])[:5]:
            hypothesis = by_id.get(item.get("hypothesis_id"))
            title = str(item.get("title", "")).strip()
            if not title or (hypothesis and hypothesis.dimension in LEAD_TRAITS):
                continue
            effort = item.get("effort") if item.get("effort") in {"low", "medium", "high"} else "medium"
            recs.append(
                Recommendation(
                    id=f"R{len(recs) + 1}",
                    title=title,
                    rationale=str(item.get("rationale", "")).strip(),
                    hypothesis_id=hypothesis.id if hypothesis else None,
                    effort=effort,
                    impact=hypothesis.impact
                    if hypothesis and hypothesis.verdict.label != "rejected"
                    else None,
                    action=build_action(
                        run, item.get("action", "none"), hypothesis, title, item.get("message")
                    ),
                )
            )
        summary = str(answer.get("summary", "")).strip() or self._fallback.summary(run, hypotheses)
        return summary, recs or playbook_recommendations(run, hypotheses)
