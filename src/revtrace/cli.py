from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ROOT, get_settings


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("revtrace.api:app", host=args.host, port=args.port, reload=args.reload)


def _investigate(args: argparse.Namespace) -> None:
    from .service import Service, ServiceError

    service = Service()
    try:
        investigation_id = service.investigate(
            args.question, args.dataset, args.mode, args.current, args.baseline, wait=True
        )
    except ServiceError as exc:
        sys.exit(str(exc))
    record = service.investigation(investigation_id)
    if record["status"] != "complete":
        sys.exit(f"Investigation failed: {record['error']}")
    report = record["report"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    marks = {"primary": "CAUSE", "chronic": "LEAK ", "rejected": "OUT  ", "inconclusive": "?    "}
    print(f"\n{report['question']}  [{report['engine']}]\n")
    print(report["summary"], "\n")
    for h in report["hypotheses"]:
        print(f"  {marks[h['verdict']['label']]} {h['verdict']['confidence']:>3}/100  {h['title']}")
        print(f"        {h['reasoning']}")
    print("\nRecommended actions")
    for r in report["recommendations"]:
        suffix = f"  [{r['action']['label']}, awaiting approval]" if r["action"] else ""
        print(f"  {r['id']}  {r['title']}{suffix}")
    stats = report["stats"]
    print(
        f"\n{stats['tool_calls']} tool calls, {stats['llm_calls']} model calls, {stats['duration_seconds']}s"
    )


def _evaluate(args: argparse.Namespace) -> None:
    from .evaluation import evaluate
    from .service import Service, ServiceError

    try:
        strategy = Service().strategy(args.mode)
    except ServiceError as exc:
        sys.exit(str(exc))

    def progress(row: dict) -> None:
        mark = "ok  " if row["exact"] else "MISS"
        print(f"  {mark} {row['scenario']}  expected={row['expected']}  found={row['found']}")

    result = evaluate(args.scenarios, strategy, get_settings(), progress)
    out = ROOT / "eval" / f"results-{result['engine'].split(':')[0]}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"\n{result['engine']} on {result['scenarios']} scenarios\n"
        f"  precision {result['precision']:.0%}   recall {result['recall']:.0%}   F1 {result['f1']:.2f}\n"
        f"  every cause found, nothing extra: {result['exact_match']:.0%}\n"
        f"  decoys rejected: {result['decoy_rejection']:.0%}   chronic leak found: {result['chronic_leak_found']:.0%}\n"
        f"  saved to {out.relative_to(ROOT)}"
    )


def _generate(args: argparse.Namespace) -> None:
    from .synth import Scenario, generate

    scenario = Scenario(
        name=args.name,
        seed=args.seed,
        slow_response=not args.no_slow_response,
        missing_followups=not args.no_missing_followups,
        bad_source=args.bad_source,
        price_hike=args.price_hike,
    )
    truth = generate(scenario, Path(args.out) / args.name)
    truth_file = ROOT / "eval" / f"{args.name}-truth.json"
    truth_file.parent.mkdir(exist_ok=True)
    truth_file.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"Dataset written to {Path(args.out) / args.name}; answer key in {truth_file.relative_to(ROOT)}")


def _model(args: argparse.Namespace) -> None:
    from .service import Service

    print(json.dumps(Service().context(args.dataset).model.card, indent=2))


def _mcp(_: argparse.Namespace) -> None:
    from .mcp_server import main as run

    run()


def main() -> None:
    parser = argparse.ArgumentParser(prog="revtrace", description="Agentic sales investigation.")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the API and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(run=_serve)

    investigate = commands.add_parser("investigate", help="Run one investigation in the terminal")
    investigate.add_argument("question")
    investigate.add_argument("--dataset")
    investigate.add_argument("--mode", choices=["auto", "baseline", "agentic"], default="auto")
    investigate.add_argument("--current")
    investigate.add_argument("--baseline")
    investigate.add_argument("--json", action="store_true")
    investigate.set_defaults(run=_investigate)

    evaluate = commands.add_parser("eval", help="Score the engine on generated scenarios with known causes")
    evaluate.add_argument("--scenarios", type=int, default=16)
    evaluate.add_argument("--mode", choices=["auto", "baseline", "agentic"], default="baseline")
    evaluate.set_defaults(run=_evaluate)

    generate = commands.add_parser("generate", help="Generate a synthetic dataset")
    generate.add_argument("--name", default="dar-confort")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--out", default=str(ROOT / "datasets"))
    generate.add_argument("--no-slow-response", action="store_true")
    generate.add_argument("--no-missing-followups", action="store_true")
    generate.add_argument("--bad-source", action="store_true")
    generate.add_argument("--price-hike", action="store_true")
    generate.set_defaults(run=_generate)

    model = commands.add_parser("model", help="Train the conversion model and print its card")
    model.add_argument("--dataset")
    model.set_defaults(run=_model)

    mcp = commands.add_parser("mcp", help="Run the MCP server over stdio")
    mcp.set_defaults(run=_mcp)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
