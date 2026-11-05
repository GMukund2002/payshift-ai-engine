"""Integration test for Phase 4 (RAG). Makes REAL network calls to official
provider documentation and indexes into a REAL (temp) Chroma store using the
local embedding fallback -- no mocking, so a pass here means retrieval
genuinely works, not just that the plumbing compiles.

Skipped automatically if there is no network access.
"""
import socket

import pytest

from rag.discovery import resolve_documentation_sources
from rag.pipeline import ensure_provider_documentation_indexed
from rag.retrieval import DocumentIndex


def _has_network() -> bool:
    try:
        socket.create_connection(("docs.stripe.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


requires_network = pytest.mark.skipif(not _has_network(), reason="no network access in this environment")


def test_discovery_blocks_unknown_provider_without_url():
    result = resolve_documentation_sources("totally_unknown_psp")
    assert result.blocked is True
    assert "totally_unknown_psp" in result.blocker_reason


def test_discovery_resolves_known_provider_to_official_domain():
    result = resolve_documentation_sources("stripe")
    assert result.blocked is False
    assert all(s.trust_level == "OFFICIAL_VERIFIED" for s in result.sources)
    assert all(s.url.startswith("https://docs.stripe.com") for s in result.sources)


def test_discovery_rejects_non_https_user_url():
    result = resolve_documentation_sources("stripe", user_supplied_url="http://docs.stripe.com/api")
    assert result.blocked is True


@requires_network
def test_end_to_end_index_and_retrieve_stripe_docs(tmp_path):
    index = DocumentIndex(persist_directory=tmp_path / "chroma")
    summary = ensure_provider_documentation_indexed("stripe", index)

    assert summary.blocked is False
    assert summary.chunks_indexed > 0, f"warnings: {summary.warnings}"

    results = index.search("how do I create a refund", provider_id="stripe", operation="CREATE_REFUND", top_k=3)
    assert len(results) > 0
    assert all(r.provider_id == "stripe" for r in results)
    assert all(r.trust_level == "OFFICIAL_VERIFIED" for r in results)
    # At least one of the top results should actually be about refunds, not
    # just "some stripe text" -- this is the real signal that retrieval works.
    assert any("refund" in r.text.lower() for r in results)


@requires_network
def test_end_to_end_index_and_retrieve_razorpay_docs(tmp_path):
    index = DocumentIndex(persist_directory=tmp_path / "chroma")
    summary = ensure_provider_documentation_indexed("razorpay", index)

    assert summary.blocked is False
    assert summary.chunks_indexed > 0, f"warnings: {summary.warnings}"

    results = index.search("webhook signature verification", provider_id="razorpay",
                            operation="VERIFY_WEBHOOK_SIGNATURE", top_k=3)
    assert len(results) > 0
    assert all(r.provider_id == "razorpay" for r in results)


@requires_network
def test_user_supplied_url_for_unregistered_provider_is_marked_user_approved(tmp_path):
    index = DocumentIndex(persist_directory=tmp_path / "chroma")
    summary = ensure_provider_documentation_indexed(
        "some_new_psp", index, user_supplied_url="https://docs.stripe.com/api/payment_intents/create",
    )
    assert summary.blocked is False
    assert summary.chunks_indexed > 0

    results = index.search("create a payment", provider_id="some_new_psp", top_k=3)
    assert all(r.trust_level == "USER_APPROVED" for r in results)
