"""Pipeline stage boundaries (interfaces + pure boundary helpers).

This module FIXES the stage boundaries from the Stage 1-2 design without
implementing data-source or AI logic:

    Adapter  ->  RawItem
        ->  Normalize      (NormalizeStage)
        ->  Validate       (ValidationStage)        # red-line checks
        ->  SourceVerify   (SourceVerifyStage)     # original_url domain vs source
        ->  Deduplicate    (DeduplicationStage)    # same source+URL
        ->  Cluster         (EventAggregationStage)  # multi-source same event
        ->  HotScore       (HotScoreStage)          # 5-dim, no AI
        ->  Rank           (sorted by hot_score)
        ->  Cap <=20       (TopStage)                # BEFORE AI
        ->  AI Enrich      (AIProcessor)            # optional, disableable
        ->  AI FactCheck   (AIProcessor.fact_check)
        ->  Publish        (PublishStage)             # assemble PublishedData

The *_Stage classes are Protocols (interface only) describing each
transform and what it MUST NOT do. The free functions
(``canonicalize_url``, ``host_of``, ``verify_original_url``,
``validate_pipeline_item``, ``combine_hot_score``, ``canonical_id``,
``cap_items``, ``build_trend``, ``build_event``, ``finalize_event``,
``decide_event_merge``, ``MergeContext``) are PURE and network-free --
they encode exactly the boundary rules and are unit-tested. No API / RSS
/ AI / network is touched here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from .models import (
    Event,
    EventSourceRef,
    ScoreBreakdown,
    Trend,
    TrendStatus,
)
from .raw import NormalizedItem

# Tracking-param keys stripped during URL canonicalization.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "feature", "spm", "from",
}


# ---------------------------------------------------------------------------
# Pure boundary helpers
# ---------------------------------------------------------------------------


def canonicalize_url(url: str) -> str:
    """Normalize a URL for deduplication / stable id.

    - lowercases scheme + host
    - drops tracking / referral query params
    - drops the fragment
    - strips a trailing slash on an otherwise-empty path
    Deterministic and side-effect free.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query = parts.query
    if query:
        kept = []
        for pair in query.split("&"):
            key = pair.split("=", 1)[0].lower()
            if key and key not in _TRACKING_PARAMS and not key.startswith("utm"):
                kept.append(pair)
        query = "&".join(kept)
    return urlunsplit((scheme, netloc, path, query, ""))


def canonical_id(source_id: str, canonical_url: str) -> str:
    """Stable dedup id = hash(source_id + canonical_url).

    Two RawItems from the SAME source with the SAME canonical URL collide
    here (dedup). Different URLs -- even similar titles -- do NOT collide;
    they belong to Event Aggregation instead (see Cluster stage).
    """
    digest = hashlib.sha256(
        f"{source_id}|{canonical_url}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def host_of(url: str) -> Optional[str]:
    """Extract the lowercased host of a URL, or ``None`` if malformed."""
    if not url or not url.strip():
        return None
    try:
        netloc = urlsplit(url.strip()).netloc.lower()
    except Exception:  # noqa: BLE001 -- malformed input is a verification failure
        return None
    return netloc or None


def verify_original_url(
    url: str,
    allowed_domains: list[str],
    require_https: bool = True,
) -> bool:
    """Source-verification predicate for the ``original_url`` truth core (pure).

    A Trend is trustworthy only if its URL lives on a domain the source
    is *allowed* to publish on. This is deliberately a SET of official
    domains (``allowed_domains``), NOT a single ``declared_domain`` --
    a real source (e.g. GitHub) may serve from several official hosts
    (``github.com``, ``gist.github.com``, ...), so a single-domain
    check would be too strict and cause false drops (Stage 1-2.1 Q2).

    Safe match rule (resistant to suffix attacks):
        host == allowed  OR  host.endswith("." + allowed)
    e.g. allowed ``github.com`` matches ``api.github.com`` but NOT
    ``github.com.evil.net`` nor ``notgithub.com``.

    Returns ``False`` when: scheme is not https (if ``require_https``),
    the URL is malformed, or no allowed domain matches. NEVER guesses or
    invents URLs.
    """
    allowed = {d.lower().strip() for d in allowed_domains if d}
    if not allowed:
        return False
    parts = urlsplit(url.strip())
    if require_https and parts.scheme.lower() != "https":
        return False
    host = parts.netloc.lower()
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed)


def validate_pipeline_item(
    item: NormalizedItem,
    valid_categories: set[str],
    now: Optional[datetime] = None,
) -> list[str]:
    """Pipeline Validation boundary (pure red-line predicate).

    Returns a list of violation messages; ``[]`` means the item may
    continue toward SourceVerify / Dedup. Mirrors PROJECT_RULES section
    seventeen and DATA_CONTRACT section 11:
        - original_url required, non-empty, syntactically valid http(s)
        - source_id present
        - title present (non-empty after normalize)
        - category is in the configured set
        - is_mock must be False (raw data is never mock)
        - summary_origin must be original/none (never ai at this stage)
        - published_at, if present, must not be in the future
    A single-item failure here is isolated: the item is dropped, the run
    continues.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    errors: list[str] = []

    if not item.original_url or not item.original_url.strip():
        errors.append("original_url is required")
    else:
        parsed = urlsplit(item.original_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append("original_url is not a valid http(s) URL")

    if not item.source_id:
        errors.append("source_id is required")
    if not item.title or not item.title.strip():
        errors.append("title is required")
    if item.category not in valid_categories:
        errors.append(f"category '{item.category}' is not a configured category")
    if item.is_mock:
        errors.append("is_mock must be False for pipeline data")
    if item.summary_origin.value not in ("original", "none"):
        errors.append("summary_origin must be original/none at pipeline stage (no AI yet)")
    if item.published_at is not None and item.published_at > now:
        errors.append("published_at is in the future")
    return errors


@dataclass(frozen=True)
class HotScoreWeights:
    """Default HotScore weights (v2 section 10.3)."""

    authority: float = 0.25
    heat: float = 0.30
    freshness: float = 0.20
    multi_source: float = 0.15
    platform: float = 0.10


def combine_hot_score(
    breakdown: ScoreBreakdown,
    weights: HotScoreWeights | None = None,
) -> float:
    """Combine the five HotScore dimensions into a 0-100 score (pure).

    Uses the v2 section 10.1 formula:
        hot_score = 100 * clamp01(
            W_auth*Authority + W_heat*Heat + W_fresh*Freshness
            + W_multi*MultiSource + W_plat*Platform)
    where each dimension is already 0-100. Only normalizes; never
    invents heat. Missing dimensions must be pre-zeroed by the caller.
    """
    if weights is None:
        weights = HotScoreWeights()
    total = (
        weights.authority * breakdown.authority
        + weights.heat * breakdown.heat
        + weights.freshness * breakdown.freshness
        + weights.multi_source * breakdown.multi_source
        + weights.platform * breakdown.platform
    )
    clamped = max(0.0, min(1.0, total / 100.0))
    return round(100.0 * clamped, 2)


def cap_items(items: list[Trend], max_per_category: int = 20) -> list[Trend]:
    """Top-20 cap boundary (pure). Returns at most ``max_per_category``.

    Never pads: if fewer valid items exist, the shorter list is returned
    as-is (PROJECT_RULES section two: 不足不凑数).
    """
    return items[:max_per_category]


def build_trend(
    item: NormalizedItem,
    hot_score: float,
    breakdown: ScoreBreakdown,
    status: TrendStatus = TrendStatus.PUBLISHED,
) -> Trend:
    """Assemble a final ``Trend`` from a scored NormalizedItem.

    This is the PublishedData-generation boundary for a single item:
    fills the score fields the production ``Trend`` model requires,
    keeps ``event_id`` assigned by the Cluster stage, and preserves
    ``original_url`` / ``source_id`` untouched (AI never rewrites these).
    """
    return Trend(
        id=canonical_id(item.source_id, item.canonical_url or item.original_url),
        event_id=item.event_id,
        source_id=item.source_id,
        source_name=item.source_name,
        category=item.category,
        title=item.title,
        summary=item.summary,
        summary_origin=item.summary_origin,
        original_url=item.original_url,
        canonical_url=item.canonical_url,
        author=item.author,
        tags=list(item.tags),
        tags_origin=item.tags_origin,
        published_at=item.published_at,
        collected_at=item.collected_at,
        updated_at=item.updated_at,
        heat_raw=item.heat_raw,
        hot_score=hot_score,
        score_breakdown=breakdown,
        rank_in_source=item.rank_in_source,
        status=status,
        lang=item.lang,
        is_mock=False,
    )


def build_event(event_id: str, items: list[NormalizedItem]) -> Event:
    """Assemble an ``Event`` from its member items (pure).

    Event Aggregation boundary: one Event bundles several Trends about the
    SAME real event (one-to-many). Original Trends are NOT deleted --
    each member is referenced via ``EventSourceRef`` carrying its own
    ``original_url`` for traceability. ``source_count`` equals the number
    of DISTICT member ``source_id``s (NOT ``len(sources)`` -- the same
    source posting several reposts/updates keeps every ``original_url`` as
    evidence but counts once for MultiSourceScore); ``hot_score`` is the
    hottest member's score.
    """
    if not items:
        raise ValueError("cannot build an Event from zero items")
    sources: list[EventSourceRef] = []
    member_scores: list[float] = []
    earliest = None
    latest = None
    for it in items:
        score = 0.0  # placeholder until HotScore stage runs; kept 0 here
        member_scores.append(score)
        sources.append(
            EventSourceRef(
                source_id=it.source_id,
                source_name=it.source_name,
                trend_id=canonical_id(
                    it.source_id, it.canonical_url or it.original_url
                ),
                original_url=it.original_url,
                title=it.title,
                hot_score=score,
            )
        )
        pat = it.published_at
        if pat is not None:
            if earliest is None or pat < earliest:
                earliest = pat
            if latest is None or pat > latest:
                latest = pat
    published_at = earliest or items[0].collected_at
    updated_at = latest or items[0].updated_at
    # Event score = hottest member (members are filled by HotScore stage later).
    event_score = max(member_scores) if member_scores else 0.0
    return Event(
        event_id=event_id,
        title=items[0].title,
        summary=items[0].summary,
        category=items[0].category,
        sources=sources,
        source_count=len({s.source_id for s in sources}),
        trend_ids=[s.trend_id for s in sources],
        hot_score=event_score,
        score_breakdown=ScoreBreakdown(
            authority=0, heat=0, freshness=0, multi_source=0, platform=0
        ),
        published_at=published_at,
        updated_at=updated_at,
    )


def finalize_event(event: Event, members: list[Trend]) -> Event:
    """Backfill an Event's score from its scored member Trends (pure).

    Runs AFTER the HotScore stage (Stage 1-2.1 Q3 timing).
    An Event's ``hot_score`` is the hottest member's score (``max``);
    its ``score_breakdown`` is the element-wise ``max`` of member
    breakdowns -- the most "extreme" representative dimension. This keeps
    ``Event.hot_score`` consistent with ``Trend.hot_score`` and never
    re-runs AI. ``sources`` / ``source_count`` / ``trend_ids`` are left
    untouched (the Cluster stage set them, see ``build_event``).
    """
    if not members:
        # Nothing to backfill from; keep the Event as the cluster left it.
        return event
    hot = max(m.hot_score for m in members)
    bd = ScoreBreakdown(
        authority=max(m.score_breakdown.authority for m in members),
        heat=max(m.score_breakdown.heat for m in members),
        freshness=max(m.score_breakdown.freshness for m in members),
        multi_source=max(m.score_breakdown.multi_source for m in members),
        platform=max(m.score_breakdown.platform for m in members),
    )
    return event.model_copy(update={"hot_score": hot, "score_breakdown": bd})


@dataclass(frozen=True)
class MergeContext:
    """Minimal facts a conservative MVP event-aggregator reasons about.

    One per candidate Trend. Kept tiny and pure (no raw item, no AI).
    ``entity`` is the core entity (e.g. paper id / product name);
    ``keywords`` are the core keywords (lower-cased by the caller).
    """

    canonical_url: str
    entity: Optional[str]
    keywords: tuple[str, ...]
    title: str
    published_at: datetime


def decide_event_merge(
    a: MergeContext,
    b: MergeContext,
    *,
    keyword_overlap_min: int = 2,
    window_hours: int = 48,
) -> bool:
    """Conservative MVP event-merge decision (pure, NO AI).

    MVP principle: 宁可少聚合，也不要错误聚合 -- prefering
    under-aggregation over a WRONG aggregation. Merge ONLY when one of:
      (1) canonical URL exactly matches, OR
      (2) core entity matches AND within the time window AND enough
          shared core keywords.

    Title similarity is NEVER a sole trigger -- it is deliberately
    excluded from the decisive logic to avoid false merges. When
    uncertain, return ``False`` (keep as independent Events). The
    detailed rule lives in PIPELINE_DESIGN.md section 17 (Q5).
    """
    # (1) Exact canonical-URL match -> same real artifact -> merge.
    if a.canonical_url and b.canonical_url and a.canonical_url == b.canonical_url:
        return True
    # Time window (applies to the entity/keyword path).
    delta = abs((a.published_at - b.published_at).total_seconds())
    within_window = delta <= window_hours * 3600
    # (2) Composite: entity match + window + keyword overlap.
    entity_match = bool(a.entity and b.entity and a.entity == b.entity)
    shared = set(a.keywords) & set(b.keywords)
    keyword_ok = len(shared) >= keyword_overlap_min
    if entity_match and within_window and keyword_ok:
        return True
    # Title similarity alone is NOT enough -> explicitly do NOT merge.
    return False


# ---------------------------------------------------------------------------
# Stage Protocols (interface only -- no implementation beyond the helpers above)
# ---------------------------------------------------------------------------


@runtime_checkable
class NormalizeStage(Protocol):
    """Unify RawItem fields -> NormalizedItem.

    MUST: canonicalize URL, normalize time format, clean text, map the
    source's category. MUST NOT: invent facts, fabricate summaries, or
    compute any heat.
    """

    def normalize(self, items: list) -> list[NormalizedItem]:
        ...


@runtime_checkable
class ValidationStage(Protocol):
    """Reject items violating production red lines.

    MUST drop (not fix) any item failing ``validate_pipeline_item``. MUST
    NOT mutate a failing item into a passing one.
    """

    def validate(
        self, items: list[NormalizedItem], valid_categories: set[str]
    ) -> tuple[list[NormalizedItem], list[str]]:
        ...


@runtime_checkable
class SourceVerifyStage(Protocol):
    """Verify original_url truth (v2 step [4], Stage 1-2.1 Q2).

    MUST drop items whose original_url host is NOT in the source's
    ``allowed_domains`` set (a SET of official domains, not a single
    declared domain -- see ``verify_original_url``). MUST NOT generate
    or guess URLs.
    """

    def verify(self, item: NormalizedItem, allowed_domains: list[str]) -> bool:
        ...


@runtime_checkable
class DeduplicationStage(Protocol):
    """Collapse same-source + same-URL duplicates (v2 step [5]).

    MUST use ``canonical_id`` to detect duplicates. MUST NOT merge items
    from DIFFERENT urls (those are Event Aggregation, not dedup).
    """

    def dedup(self, items: list[NormalizedItem]) -> list[NormalizedItem]:
        ...


@runtime_checkable
class EventAggregationStage(Protocol):
    """Cluster cross-source same-event items into Events (v2 step [6]).

    MUST keep original Trends (one-to-many). MUST NOT delete source data.
    MUST NOT use AI to decide membership in Stage 1-2 (rule / similarity
    / URL / keyword only).
    """

    def cluster(self, items: list[NormalizedItem]) -> list[list[NormalizedItem]]:
        ...


@runtime_checkable
class HotScoreStage(Protocol):
    """Score each Trend with the 5-dim transparent formula (v2 step [7]).

    MUST run AFTER Event Aggregation (MultiSourceScore needs
    Event.source_count). MUST be pure rules, no AI. MUST store
    score_breakdown for explainability.
    """

    def score(self, items: list[NormalizedItem]) -> list[NormalizedItem]:
        ...


@runtime_checkable
class TopStage(Protocol):
    """Rank by hot_score then cap at <=20 per category (v2 step [9]).

    MUST run BEFORE any AI stage. MUST NOT pad to 20.
    """

    def rank_and_cap(
        self, items: list[Trend], max_per_category: int = 20
    ) -> list[Trend]:
        ...


@runtime_checkable
class PublishStage(Protocol):
    """Assemble the final PublishedData (v2 step [12]).

    MUST run the PublishedData red-line validation (is_mock=false,
    original_url present, count==len(items), <=20) and MUST refuse to
    publish if it fails.
    """

    def assemble(self, *args, **kwargs) -> object:
        ...
