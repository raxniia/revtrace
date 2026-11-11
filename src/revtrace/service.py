from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import analytics
from .config import Settings, get_settings
from .dataset import Dataset, DatasetError, DatasetRegistry, slugify
from .engine import evidence as ev
from .engine.baseline import TEMPLATES, BaselineStrategy
from .engine.investigation import Context, Investigation, Strategy
from .engine.recommend import LEAD_TRAITS
from .engine.schema import Event, Report
from .engine.scoring import judge
from .llm import LLMError, get_provider
from .store import Store

DATA_FILES = {"leads.csv", "orders.csv", "customers.csv", "conversations.json"}


class ServiceError(ValueError):
    pass


@dataclass
class LiveRun:
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    condition: threading.Condition = field(default_factory=threading.Condition)

    def push(self, event: Event) -> None:
        with self.condition:
            self.events.append(event.model_dump())
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.finished = True
            self.condition.notify_all()


class Service:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.uploads = self.settings.var_dir / "datasets"
        self.registry = DatasetRegistry(self.settings.datasets_dir, self.uploads)
        self.store = Store(self.settings.var_dir / "revtrace.db")
        self._contexts: dict[str, Context] = {}
        self._live: dict[str, LiveRun] = {}
        self._lock = threading.Lock()

    def context(self, dataset: str | None = None) -> Context:
        name = dataset or self.settings.default_dataset
        with self._lock:
            if name not in self._contexts:
                try:
                    self._contexts[name] = Context.build(self.registry.get(name), self.settings)
                except DatasetError as exc:
                    raise ServiceError(str(exc)) from exc
            return self._contexts[name]

    def config(self) -> dict:
        return {
            "engine": self.settings.engine_label,
            "agentic": self.settings.agentic,
            "provider": self.settings.provider,
            "model": self.settings.model,
            "default_dataset": self.settings.default_dataset,
            "datasets": self.registry.names(),
            "sla_response_minutes": self.settings.sla_response_minutes,
            "min_followups": self.settings.min_followups,
        }

    def strategy(self, mode: str = "auto") -> Strategy:
        if mode == "baseline" or (mode == "auto" and not self.settings.agentic):
            return BaselineStrategy()
        if not self.settings.agentic:
            raise ServiceError("No LLM provider is configured. Set REVTRACE_PROVIDER and an API key in .env.")
        from .engine.agents import AgenticStrategy

        try:
            return AgenticStrategy(get_provider(self.settings))
        except LLMError as exc:
            raise ServiceError(str(exc)) from exc

    def _periods(self, ctx: Context, current: str | None, baseline: str | None) -> tuple[str, str]:
        try:
            default_current, default_baseline = ctx.ds.default_periods()
            current, baseline = current or default_current, baseline or default_baseline
            ctx.ds.leads_in(current), ctx.ds.leads_in(baseline)
        except DatasetError as exc:
            raise ServiceError(str(exc)) from exc
        return current, baseline

    def overview(
        self, dataset: str | None = None, current: str | None = None, baseline: str | None = None
    ) -> dict:
        ctx = self.context(dataset)
        ds = ctx.ds
        current, baseline = self._periods(ctx, current, baseline)
        return {
            "dataset": ds.describe(),
            "current": current,
            "baseline": baseline,
            "current_label": ev.month_name(current),
            "baseline_label": ev.month_name(baseline),
            "comparison": analytics.compare_periods(ds, current, baseline),
            "health": analytics.health(
                ds, current, baseline, self.settings.sla_response_minutes, self.settings.min_followups
            ),
            "series": analytics.daily_series(ds),
            "changepoint": analytics.detect_changepoint(ds),
            "signals": self._signals(ctx, current, baseline),
            "model": ctx.model.card,
            "documents": ctx.index.outline(),
        }

    def _signals(self, ctx: Context, current: str, baseline: str, limit: int = 4) -> list[dict]:
        signals = []
        for name in ctx.ds.dimensions:
            if name in LEAD_TRAITS:
                continue
            test = analytics.factor_test(ctx.ds, name, current, baseline)
            verdict = judge(test)
            if verdict.label not in {"primary", "chronic"}:
                continue
            gap, shift = test["gap"], test["shift"]
            if verdict.label == "primary":
                headline = (
                    f"“{shift['culprit']}” grew from {ev.pct(shift['culprit_baseline_share'], 0)} to "
                    f"{ev.pct(shift['culprit_current_share'], 0)} of leads, and “{gap['worst']}” converts at "
                    f"{ev.pct(gap['worst_rate'])} against {ev.pct(gap['best_rate'])} for “{gap['best']}”."
                )
            else:
                headline = (
                    f"“{gap['worst']}” converts at {ev.pct(gap['worst_rate'])} against "
                    f"{ev.pct(gap['best_rate'])} for “{gap['best']}”, in both periods."
                )
            signals.append(
                {
                    "dimension": name,
                    "title": TEMPLATES.get(name, (f"Shift in {test['label']}",))[0],
                    "label": verdict.label,
                    "confidence": verdict.confidence,
                    "headline": headline,
                }
            )
        signals.sort(key=lambda s: (s["label"] != "primary", -s["confidence"]))
        return signals[:limit]

    def investigate(
        self,
        question: str,
        dataset: str | None = None,
        mode: str = "auto",
        current: str | None = None,
        baseline: str | None = None,
        wait: bool = False,
    ) -> str:
        question = question.strip()
        if not question:
            raise ServiceError("Ask a question to investigate.")
        ctx = self.context(dataset)
        current, baseline = self._periods(ctx, current, baseline)
        strategy = self.strategy(mode)
        investigation_id = uuid.uuid4().hex[:12]
        live = LiveRun()
        self._live[investigation_id] = live
        self.store.create_investigation(investigation_id, ctx.ds.name, question, strategy.label)
        run = Investigation(
            ctx, question, strategy, current, baseline, emit=live.push, report_id=investigation_id
        )

        def work():
            try:
                report = run.run()
                self._save(report, live.events)
            except Exception as exc:
                run.emit("Orchestrator", "error", str(exc))
                self.store.finish_investigation(investigation_id, None, live.events, error=str(exc))
            finally:
                live.close()

        if wait:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return investigation_id

    def _save(self, report: Report, events: list[dict]) -> None:
        self.store.finish_investigation(report.id, report.model_dump(), events)
        for rec in report.recommendations:
            if rec.action:
                self.store.add_action(report.id, rec.id, rec.title, rec.action.model_dump())

    def investigation(self, investigation_id: str) -> dict:
        record = self.store.investigation(investigation_id)
        if record is None:
            raise ServiceError("Investigation not found.")
        record["actions"] = self.store.actions(investigation_id)
        return record

    def stream(self, investigation_id: str, timeout: float = 20.0):
        live = self._live.get(investigation_id)
        if live is None:
            record = self.store.investigation(investigation_id)
            if record is None:
                raise ServiceError("Investigation not found.")
            yield from record["events"]
            return
        sent = 0
        while True:
            with live.condition:
                if sent >= len(live.events) and not live.finished:
                    live.condition.wait(timeout)
                batch, finished = live.events[sent:], live.finished
            yield from batch
            sent += len(batch)
            if finished and sent >= len(live.events):
                return
            if not batch:
                yield None

    def decide(self, action_id: str, approve: bool) -> dict:
        action = self.store.action(action_id)
        if action is None:
            raise ServiceError("Action not found.")
        if action["status"] != "pending":
            raise ServiceError(f"This action was already {action['status']}.")
        if not approve:
            self.store.decide_action(action_id, "rejected")
            return self.store.action(action_id)
        payload = action["payload"]
        if action["type"] == "followup_tasks":
            due = (datetime.now(UTC) + timedelta(hours=payload.get("due_in_hours", 24))).isoformat(
                timespec="minutes"
            )
            for lead_id in payload["lead_ids"]:
                self.store.add_outbox(
                    action_id, "task", f"Follow up with lead {lead_id}", payload["message"], lead_id, due
                )
            result = {"summary": f"{len(payload['lead_ids'])} follow-up tasks created"}
        elif action["type"] == "alert_rule":
            title = f"Alert {payload['notify']} when a lead waits more than {payload['threshold_minutes']} minutes"
            self.store.add_outbox(action_id, "alert_rule", title)
            result = {"summary": "Alert rule is on"}
        else:
            self.store.add_outbox(
                action_id, "note", payload.get("subject", action["title"]), payload.get("note", "")
            )
            result = {"summary": "Brief sent to the sales lead"}
        self.store.decide_action(action_id, "executed", result)
        return self.store.action(action_id)

    def add_dataset(self, name: str, files: dict[str, bytes]) -> dict:
        slug = slugify(name)
        if slug in self.registry.names():
            raise ServiceError(f"A dataset named '{slug}' already exists.")
        if "leads.csv" not in files:
            raise ServiceError("leads.csv is required.")
        folder = self.uploads / slug
        (folder / "docs").mkdir(parents=True, exist_ok=True)
        try:
            for filename, content in files.items():
                clean = Path(filename).name
                if clean in DATA_FILES:
                    (folder / clean).write_bytes(content)
                elif Path(clean).suffix.lower() in {".md", ".txt"}:
                    (folder / "docs" / clean).write_bytes(content)
                else:
                    raise ServiceError(f"Unsupported file: {clean}")
            dataset = Dataset(folder)
            dataset.default_periods()
        except (DatasetError, ServiceError, ValueError) as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise ServiceError(str(exc)) from exc
        return dataset.describe()
