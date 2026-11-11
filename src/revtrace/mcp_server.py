from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .dataset import DatasetError
from .service import Service

INSTRUCTIONS = (
    "Sales data for one company: leads, orders, customer conversations and internal policies. "
    "Use compare_periods to see what changed, test_factor to check whether a dimension explains it, "
    "the conversation tools to hear customers, and search_policies for the company's own rules. "
    "run_investigation performs a full hypothesis-by-hypothesis investigation. "
    "Actions proposed by an investigation can be listed here but are approved by a person in the RevTrace dashboard."
)


def _readable_errors(fn: Callable[..., dict]) -> Callable[..., dict]:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatasetError as exc:
            return {"error": str(exc)}

    return wrapper


def build_server(service: Service | None = None, dataset: str | None = None) -> MCPServer:
    service = service or Service()
    ctx = service.context(dataset)
    server = MCPServer("revtrace-sales", instructions=INSTRUCTIONS)
    for tool in ctx.toolkit.tools.values():
        server.add_tool(_readable_errors(tool.fn), name=tool.name, description=tool.description)

    def run_investigation(
        question: Annotated[str, Field(description="What the sales manager wants explained")],
        current: Annotated[str | None, Field(description="Month under investigation, YYYY-MM")] = None,
        baseline: Annotated[str | None, Field(description="Month to compare against, YYYY-MM")] = None,
    ) -> dict:
        investigation_id = service.investigate(question, ctx.ds.name, "auto", current, baseline, wait=True)
        record = service.investigation(investigation_id)
        if record["status"] != "complete":
            return {"id": investigation_id, "status": record["status"], "error": record["error"]}
        report = record["report"]
        return {
            "id": investigation_id,
            "summary": report["summary"],
            "hypotheses": [
                {
                    "title": h["title"],
                    "verdict": h["verdict"]["label"],
                    "evidence_score": h["verdict"]["confidence"],
                    "reasoning": h["reasoning"],
                }
                for h in report["hypotheses"]
            ],
            "recommendations": [r["title"] for r in report["recommendations"]],
            "pending_actions": len(record["actions"]),
        }

    def list_pending_actions() -> dict:
        pending = [a for a in service.store.actions() if a["status"] == "pending"]
        return {"pending": [{"id": a["id"], "title": a["title"], "action": a["label"]} for a in pending]}

    server.add_tool(
        run_investigation,
        description="Investigate why sales changed between two months: hypotheses, evidence, verdicts, recommended actions.",
    )
    server.add_tool(
        list_pending_actions,
        description="Actions waiting for human approval in the RevTrace dashboard. Read-only.",
    )
    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
