"""ChromaDB-backed documentation index and the search_provider_docs retrieval API.

Embedding function is provider-configurable: if OPENAI_API_KEY is set, uses
OpenAI embeddings (matching the spec's stack); otherwise falls back to
Chroma's bundled local ONNX MiniLM model so indexing/retrieval is fully
testable without any paid API key.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from rag.ingestion import DocumentChunk

logger = logging.getLogger("payshift.rag.retrieval")

_OPERATION_KEYWORDS: dict[str, list[str]] = {
    "CREATE_PAYMENT": ["create a payment", "payment intent", "create an order", "charge", "collect payment"],
    "GET_PAYMENT_STATUS": ["retrieve", "status", "get a payment", "fetch payment"],
    "CREATE_REFUND": ["refund"],
    "HANDLE_WEBHOOK": ["webhook", "event"],
    "VERIFY_WEBHOOK_SIGNATURE": ["signature", "webhook secret", "verify"],
    "FULFILL_ORDER": ["fulfill", "order"],
}


@dataclass
class SearchResult:
    text: str
    source_url: str
    title: str
    provider_id: str
    trust_level: str
    code_block: bool
    distance: float


def _embedding_function_and_collection_name() -> tuple:
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        logger.info("Using OpenAI embeddings for the documentation index")
        model_name = "text-embedding-3-small"
        return embedding_functions.OpenAIEmbeddingFunction(api_key=api_key, model_name=model_name), \
            f"payshift_provider_docs__openai_{model_name}"
    logger.info("No OPENAI_API_KEY set; using Chroma's bundled local embedding model")
    return embedding_functions.DefaultEmbeddingFunction(), "payshift_provider_docs__local_minilm"


class DocumentIndex:
    """Collections are namespaced by which embedding function produced their
    vectors (see _embedding_function_and_collection_name). Chroma stores each
    collection's vector dimension and raises if you add a mismatched one, so
    switching from the local embedding model to OpenAI's (384 vs 1536 dims)
    on a persistent store would otherwise crash every write -- namespacing
    means switching providers just starts a fresh, correctly-dimensioned
    collection instead of corrupting or crashing against the old one.
    """

    def __init__(self, persist_directory: Path | str):
        self._client = chromadb.PersistentClient(path=str(persist_directory))
        embedding_fn, collection_name = _embedding_function_and_collection_name()
        self._collection = self._client.get_or_create_collection(
            name=collection_name, embedding_function=embedding_fn,
        )

    def index_chunks(self, chunks: list[DocumentChunk]) -> int:
        if not chunks:
            return 0
        ids, documents, metadatas = [], [], []
        for chunk in chunks:
            chunk_id = hashlib.sha256(f"{chunk.source_url}#{chunk.chunk_index}".encode()).hexdigest()
            ids.append(chunk_id)
            documents.append(chunk.text)
            metadatas.append({
                "source_url": chunk.source_url,
                "title": chunk.title,
                "provider_id": chunk.provider_id,
                "trust_level": chunk.trust_level,
                "fetched_at": chunk.fetched_at,
                "code_block": chunk.code_block,
            })
        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def search(self, query: str, provider_id: str | None = None, operation: str | None = None,
               top_k: int = 5) -> list[SearchResult]:
        where = {"provider_id": provider_id} if provider_id else None
        fetch_n = max(top_k * 3, top_k)
        raw = self._collection.query(query_texts=[query], n_results=fetch_n, where=where)

        documents = raw["documents"][0] if raw["documents"] else []
        metadatas = raw["metadatas"][0] if raw["metadatas"] else []
        distances = raw["distances"][0] if raw["distances"] else [0.0] * len(documents)

        results = [
            SearchResult(
                text=doc, source_url=meta["source_url"], title=meta["title"],
                provider_id=meta["provider_id"], trust_level=meta["trust_level"],
                code_block=meta["code_block"], distance=dist,
            )
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]

        if operation and operation in _OPERATION_KEYWORDS:
            keywords = _OPERATION_KEYWORDS[operation]
            boosted = [r for r in results if any(kw.lower() in r.text.lower() for kw in keywords)]
            rest = [r for r in results if r not in boosted]
            results = boosted + rest

        return results[:top_k]

    def document_count(self) -> int:
        return self._collection.count()
