"""Thin, stable entry points over the RAG pipeline (rag/*) for use by agent
nodes and the MCP server -- a single shared DocumentIndex instance backed by
a persistent Chroma store on disk so documentation fetched once is reused
across runs instead of being re-downloaded every time.
"""
from __future__ import annotations

from pathlib import Path

from rag.pipeline import IndexingSummary, ensure_provider_documentation_indexed
from rag.retrieval import DocumentIndex, SearchResult

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHROMA_DIR = AI_ENGINE_ROOT / "chroma_db"

_index: DocumentIndex | None = None


def get_index(persist_directory: Path | str = DEFAULT_CHROMA_DIR) -> DocumentIndex:
    global _index
    if _index is None:
        _index = DocumentIndex(persist_directory=persist_directory)
    return _index


def ensure_docs_indexed(provider_id: str, user_supplied_url: str | None = None,
                         force_refresh: bool = False) -> IndexingSummary:
    return ensure_provider_documentation_indexed(provider_id, get_index(), user_supplied_url, force_refresh)


def search_provider_docs(query: str, provider_id: str | None = None, operation: str | None = None,
                          top_k: int = 5) -> list[SearchResult]:
    return get_index().search(query=query, provider_id=provider_id, operation=operation, top_k=top_k)
