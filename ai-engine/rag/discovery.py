"""Dynamic documentation discovery (Phase 4).

Resolves which URL(s) to ingest for a given provider, honoring the security
requirement that only verified official domains or explicit user-approved
sources are trusted automatically. Never silently invents or guesses a
documentation URL for a provider it doesn't recognize.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from rag.provider_registry import KNOWN_PROVIDER_DOCS, is_official_domain, looks_like_documentation_host

TrustLevel = str  # "OFFICIAL_VERIFIED" | "USER_APPROVED" | "UNVERIFIED"


@dataclass
class DiscoveredSource:
    url: str
    trust_level: TrustLevel


@dataclass
class DiscoveryResult:
    provider_id: str
    sources: list[DiscoveredSource]
    warnings: list[str]
    blocked: bool
    blocker_reason: str | None = None


def resolve_documentation_sources(provider_id: str, user_supplied_url: str | None = None) -> DiscoveryResult:
    warnings: list[str] = []

    if user_supplied_url:
        host = urlparse(user_supplied_url).hostname or ""
        if not user_supplied_url.lower().startswith("https://"):
            return DiscoveryResult(
                provider_id=provider_id, sources=[], warnings=warnings, blocked=True,
                blocker_reason=f"Refusing non-HTTPS documentation URL: {user_supplied_url}",
            )
        trust = "OFFICIAL_VERIFIED" if is_official_domain(provider_id, host) else "USER_APPROVED"
        if trust == "USER_APPROVED" and not looks_like_documentation_host(host):
            warnings.append(
                f"'{host}' is not a recognized official domain for provider '{provider_id}' and doesn't look "
                f"like a documentation host. Proceeding because the user explicitly supplied it, but treat "
                f"anything extracted from it with extra scrutiny."
            )
        return DiscoveryResult(
            provider_id=provider_id,
            sources=[DiscoveredSource(url=user_supplied_url, trust_level=trust)],
            warnings=warnings,
            blocked=False,
        )

    known = KNOWN_PROVIDER_DOCS.get(provider_id)
    if known is None:
        return DiscoveryResult(
            provider_id=provider_id,
            sources=[],
            warnings=warnings,
            blocked=True,
            blocker_reason=(
                f"No trusted documentation is registered for provider '{provider_id}' and no documentation "
                f"URL was supplied. Supply an official documentation URL for this provider to proceed."
            ),
        )
    return DiscoveryResult(
        provider_id=provider_id,
        sources=[DiscoveredSource(url=u, trust_level="OFFICIAL_VERIFIED") for u in known.seed_urls],
        warnings=warnings,
        blocked=False,
    )
