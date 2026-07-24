"""AI processing boundary (interface only, disableable, no AI calls here).

Stage 1-2 design (PROJECT_RULES section ten / v2 section 2.4):

    AI is an OPTIONAL, DISABLEABLE processing stage that runs AFTER the
    Top-20 cap. It may:
        - rewrite a summary        (from real source text)
        - generate tags            (from title/summary)
        - optimize a title        (cosmetic, source-faithful)
    It must NOT:
        - generate facts / fabricate news
        - generate or rewrite URLs
        - add non-existent sources
        - modify published_at or heat_raw
        - raise HotScore
        - create non-existent Trends
    On ANY failure it must FALL BACK to the original text, never to a
    replacement fact. ``ai_enabled=false`` selects ``NullAIProcessor``.

Nothing in this file calls a network, an API, or an LLM. ``NullAIProcessor``
is a pure passthrough used for the disabled path and for tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import Trend


@runtime_checkable
class AIProcessor(Protocol):
    """Contract for the optional AI enrichment stage."""

    def enrich(self, trend: Trend) -> Trend:
        """Return an enriched Trend (summary/tags/title) or the original.

        On failure it MUST return the input ``trend`` unchanged (fallback
        to source text), never a fabricated one.
        """
        ...

    def fact_check(self, trend: Trend, original: Trend) -> bool:
        """True if ``trend``'s AI output is traceable to ``original``.

        If it cannot be traced (hallucination), the caller MUST discard the
        AI result and fall back to ``original``.
        """
        ...


class NullAIProcessor:
    """AI disabled. Pure passthrough -- never touches content.

    Used when ``config ai.enabled=false`` (v2 section 2.4). ``enrich``
    returns the input unchanged; ``fact_check`` returns True (nothing to
    check, and the no-AI path is always acceptable).
    """

    def enrich(self, trend: Trend) -> Trend:
        return trend

    def fact_check(self, trend: Trend, original: Trend) -> bool:
        return True
