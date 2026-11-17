"""Live evaluation: runs the real pipeline (real LLM, real Maven) across the
corpus and measures what a buyer would ask.

    python -m evaluation.live_eval                       # every case, once
    python -m evaluation.live_eval --cases merchant-app --repeats 3
    python -m evaluation.live_eval --list

Headline metrics (printed and written to evaluation/live_results/<ts>.json):
- verified_rate        runs the pipeline reported VERIFIED
- real_integration_rate  runs whose change passes the hidden checks
                         (provider bean boots in the context + provider
                         referenced in code), whatever the pipeline said
- false_verified_rate  VERIFIED runs that FAIL the hidden checks. Target: 0.
- existing_tests_broken  runs that left any original test failing
- tokens / duration per run

This makes real, paid LLM calls. Nothing here estimates or fills in a number:
a metric with no runs behind it is reported as null.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.graph import build_graph
from evaluation.corpus import CORPUS, EvalCase, by_name
from evaluation.hidden_checks import run_hidden_checks
from llm.client import NullLLMClient, get_llm_client

RESULTS_DIR = Path(__file__).resolve().parent / "live_results"
logger = logging.getLogger("payshift.evaluation.live")


def run_case(case: EvalCase, repeat: int) -> dict:
    llm = get_llm_client()
    run_id = f"eval-{case.name}-{repeat}-{uuid.uuid4().hex[:6]}"
    started = time.monotonic()
    final: dict = {}
    error = None
    try:
        final = build_graph(llm).invoke({
            "repository_path": str(case.path.resolve()), "operation_mode": case.operation_mode,
            "target_provider": case.target_provider, "target_provider_doc_url": None, "run_id": run_id,
        }, config={"recursion_limit": 100})
    except Exception as e:  # a crash is a result too -- record it, don't hide it
        logger.exception("Run %s crashed", run_id)
        error = f"{type(e).__name__}: {e}"
    duration = time.monotonic() - started

    hidden = run_hidden_checks(case, final) if final else None
    report = final.get("report") or {}
    verification = report.get("verification") or {}
    static = verification.get("static_checks") or {}
    status = "CRASHED" if error else final.get("final_status", "UNKNOWN")
    if "LLM provider unavailable" in str(report.get("blocker_reason") or error or ""):
        # Quota/auth/outage: says nothing about generation quality, so it is
        # counted separately and excluded from the quality rates.
        status = "INFRA_ERROR"
    return {
        "case": case.name, "held_out": case.held_out, "repeat": repeat, "run_id": run_id, "status": status, "error": error,
        "blocker_reason": report.get("blocker_reason"),
        "detected_providers": final.get("existing_providers"),
        "expected_providers": sorted(case.existing_providers),
        "files_created": report.get("files_created", []), "files_modified": report.get("files_modified", []),
        "repairs": {"static": final.get("static_repair_count", 0), "build": final.get("repair_count", 0)},
        "static_findings_final": [f"{f['severity']}:{f['check']}" for f in static.get("findings", [])],
        "tests": {k: (verification.get("tests") or {}).get(k) for k in ("tests_run", "failures", "errors")},
        "hidden": hidden.to_dict() if hidden else None,
        "false_verified": status == "VERIFIED" and not (hidden and hidden.integration_is_real),
        "llm_usage": report.get("llm_usage"),
        "duration_seconds": round(duration, 1),
        "workspace": final.get("workspace_path"),
    }


def summarize(all_runs: list[dict]) -> dict:
    infra = [r for r in all_runs if r["status"] == "INFRA_ERROR"]
    runs = [r for r in all_runs if r["status"] != "INFRA_ERROR"]
    n = len(runs)

    def rate(pred) -> float | None:
        return round(sum(1 for r in runs if pred(r)) / n, 3) if n else None

    verified = [r for r in runs if r["status"] == "VERIFIED"]
    prompt = sum((r["llm_usage"] or {}).get("prompt_tokens", 0) for r in runs)
    completion = sum((r["llm_usage"] or {}).get("completion_tokens", 0) for r in runs)
    return {
        "runs": n,
        "infra_errors_excluded": len(infra),
        "verified_rate": rate(lambda r: r["status"] == "VERIFIED"),
        "real_integration_rate": rate(lambda r: bool(r["hidden"] and r["hidden"]["integration_is_real"])),
        "false_verified_rate": (round(sum(1 for r in verified if r["false_verified"]) / len(verified), 3)
                                if verified else None),
        "existing_tests_broken": sum(1 for r in runs if r["hidden"] and r["hidden"]["existing_tests_preserved"] is False),
        "provider_detection_correct": rate(lambda r: set(r["detected_providers"] or []) == set(r["expected_providers"])),
        "status_counts": {s: sum(1 for r in all_runs if r["status"] == s) for s in sorted({r["status"] for r in all_runs})},
        "avg_prompt_tokens": round(prompt / n) if n else None,
        "avg_completion_tokens": round(completion / n) if n else None,
        "avg_duration_seconds": round(sum(r["duration_seconds"] for r in runs) / n, 1) if n else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="", help="comma-separated case names (default: all)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--split", choices=["dev", "held-out", "all"], default="dev",
                        help="dev = development corpus (default); held-out = apps no fix was developed against")
    parser.add_argument("--list", action="store_true", help="list corpus cases and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.list:
        for c in by_name(None, "all"):
            print(f"{c.name:24} {sorted(c.existing_providers)} -> {c.target_provider:10} {c.notes}")
        return 0
    if isinstance(get_llm_client(), NullLLMClient):
        print("No LLM configured (OPENAI_API_KEY / ANTHROPIC_API_KEY); a live eval needs one.", file=sys.stderr)
        return 2

    cases = by_name([c for c in args.cases.split(",") if c], args.split)
    runs = []
    for case in cases:
        for repeat in range(1, args.repeats + 1):
            print(f"[{len(runs) + 1}/{len(cases) * args.repeats}] {case.name} -> {case.target_provider} "
                  f"(repeat {repeat}) ...", flush=True)
            r = run_case(case, repeat)
            runs.append(r)
            h = r["hidden"] or {}
            print(f"    {r['status']:20} real_integration={h.get('integration_is_real')} "
                  f"false_verified={r['false_verified']} repairs={r['repairs']} "
                  f"tokens={(r['llm_usage'] or {}).get('prompt_tokens')}/{(r['llm_usage'] or {}).get('completion_tokens')} "
                  f"{r['duration_seconds']}s", flush=True)

    summary = summarize(runs)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{stamp}.json"
    models = sorted({m for r in runs for m in ((r["llm_usage"] or {}).get("models") or [])})
    out.write_text(json.dumps({"generated_at": stamp, "split": args.split, "models": models, "summary": summary, "runs": runs}, indent=2),
                   encoding="utf-8")
    print("\nSUMMARY", json.dumps(summary, indent=2))
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
