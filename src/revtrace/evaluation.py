from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .dataset import Dataset
from .engine.investigation import Context, Investigation, Strategy
from .synth import Scenario, generate, scenario_suite

FAMILIES = {
    "response_time": "response",
    "sales_rep": "response",
    "followups": "followups",
    "source": "source",
    "price_band": "price",
    "product": "product",
}
QUESTION = "Why did our conversion rate drop last month?"


def evaluate_scenario(scenario: Scenario, strategy: Strategy, settings: Settings, workdir: Path) -> dict:
    truth = generate(scenario, workdir / scenario.name)
    ctx = Context.build(Dataset(workdir / scenario.name), settings)
    report = Investigation(ctx, QUESTION, strategy).run()
    found = {v: set() for v in ("primary", "chronic", "rejected")}
    for hypothesis in report.hypotheses:
        if hypothesis.dimension and hypothesis.verdict.label in found:
            found[hypothesis.verdict.label].add(FAMILIES.get(hypothesis.dimension, hypothesis.dimension))
    expected = set(truth["primary"])
    hits = found["primary"] & expected
    return {
        "scenario": scenario.name,
        "expected": sorted(expected),
        "found": sorted(found["primary"]),
        "true_positives": len(hits),
        "false_positives": len(found["primary"] - expected),
        "false_negatives": len(expected - found["primary"]),
        "exact": found["primary"] == expected,
        "chronic_found": set(truth["chronic"]) <= found["chronic"] | found["primary"],
        "decoys": len(truth["decoys"]),
        "decoys_rejected": sum(1 for d in truth["decoys"] if d not in found["primary"]),
        "llm_calls": report.stats.llm_calls,
        "seconds": report.stats.duration_seconds,
    }


def evaluate(
    count: int,
    strategy: Strategy,
    settings: Settings,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for scenario in scenario_suite(count):
            row = evaluate_scenario(scenario, strategy, settings, Path(tmp))
            rows.append(row)
            if progress:
                progress(row)
    tp = sum(r["true_positives"] for r in rows)
    fp = sum(r["false_positives"] for r in rows)
    fn = sum(r["false_negatives"] for r in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    decoys = sum(r["decoys"] for r in rows)
    return {
        "engine": strategy.label,
        "scenarios": len(rows),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "exact_match": round(sum(r["exact"] for r in rows) / len(rows), 3),
        "decoy_rejection": round(sum(r["decoys_rejected"] for r in rows) / decoys, 3) if decoys else None,
        "chronic_leak_found": round(sum(r["chronic_found"] for r in rows) / len(rows), 3),
        "rows": rows,
    }
