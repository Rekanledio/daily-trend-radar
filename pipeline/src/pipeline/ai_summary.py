"""AI Summary enrichment for Daily Trend Radar.

Stage 4-1: generates ``ai_summary`` on the top-N hottest trends.

Environment variables (both optional):
    AI_PROVIDER   — "openai" (default) or "none" (forces fallback)
    OPENAI_API_KEY — API key for the selected provider

No Key / fallback mode:
    Produces a simple template summary and extracts basic keywords
    from the title.  Never blocks the Pipeline.

Design:
    - Only enriches trends with ``ai_summary = None``.
    - Only processes the top-N hottest trends (default 10).
    - LLM calls have a 10-second timeout.
    - Any exception falls back to the template summary.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from .models import AISummary, Trend

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_TRENDS = 10  # only the hottest N trends get AI enrichment
_REQUEST_TIMEOUT = 10  # seconds

# ---------------------------------------------------------------------------
# Fallback generator (no LLM or on failure)
# ---------------------------------------------------------------------------


def _fallback_summary(trend: Trend) -> AISummary:
    """Produce a simple template-based summary when no LLM is available."""
    words = re.findall(r"[A-Za-z]\w+", trend.title or "")
    keywords = sorted(
        {w.lower() for w in words if len(w) > 3 and w.lower() not in _STOP_WORDS}
    )[:5]
    if not keywords:
        keywords = [trend.source_id]

    return AISummary(
        summary=f"AI trend from {trend.source_name}: {trend.title}",
        why_it_matters=(
            f"This {trend.source_name} trend covers {trend.category.replace('_', ' ')} "
            f"topics with a hot score of {trend.hot_score:.1f}."
        ),
        keywords=keywords,
    )


_STOP_WORDS = frozenset(
    {
        "this", "that", "with", "from", "they", "them",
        "have", "been", "will", "would", "could", "should",
        "their", "there", "which", "about", "into", "what",
        "when", "then", "than", "more", "also", "just",
        "very", "your", "some", "such", "only", "than",
    }
)

# ---------------------------------------------------------------------------
# LLM integration
# ---------------------------------------------------------------------------


def _llm_summary(trend: Trend) -> Optional[AISummary]:
    """Call the configured LLM provider for an enriched summary.

    Returns ``None`` on any failure (timeout, network, parse error),
    so the caller can fall back to ``_fallback_summary``.
    """
    provider = (os.environ.get("AI_PROVIDER") or "openai").lower().strip()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not api_key or provider == "none":
        return None

    if provider == "openai":
        return _openai_summary(trend, api_key)

    # Unknown provider — fall back
    return None


def _openai_summary(trend: Trend, api_key: str) -> Optional[AISummary]:
    """Call the OpenAI Chat Completions API for a single trend."""
    import urllib.request
    import urllib.error

    title = (trend.title or "")[:200]
    source = trend.source_name
    summary = (trend.summary or "")[:300]

    prompt = (
        f"You are a tech trend analyst. Given the following item from {source}, "
        f"generate a JSON response with exactly these fields: "
        f'summary (1-2 sentence), why_it_matters (1 sentence), '
        f'keywords (array of 3-5 short keywords).\n\n'
        f"Title: {title}\n"
        f"Summary: {summary}\n"
        f"Source: {source}\n"
    )

    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful tech trend analyst. Respond with valid JSON only, no markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 300,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT)
        data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return AISummary(
            summary=str(parsed.get("summary", "")),
            why_it_matters=str(parsed.get("why_it_matters", "")),
            keywords=[str(k) for k in parsed.get("keywords", [])],
        )
    except Exception:  # noqa: BLE001 — LLM errors never break the pipeline
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_trends(trends: list[Trend]) -> list[Trend]:
    """Add ``ai_summary`` to the hottest trends.

    Only the top ``_MAX_TRENDS`` (sorted by ``hot_score`` desc) get LLM
    enrichment; all others receive a fallback summary.  The pipeline
    never fails — any exception is caught and falls back.
    """
    if not trends:
        return trends

    # Sort by hot_score descending, take top N
    sorted_trends = sorted(
        trends, key=lambda t: (t.hot_score if t.hot_score else 0), reverse=True
    )

    for i, trend in enumerate(sorted_trends):
        if trend.ai_summary is not None:
            continue  # already enriched

        try:
            llm_result = _llm_summary(trend)
            if llm_result is not None:
                trend.ai_summary = llm_result
                continue
        except Exception:  # noqa: BLE001
            pass

        # Fallback
        if i < _MAX_TRENDS:
            trend.ai_summary = _fallback_summary(trend)

    return trends
