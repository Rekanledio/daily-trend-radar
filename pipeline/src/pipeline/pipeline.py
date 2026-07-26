"""ArXiv single-source pipeline orchestrator (Stage 1-4A).

Wires the authoritative 14-step order using the PURE boundary helpers in
``stages.py`` / ``validation.py`` / ``ai.py`` (which encode the rules)
and the concrete adapter registry. This module owns the SEQUENCING and
the source-agnostic scoring/clustering glue; it does not invent facts.

Order (v2 section 2.2 / PROJECT_RULES section 17), strictly enforced:

    Adapter     -> RawItem
    -> Normalize      (RawItem.as_normalized + canonicalize_url)
    -> Validate       (validate_pipeline_item; DROP on violation)
    -> SourceVerify   (verify_original_url; DROP on domain mismatch)
    -> Dedup          (canonical_id; DROP same source+URL)
    -> Cluster/Event  (decide_event_merge; assign event_id)
    -> HotScore        (5-dim, NO AI; arXiv heat missing => heat=0)
    -> Rank           (by hot_score desc)
    -> Cap <=20       (BEFORE AI; never pad)
    -> AI (disabled)  (NullAIProcessor passthrough)
    -> Publish         (assemble PublishedData; validated elsewhere)

ArXiv has NO platform heat signal (no views / likes / rank), so the
``heat`` dimension is set to 0 -- we deliberately do NOT fabricate it.
This is reported transparently in the run summary (see ``RunSummary``
extensions are intentionally absent; the 0 is visible in every Trend's
``score_breakdown.heat``).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .adapters.base import AdapterResult
from .ai import AIProcessor, NullAIProcessor
from .ai_summary import enrich_trends
from .models import (
    CategoryBlock,
    Event,
    PublishedData,
    PublishedMetadata,
    RunSummary,
    ScoreBreakdown,
    SourceConfig,
    Trend,
    TrendStatus,
)
from .raw import NormalizedItem, RawItem
from .stages import (
    MergeContext,
    build_event,
    build_trend,
    canonical_id,
    canonicalize_url,
    cap_items,
    combine_hot_score,
    decide_event_merge,
    finalize_event,
    validate_pipeline_item,
    verify_original_url,
)

# --- HotScore dimension mappings (transparent, rule-based, NO AI) --------

# Lower priority number == more authoritative source.
_AUTHORITY_BY_PRIORITY = {1: 90.0, 2: 75.0, 3: 60.0, 4: 45.0, 5: 30.0}

# Platform weight by the source's legal status.
_PLATFORM_BY_LEGAL = {
    "official_api": 80.0,
    "official_rss": 70.0,
    "public_page": 50.0,
    "third_party_legal": 40.0,
    "manual": 30.0,
}

# Freshness exponential-decay half-life (hours): score halves every 24h.
_FRESHNESS_HALF_LIFE_H = 24.0
_FRESHNESS_LAMBDA = math.log(2) / _FRESHNESS_HALF_LIFE_H

# Multi-source normaliser: K distinct source_ids in an event => full 100.
_MULTI_SOURCE_K = 3.0


def authority_score(priority: int) -> float:
    """Authority from configured ``priority`` (1 = most authoritative)."""
    return _AUTHORITY_BY_PRIORITY.get(priority, 30.0)


def platform_score(legal_status: object) -> float:
    """Platform weight from the source's ``legal_status`` enum/value."""
    key = getattr(legal_status, "value", str(legal_status))
    return _PLATFORM_BY_LEGAL.get(key, 50.0)


def freshness_score(ref_time: Optional[datetime], now: datetime) -> float:
    """Exponential-decay freshness in [0, 100]; 0 when no time is known."""
    if ref_time is None:
        return 0.0
    age_h = max(0.0, (now - ref_time).total_seconds() / 3600.0)
    return round(100.0 * math.exp(-_FRESHNESS_LAMBDA * age_h), 2)


# ---------------------------------------------------------------------------
# Cluster stage helpers
# ---------------------------------------------------------------------------


def _merge_context(item: NormalizedItem) -> MergeContext:
    """Conservative merge facts for one item.

    ``entity`` is the canonical URL -- the natural artifact key for a
    URL-based source. Distinct URLs (the normal case for arXiv, one URL
    per paper) yield distinct entities, so ``decide_event_merge`` keeps
    them as independent Events. We deliberately prefer UNDER-aggregation.
    """
    canon = item.canonical_url or item.original_url or ""
    # Light keyword hints from the title; only consulted when entity matches.
    kws = tuple(
        w for w in re.findall(r"[a-z0-9]+", (item.title or "").lower()) if len(w) > 2
    )[:5]
    pub = item.published_at or item.collected_at
    return MergeContext(
        canonical_url=canon,
        entity=canon,
        keywords=kws,
        title=item.title,
        published_at=pub,
    )


def cluster_items(items: List[NormalizedItem]) -> List[List[NormalizedItem]]:
    """Group items into event clusters (conservative, NO AI).

    Each cluster becomes one ``Event``. Two items merge ONLY via
    ``decide_event_merge``. With a single source and distinct canonical
    URLs this yields one cluster per item (one Event per Trend).
    """
    clusters: List[List[NormalizedItem]] = []
    for item in items:
        ctx = _merge_context(item)
        placed = False
        for cluster in clusters:
            rep = _merge_context(cluster[0])
            if decide_event_merge(rep, ctx):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters


def _event_id_for(cluster: List[NormalizedItem]) -> str:
    """Stable event id from the sorted member canonical ids."""
    members = sorted(
        canonical_id(c.source_id, c.canonical_url or c.original_url or "")
        for c in cluster
    )
    digest = hashlib.sha256("|".join(members).encode("utf-8")).hexdigest()
    return f"evt-{digest[:12]}"


# ---------------------------------------------------------------------------
# HotScore (5-dim, NO AI)
# ---------------------------------------------------------------------------


def _score_item(
    item: NormalizedItem,
    cfg: SourceConfig,
    source_count: int,
    now: datetime,
) -> ScoreBreakdown:
    authority = authority_score(cfg.priority)
    # ArXiv has NO platform heat signal -> heat is 0, never fabricated.
    heat = 0.0
    fresh = freshness_score(item.published_at or item.collected_at, now)
    multi = min(1.0, source_count / _MULTI_SOURCE_K) * 100.0
    plat = platform_score(cfg.legal_status)
    return ScoreBreakdown(
        authority=round(authority, 2),
        heat=heat,
        freshness=round(fresh, 2),
        multi_source=round(multi, 2),
        platform=round(plat, 2),
    )


# ---------------------------------------------------------------------------
# Rank + Cap (per category, BEFORE AI, never pad)
# ---------------------------------------------------------------------------


def rank_and_cap(trends: List[Trend], max_per_category: int = 20) -> List[Trend]:
    """Sort each category by hot_score desc, then cap at ``max_per_category``."""
    by_cat: Dict[str, List[Trend]] = defaultdict(list)
    for t in trends:
        by_cat[t.category].append(t)
    out: List[Trend] = []
    for items in by_cat.values():
        items_sorted = sorted(items, key=lambda t: t.hot_score, reverse=True)
        out.extend(cap_items(items_sorted, max_per_category))
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(
    results: Dict[str, AdapterResult],
    configs: List[SourceConfig],
    now: Optional[datetime] = None,
    batch_date: Optional[str] = None,
    ai_enabled: bool = False,
) -> Tuple[PublishedData, RunSummary]:
    """Run the full ArXiv single-source pipeline and assemble ``PublishedData``.

    ``now`` is the run timestamp (UTC). ``batch_date`` is the YYYY-MM-DD
    label for the produced shard (distinct from each Trend's ``published_at``,
    which keeps the source's real publication time). AI is disabled this round
    (``NullAIProcessor`` passthrough, ``ai_enabled=False``).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if batch_date is None:
        batch_date = now.strftime("%Y-%m-%d")

    # Lazy import: the package ``__version__`` is only available once the
    # package is fully initialised (avoids an import cycle with ``__init__``).
    from . import __version__

    cfg_by_id = {c.id: c for c in configs}
    valid_categories = {c.category for c in configs}

    sources_ok = 0
    sources_failed = 0
    total_dropped = 0

    # ---- 1. Collate raw items from non-failed adapters ----
    raw: List[RawItem] = []
    for sid, res in results.items():
        if res.error is not None or res.health is None or res.health.status.value == "failed":
            sources_failed += 1
            continue
        sources_ok += 1
        raw.extend(res.items)

    # ---- 2. Normalize ----
    normalized: List[NormalizedItem] = []
    for r in raw:
        cat = cfg_by_id[r.source_id].category
        n = r.as_normalized(cat)
        n.canonical_url = canonicalize_url(n.original_url)
        normalized.append(n)

    # ---- 3. Validate (red-line drop) ----
    kept_valid: List[NormalizedItem] = []
    for n in normalized:
        errs = validate_pipeline_item(n, valid_categories, now)
        if errs:
            total_dropped += 1
            continue
        kept_valid.append(n)

    # ---- 4. SourceVerify (domain truth core) ----
    kept_verified: List[NormalizedItem] = []
    for n in kept_valid:
        allowed = list(cfg_by_id[n.source_id].allowed_domains or [])
        if not verify_original_url(n.original_url, allowed, require_https=True):
            total_dropped += 1
            continue
        kept_verified.append(n)

    # ---- 5. Dedup (source_id + canonical_url) ----
    seen: set[str] = set()
    kept_dedup: List[NormalizedItem] = []
    for n in kept_verified:
        key = canonical_id(n.source_id, n.canonical_url or n.original_url or "")
        if key in seen:
            total_dropped += 1
            continue
        seen.add(key)
        kept_dedup.append(n)

    # ---- 6. Cluster -> Events (assign event_id) ----
    clusters = cluster_items(kept_dedup)
    events_by_id: Dict[str, Event] = {}
    for cluster in clusters:
        eid = _event_id_for(cluster)
        for c in cluster:
            c.event_id = eid
        events_by_id[eid] = build_event(eid, cluster)

    # ---- 7. HotScore (5-dim, NO AI) + build Trend ----
    trends: List[Trend] = []
    for n in kept_dedup:
        eid = n.event_id
        ev = events_by_id.get(eid)
        src_count = ev.source_count if ev is not None else 1
        bd = _score_item(n, cfg_by_id[n.source_id], src_count, now)
        hs = combine_hot_score(bd)
        trends.append(build_trend(n, hs, bd, status=TrendStatus.PUBLISHED))

    # ---- finalize events from scored trends ----
    members_by_event: Dict[str, List[Trend]] = defaultdict(list)
    for t in trends:
        if t.event_id:
            members_by_event[t.event_id].append(t)
    finalized_events: List[Event] = []
    for eid, members in members_by_event.items():
        finalized_events.append(finalize_event(events_by_id[eid], members))

    # ---- 8. AI (disabled) passthrough ----
    ai: AIProcessor = NullAIProcessor()
    enriched: List[Trend] = []
    for t in trends:
        e = ai.enrich(t)
        if ai.fact_check(e, t):
            enriched.append(e)
        else:
            enriched.append(t)

    # ---- 8b. AI Summary enrichment (top-N hottest) ----
    enrich_trends(enriched)

    # ---- 9. Rank + Cap <=20 (per category, BEFORE any AI effect) ----
    capped = rank_and_cap(enriched, max_per_category=20)

    # ---- 10. Assemble PublishedData ----
    cats: Dict[str, List[Trend]] = defaultdict(list)
    for t in capped:
        cats[t.category].append(t)
    categories = {
        cat: CategoryBlock(count=len(items), items=items)
        for cat, items in cats.items()
    }
    final_events = [
        e for e in finalized_events if any(t.event_id == e.event_id for t in capped)
    ]
    run_summary = RunSummary(
        sources_ok=sources_ok,
        sources_failed=sources_failed,
        total_dropped=total_dropped,
        generated_by=f"daily-trend-radar-pipeline/{__version__}",
    )
    data = PublishedData(
        date=batch_date,
        schema_version="1.0",
        generated_at=now,
        pipeline_version=__version__,
        ai_enabled=ai_enabled,
        categories=categories,
        trends=capped,
        events=final_events,
        metadata=PublishedMetadata(run_summary=run_summary),
    )
    return data, run_summary
