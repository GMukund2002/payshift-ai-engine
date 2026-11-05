"""CLI entry point for the PayShift AI pipeline (complements frontend/app.py).

Example:
    python main.py --repository ../sample-apps/merchant-app \\
        --mode ADD_PSP --target-provider razorpay
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

from agent.graph import build_graph
from llm.client import NullLLMClient, get_llm_client
from storage.db import backend_label, save_run_report


def main():
    parser = argparse.ArgumentParser(description="Run the PayShift AI agent pipeline")
    parser.add_argument("--repository", required=True, help="Path to the Java Spring Boot repository to analyze")
    parser.add_argument("--mode", choices=["ADD_PSP", "MIGRATE_PSP"], required=True)
    parser.add_argument("--target-provider", required=True, help="Target PSP id, e.g. razorpay, adyen, paypal")
    parser.add_argument("--doc-url", default=None, help="Official documentation URL, if the provider isn't pre-registered")
    args = parser.parse_args()

    llm = get_llm_client()
    if isinstance(llm, NullLLMClient):
        print("WARNING: no LLM provider configured (OPENAI_API_KEY / ANTHROPIC_API_KEY). "
              "The pipeline will run and report itself as blocked at the first reasoning step.", file=sys.stderr)

    graph = build_graph(llm)
    run_id = uuid.uuid4().hex[:12]
    initial_state = {
        "repository_path": str(Path(args.repository).resolve()),
        "operation_mode": args.mode,
        "target_provider": args.target_provider,
        "target_provider_doc_url": args.doc_url,
        "run_id": run_id,
    }

    print(f"Starting run {run_id}: {args.mode} -> {args.target_provider}")
    final_state = {}
    for event in graph.stream(initial_state, config={"recursion_limit": 50}):
        for node_name, update in event.items():
            final_state.update(update)
            print(f"  [{node_name}] done" + (f" -- BLOCKED: {update['blocker_reason']}" if update.get("blocked") else ""))

    report = final_state.get("report")
    if report:
        print("\n" + json.dumps(report, indent=2))
    else:
        print(f"\nRun blocked before a report could be produced: {final_state.get('blocker_reason')}")

    save_run_report(
        run_id=run_id,
        operation_mode=args.mode,
        target_provider=args.target_provider,
        existing_providers=final_state.get("existing_providers", []),
        final_status=final_state.get("final_status") or final_state.get("blocker_reason"),
        report=report,
    )
    print(f"\n(run history persisted to {backend_label()})")

    sys.exit(0 if not final_state.get("blocked") else 1)


if __name__ == "__main__":
    main()
