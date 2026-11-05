"""Graph nodes: research_provider, retrieve_documentation (Agent 2).

Both are deterministic -- the actual LLM reasoning over what the retrieved
passages mean for capability support happens in planning.py (Agent 3), which
is the node that can see both the capability model and the retrieved text at
once and judge comparability. Here we only decide *what* to fetch and *what*
to retrieve, grounded in the capability model built in build_payment_ir.
"""
from __future__ import annotations

import logging

from agent.state import AgentState
from tools.documentation_tools import ensure_docs_indexed, search_provider_docs

logger = logging.getLogger("payshift.agent.research")


def research_provider(state: AgentState) -> dict:
    target = state["target_provider"]
    doc_url = state.get("target_provider_doc_url")

    summary = ensure_docs_indexed(target, user_supplied_url=doc_url)

    errors = list(state.get("errors", []))
    for w in summary.warnings:
        errors.append(f"[documentation] {w}")

    result = {
        "documentation_indexed": {
            "provider_id": summary.provider_id,
            "urls_attempted": summary.urls_attempted,
            "urls_failed": summary.urls_failed,
            "chunks_indexed": summary.chunks_indexed,
            "warnings": summary.warnings,
            "blocked": summary.blocked,
            "blocker_reason": summary.blocker_reason,
        },
        "errors": errors,
    }
    return result


_QUERY_TEMPLATES = {
    "CREATE_PAYMENT": "how to create / initiate a payment via the API",
    "GET_PAYMENT_STATUS": "how to retrieve or fetch the status of a payment",
    "CREATE_REFUND": "how to issue a full or partial refund via the API",
    "HANDLE_WEBHOOK": "webhook events for payment status changes",
    "VERIFY_WEBHOOK_SIGNATURE": "verifying webhook signatures / authenticity",
    "FULFILL_ORDER": "order fulfillment after payment confirmation",
}


def retrieve_documentation(state: AgentState) -> dict:
    target = state["target_provider"]
    capability_model = state["capability_model"]
    doc_index_info = state.get("documentation_indexed", {})

    retrieved: dict[str, list[dict]] = {}
    if doc_index_info.get("blocked"):
        logger.warning("Documentation indexing was blocked (%s); skipping retrieval", doc_index_info.get("blocker_reason"))
        return {"retrieved_passages": retrieved}

    for capability in capability_model["capabilities"]:
        op = capability["operation"]
        query = _QUERY_TEMPLATES.get(op, op.replace("_", " ").lower())
        results = search_provider_docs(query=query, provider_id=target, operation=op, top_k=3)
        retrieved[op] = [
            {
                "text": r.text, "source_url": r.source_url, "title": r.title,
                "trust_level": r.trust_level, "code_block": r.code_block, "distance": r.distance,
            }
            for r in results
        ]

    return {"retrieved_passages": retrieved}
