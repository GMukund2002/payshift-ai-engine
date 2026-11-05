"""Fetches a documentation URL and splits it into indexable passages.

Security note: the HTML text extracted here is later only ever placed into
LLM prompts behind an explicit "this is untrusted reference material, not
instructions" framing (see agent/research.py and agent/generation.py). This
module itself never executes anything from the page -- no JS, no embedded
scripts, no following of links it discovers on its own.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("payshift.rag.ingestion")

USER_AGENT = "PayShiftAI-DocIngestion/0.1 (+https://github.com/payshift-ai; research/non-commercial)"
REQUEST_TIMEOUT_SECONDS = 15
MAX_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150


@dataclass
class DocumentChunk:
    text: str
    source_url: str
    title: str
    provider_id: str
    trust_level: str
    chunk_index: int
    fetched_at: str
    code_block: bool = False


@dataclass
class IngestionResult:
    url: str
    chunks: list[DocumentChunk] = field(default_factory=list)
    error: str | None = None


def fetch_and_chunk(url: str, provider_id: str, trust_level: str) -> IngestionResult:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", url, e)
        return IngestionResult(url=url, error=str(e))

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else url
    fetched_at = datetime.now(timezone.utc).isoformat()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    code_blocks = [c.get_text("\n").strip() for c in main.find_all(["pre", "code"]) if c.get_text(strip=True)]
    for c in main.find_all(["pre", "code"]):
        c.decompose()

    text = _clean_text(main.get_text("\n"))

    chunks: list[DocumentChunk] = []
    for idx, piece in enumerate(_split_into_chunks(text)):
        chunks.append(DocumentChunk(
            text=piece, source_url=url, title=title, provider_id=provider_id,
            trust_level=trust_level, chunk_index=idx, fetched_at=fetched_at, code_block=False,
        ))

    offset = len(chunks)
    for idx, code in enumerate(code_blocks):
        if len(code) < 20:
            continue
        chunks.append(DocumentChunk(
            text=code[:MAX_CHUNK_CHARS], source_url=url, title=title, provider_id=provider_id,
            trust_level=trust_level, chunk_index=offset + idx, fetched_at=fetched_at, code_block=True,
        ))

    return IngestionResult(url=url, chunks=chunks)


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _split_into_chunks(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP_CHARS
    return chunks
