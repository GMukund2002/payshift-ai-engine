"""Ties discovery -> ingestion -> indexing together into the one call the
LangGraph research node (Phase 5 agent) actually uses."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rag.discovery import resolve_documentation_sources
from rag.ingestion import fetch_and_chunk
from rag.retrieval import DocumentIndex

logger = logging.getLogger("payshift.rag.pipeline")


@dataclass
class IndexingSummary:
    provider_id: str
    urls_attempted: list[str] = field(default_factory=list)
    urls_failed: list[str] = field(default_factory=list)
    chunks_indexed: int = 0
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    blocker_reason: str | None = None


def ensure_provider_documentation_indexed(
    provider_id: str,
    index: DocumentIndex,
    user_supplied_url: str | None = None,
    force_refresh: bool = False,
) -> IndexingSummary:
    existing = index.search(query=provider_id, provider_id=provider_id, top_k=1)
    if existing and not force_refresh and not user_supplied_url:
        logger.info("Provider '%s' already has indexed documentation; skipping re-fetch", provider_id)
        return IndexingSummary(provider_id=provider_id, chunks_indexed=0, warnings=["already indexed; skipped re-fetch"])

    discovery = resolve_documentation_sources(provider_id, user_supplied_url)
    summary = IndexingSummary(provider_id=provider_id, warnings=list(discovery.warnings))
    if discovery.blocked:
        summary.blocked = True
        summary.blocker_reason = discovery.blocker_reason
        return summary

    for source in discovery.sources:
        summary.urls_attempted.append(source.url)
        result = fetch_and_chunk(source.url, provider_id=provider_id, trust_level=source.trust_level)
        if result.error:
            summary.urls_failed.append(source.url)
            summary.warnings.append(f"Failed to fetch {source.url}: {result.error}")
            continue
        summary.chunks_indexed += index.index_chunks(result.chunks)

    return summary
