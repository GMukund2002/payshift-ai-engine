"""Graph node: understand_architecture (Agent 1).

The LLM interprets the analyzer's structured findings into a narrative
architectural assessment. It is given ONLY the analyzer's JSON (never raw
source text) and is explicitly instructed not to reference anything outside
it; the node then defensively drops any file reference the model invents
that doesn't actually appear in the analysis, so a hallucinated citation
never reaches the plan or report.
"""
from __future__ import annotations

import json
import logging

from agent.state import AgentState
from llm.client import LLMClient, LLMNotConfiguredError

logger = logging.getLogger("payshift.agent.understanding")

SYSTEM_PROMPT = """You are a principal software architect analyzing an EXISTING Java Spring \
Boot application's payment integration, strictly from structured static-analysis data -- you \
have not read the raw source code and must not pretend otherwise.

Rules:
- Base every claim ONLY on the JSON provided in the user message. It was produced by a \
deterministic JavaParser-based analyzer, not by you.
- Never invent a class, method, file path, or behavior that is not present in that JSON.
- If the data is ambiguous or insufficient to answer something, say so explicitly rather than \
guessing.
- Respond with a single JSON object matching exactly this shape:
{
  "summary": "<2-4 sentence plain-English summary of the payment architecture>",
  "payment_creation_flow": "<how payments are created, citing real class/method names>",
  "webhook_flow": "<how webhooks are received/verified/processed, or 'none detected'>",
  "refund_flow": "<how refunds are issued, or 'none detected'>",
  "provider_abstraction_assessment": "<is there a reusable provider interface, and why>",
  "coupling_risk": "LOW" | "MEDIUM" | "HIGH",
  "refactoring_recommended": true | false,
  "file_references": ["<file paths you cited, must all appear in the input JSON>"]
}"""


def understand_architecture(state: AgentState, llm: LLMClient) -> dict:
    analysis = state["repository_analysis"]

    user_prompt = (
        "Here is the structured repository analysis (java-analyzer output). Analyze it "
        "per the rules in the system prompt:\n\n" + json.dumps(analysis, indent=2)
    )

    try:
        raw = llm.complete_json(SYSTEM_PROMPT, user_prompt)
    except LLMNotConfiguredError as e:
        return {"blocked": True, "blocker_reason": str(e)}
    except ValueError as e:
        logger.error("understand_architecture: model returned invalid JSON: %s", e)
        return {"blocked": True, "blocker_reason": f"Architecture understanding failed: {e}"}

    known_files = {pc["file"] for pc in analysis.get("paymentClasses", [])} | {
        op["sourceFile"] for op in analysis.get("paymentOperations", [])
    }
    cited = raw.get("file_references", [])
    verified = [f for f in cited if f in known_files]
    dropped = set(cited) - set(verified)
    if dropped:
        logger.warning("Dropped hallucinated file references not present in analysis: %s", dropped)
    raw["file_references"] = verified

    return {"architecture_findings": raw}


_BUSINESS_INTENT_BY_OPERATION = {
    "CREATE_PAYMENT": "collect_customer_payment",
    "GET_PAYMENT_STATUS": "report_payment_status",
    "CREATE_REFUND": "issue_refund",
    "HANDLE_WEBHOOK": "receive_async_payment_event",
    "VERIFY_WEBHOOK_SIGNATURE": "verify_event_authenticity",
    "FULFILL_ORDER": "fulfill_order_after_payment",
}


def build_payment_ir(state: AgentState) -> dict:
    """Deterministic: turns the analyzer's flat payment_operations list into one
    CapabilityEntry per distinct operation type, each defaulted to REQUIRES_RESEARCH.
    No LLM call -- this is bookkeeping, not reasoning."""
    analysis = state["repository_analysis"]
    operations = analysis.get("paymentOperations", [])

    by_type: dict[str, list[dict]] = {}
    for op in operations:
        by_type.setdefault(op["operation"], []).append(op)

    capabilities = []
    for op_type, occurrences in by_type.items():
        providers_seen = [o["provider"] for o in occurrences if o.get("provider")]
        provider = providers_seen[0] if providers_seen else None
        representative = occurrences[0]
        source_api = (
            f"{provider}:{representative['className']}.{representative['method']}"
            if provider else f"unknown:{representative['className']}.{representative['method']}"
        )
        capabilities.append({
            "operation": op_type,
            "business_intent": _BUSINESS_INTENT_BY_OPERATION.get(op_type, "collect_customer_payment"),
            "source_api": source_api,
            "target_support": "REQUIRES_RESEARCH",
            "target_api": None,
            "documentation_refs": [],
            "notes": None,
        })

    capability_model = {
        "operation_mode": state["operation_mode"],
        "existing_providers": state.get("existing_providers", []),
        "target_provider": state["target_provider"],
        "capabilities": capabilities,
        "currency_support": [],
        "idempotency_strategy": None,
        "manual_review_required": [],
        "unresolved_operations": [c["operation"] for c in capabilities],
    }
    return {"capability_model": capability_model}
