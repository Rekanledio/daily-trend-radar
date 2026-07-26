"""Rule-based Trend Scoring System (Stage 4-3).

Computes a composite ``trend_score`` (0-100), an ``impact_level`` (critical /
high / medium / low) and a list of ``score_reasons`` for each Trend.

Design principles:
  - Pure rule-based: no ML, no LLM calls.
  - Every Trend gets scored regardless of source.
  - Scores are computed AFTER AI enrichment so AI keywords can be used.
  - Never blocks the pipeline on scoring failure.
  - Old data without scoring fields remains valid (Optional).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional

from .models import Trend

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Source authority weights (max 30)
_SOURCE_WEIGHTS = {
    "github": 28.0,
    "arxiv": 26.0,
    # future sources will get lower weights here
}

_DEFAULT_SOURCE_WEIGHT = 20.0

# Days after which freshness score drops to half
_FRESHNESS_HALF_LIFE_DAYS = 2.0
_FRESHNESS_LAMBDA = 0.693 / _FRESHNESS_HALF_LIFE_DAYS  # ln(2) / half-life

# AI relevance keywords (case-insensitive, combined across title+keywords)
_AI_KEYWORDS = [
    "ai", "llm", "agent", "transformer", "deep learning",
    "machine learning", "gpt", "language model", "neural",
    "diffusion", "reinforcement learning", "rag", "retrieval augmented",
    "multimodal", "foundation model", "open source llm",
    "fine tuning", "sft", "rlhf", "chain of thought",
]

# Impact level thresholds
_IMPACT_LEVELS = [
    (80.0, "critical"),
    (60.0, "high"),
    (40.0, "medium"),
    (0.0, "low"),
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _source_score(trend: Trend) -> tuple[float, str]:
    """Score based on source authority (0-30)."""
    weight = _SOURCE_WEIGHTS.get(trend.source_id, _DEFAULT_SOURCE_WEIGHT)
    reason = f"Source ({trend.source_name}): {weight:.0f}/30"
    return weight, reason


def _hot_score_component(trend: Trend) -> tuple[float, str]:
    """Map existing hot_score (0-100) into the 0-30 range."""
    score = round(trend.hot_score * 0.3, 1)
    reason = f"Hot score ({trend.hot_score:.0f}): {score:.1f}/30"
    return score, reason


def _freshness_score(trend: Trend, now: datetime) -> tuple[float, str]:
    """Exponential-decay freshness in the 0-20 range.

    Uses the same decay model as pipeline.py but with a 2-day half-life
    and capped at 20.
    """
    ref = trend.published_at or trend.collected_at
    if ref is None:
        return 0.0, "Freshness: no timestamp → 0/20"
    age_days = max(0.0, (now - ref).total_seconds() / 86400.0)
    score = round(20.0 * (2.0 ** (-age_days / _FRESHNESS_HALF_LIFE_DAYS)), 1)
    days_str = f"{age_days:.1f}d" if age_days < 100 else f"{age_days:.0f}d"
    reason = f"Freshness ({days_str} ago): {score:.1f}/20"
    return score, reason


def _ai_relevance_score(trend: Trend) -> tuple[float, str]:
    """Score based on AI-relevant keywords in title, summary, and AI summary (0-20).

    Checks title, summary, keywords, and ai_summary fields for AI-related terms.
    """
    # Collect text to search
    texts: list[str] = [trend.title or ""]
    if trend.summary:
        texts.append(trend.summary)
    if trend.ai_summary:
        texts.append(trend.ai_summary.summary)
        texts.append(trend.ai_summary.why_it_matters)
        texts.extend(trend.ai_summary.keywords)

    combined = " ".join(texts).lower()

    matched = 0
    for kw in _AI_KEYWORDS:
        if re.search(re.escape(kw), combined):
            matched += 1

    # Score: each matched keyword adds up to 20/max_keywords_score
    max_keywords = min(len(_AI_KEYWORDS), 10)  # cap at 10 for scoring
    score = round(min(20.0, (matched / max_keywords) * 20.0), 1)
    reason = f"AI relevance ({matched} keywords): {score:.1f}/20"
    return score, reason


# ---------------------------------------------------------------------------
# Impact level
# ---------------------------------------------------------------------------


def _determine_impact_level(total_score: float) -> str:
    """Map total score (0-100) to an impact level string."""
    for threshold, level in _IMPACT_LEVELS:
        if total_score >= threshold:
            return level
    return "low"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_trend(trend: Trend, now: Optional[datetime] = None) -> Trend:
    """Apply scoring to a single Trend in-place and return it.

    Sets ``trend_score``, ``impact_level``, and ``score_reason`` on the Trend.
    Safe for old data -- if fields already exist they are overwritten.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        s_src, r_src = _source_score(trend)
        s_hot, r_hot = _hot_score_component(trend)
        s_fresh, r_fresh = _freshness_score(trend, now)
        s_ai, r_ai = _ai_relevance_score(trend)

        total = round(s_src + s_hot + s_fresh + s_ai, 1)
        total = max(0.0, min(100.0, total))  # clamp to 0-100

        impact = _determine_impact_level(total)
        reasons = [r_src, r_hot, r_fresh, r_ai]

        trend.trend_score = total
        trend.impact_level = impact
        trend.score_reason = reasons
    except Exception:
        # Never let scoring crash the pipeline
        trend.trend_score = 0.0
        trend.impact_level = "low"
        trend.score_reason = ["Scoring error: fallback to default"]

    return trend


def score_trends(trends: list[Trend], now: Optional[datetime] = None) -> list[Trend]:
    """Score a list of Trends, returning them in the same order."""
    return [score_trend(t, now=now) for t in trends]
