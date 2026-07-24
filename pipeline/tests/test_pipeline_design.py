"""Interface / contract tests for the Stage 1-2 pipeline design.

Pure offline tests -- NO network, NO API, NO RSS, NO AI, NO real data
sources, NO mock production data. They lock the boundaries designed in
docs/PIPELINE_DESIGN.md:

  1. SourceAdapter interface contract (conformance + non-conformance)
  2. Error-isolation contract (safe_fetch / run_sources catch & continue)
  3. RawItem basic structure (RawItem != Trend; no score/event/mock)
  4. Normalize contract (canonicalize_url strips tracking, lowercases host)
  5. Validation contract (red lines enforced, single item isolated)
  6. HotScore combine (5-dim weighted clamp, no AI, no invention)
  7. Deduplication key (same source+URL collide; different URL does not)
  8. Top-20 cap (<=20, never pads)
  9. AI boundary (NullAIProcessor passthrough when disabled)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pipeline.adapters.base import (
    AdapterError,
    AdapterResult,
    SourceAdapter,
    run_sources,
    safe_fetch,
)
from pipeline.ai import AIProcessor, NullAIProcessor
from pipeline.models import (
    HealthStatus,
    LegalStatus,
    ScoreBreakdown,
    SourceConfig,
    SourceType,
    SummaryOrigin,
    Trend,
    TrendStatus,
)
from pipeline.raw import NormalizedItem, RawItem
from pipeline.stages import (
    HotScoreWeights,
    MergeContext,
    build_event,
    build_trend,
    canonical_id,
    canonicalize_url,
    cap_items,
    combine_hot_score,
    decide_event_merge,
    finalize_event,
    host_of,
    validate_pipeline_item,
    verify_original_url,
)
from pipeline.validation import validate_event, validate_production_trend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 7, 24, 9, 0, 0, tzinfo=timezone.utc)


def _config(source_id: str = "arxiv", enabled: bool = True) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name=source_id.title(),
        category="ai_research",
        type=SourceType.API,
        enabled=enabled,
        priority=1,
        max_items=20,
        timeout=20,
        retry_count=2,
        rate_limit="1/3s",
        legal_status=LegalStatus.OFFICIAL_API,
    )


def _raw(source_id: str = "arxiv", url: str = "https://arxiv.org/abs/123") -> RawItem:
    return RawItem(
        source_id=source_id,
        source_name=source_id.title(),
        original_url=url,
        title="A paper",
        published_at=_now(),
        source_item_id=f"{source_id}:1",
        fetched_at=_now(),
        lang="en",
    )


class _GoodAdapter:
    """Conforms to SourceAdapter."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.id
        self.category = config.category

    def fetch(self) -> list[RawItem]:
        return [_raw(self.source_id)]


class _BadAdapter:
    """Missing ``fetch`` -> does NOT satisfy SourceAdapter."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.id
        self.category = config.category


class _BrokenAdapter:
    """fetch() raises -> must be isolated, not propagate."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.id
        self.category = config.category

    def fetch(self) -> list[RawItem]:
        raise AdapterError("simulated source failure")


# ---------------------------------------------------------------------------
# 1. SourceAdapter interface contract
# ---------------------------------------------------------------------------


def test_good_adapter_satisfies_protocol():
    assert isinstance(_GoodAdapter(_config()), SourceAdapter)


def test_bad_adapter_missing_fetch_fails_protocol():
    assert not isinstance(_BadAdapter(_config()), SourceAdapter)


def test_adapter_is_not_responsible_for_score_or_event():
    # Documented boundary: adapter exposes only source identity + fetch.
    adapter = _GoodAdapter(_config())
    assert hasattr(adapter, "fetch")
    assert hasattr(adapter, "source_id")
    assert hasattr(adapter, "config")


# ---------------------------------------------------------------------------
# 2. Error-isolation contract
# ---------------------------------------------------------------------------


def test_safe_fetch_isolates_exception():
    result = safe_fetch(_BrokenAdapter(_config()), now=_now())
    assert isinstance(result, AdapterResult)
    assert result.items == []
    assert result.error is not None
    assert result.health is not None
    assert result.health.status == HealthStatus.FAILED


def test_safe_fetch_healthy_on_items():
    result = safe_fetch(_GoodAdapter(_config()), now=_now())
    assert result.error is None
    assert len(result.items) == 1
    assert result.health.status == HealthStatus.HEALTHY


def test_safe_fetch_degraded_on_empty():
    class _EmptyAdapter(_GoodAdapter):
        def fetch(self):
            return []

    result = safe_fetch(_EmptyAdapter(_config()), now=_now())
    assert result.health.status == HealthStatus.DEGRADED


def test_run_sources_continues_past_failure():
    adapters = [_GoodAdapter(_config("arxiv")), _BrokenAdapter(_config("github"))]
    results = run_sources(adapters, now=_now())
    # Both sources are represented; the broken one is failed, not raising.
    assert set(results.keys()) == {"arxiv", "github"}
    assert results["arxiv"].health.status == HealthStatus.HEALTHY
    assert results["github"].health.status == HealthStatus.FAILED


def test_run_sources_skips_disabled():
    adapters = [_GoodAdapter(_config("arxiv", enabled=False))]
    results = run_sources(adapters, now=_now())
    assert results == {}  # disabled source not run


# ---------------------------------------------------------------------------
# 3. RawItem basic structure
# ---------------------------------------------------------------------------


def test_raw_item_required_fields():
    raw = _raw()
    assert raw.original_url == "https://arxiv.org/abs/123"
    assert raw.source_item_id


def test_raw_item_has_no_score_event_or_mock():
    raw = _raw()
    # RawItem must NOT carry production-only / AI-only fields.
    assert "hot_score" not in type(raw).model_fields
    assert "event_id" not in type(raw).model_fields
    assert "is_mock" not in type(raw).model_fields
    assert "status" not in type(raw).model_fields


def test_raw_item_as_normalized_is_draft_and_not_mock():
    norm = _raw().as_normalized("ai_research")
    assert isinstance(norm, NormalizedItem)
    assert norm.category == "ai_research"
    assert norm.status == TrendStatus.DRAFT
    assert norm.is_mock is False
    assert norm.event_id is None


# ---------------------------------------------------------------------------
# 4. Normalize contract (URL canonicalization)
# ---------------------------------------------------------------------------


def test_canonicalize_url_strips_tracking_and_lowercases():
    url = "https://Example.com/Path/?utm_source=x&id=5#frag"
    canon = canonicalize_url(url)
    assert canon == "https://example.com/Path?id=5"


def test_canonicalize_url_drops_trailing_slash():
    assert canonicalize_url("https://example.com/foo/") == "https://example.com/foo"


def test_canonicalize_url_is_deterministic():
    a = canonicalize_url("https://x.com/a?b=1&utm_source=z")
    b = canonicalize_url("https://x.com/a?utm_source=z&b=1")
    # utm stripped -> identical canonical; query order after stripping is stable
    assert a == b


# ---------------------------------------------------------------------------
# 5. Validation contract (red lines)
# ---------------------------------------------------------------------------


def _valid_normalized() -> NormalizedItem:
    raw = _raw()
    return raw.as_normalized("ai_research")


def test_validation_passes_valid_item():
    assert validate_pipeline_item(_valid_normalized(), {"ai_research"}) == []


def test_validation_rejects_missing_original_url():
    item = _valid_normalized()
    item.original_url = ""
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("original_url" in e for e in errs)


def test_validation_rejects_invalid_url_scheme():
    item = _valid_normalized()
    item.original_url = "javascript:alert(1)"
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("original_url" in e for e in errs)


def test_validation_rejects_bad_category():
    item = _valid_normalized()
    item.category = "not_a_category"
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("category" in e for e in errs)


def test_validation_rejects_is_mock():
    item = _valid_normalized()
    item.is_mock = True
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("is_mock" in e for e in errs)


def test_validation_rejects_future_published_at():
    item = _valid_normalized()
    item.published_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("future" in e for e in errs)


def test_validation_rejects_ai_summary_origin_at_pipeline_stage():
    item = _valid_normalized()
    item.summary_origin = SummaryOrigin.AI
    errs = validate_pipeline_item(item, {"ai_research"})
    assert any("summary_origin" in e for e in errs)


# ---------------------------------------------------------------------------
# 6. HotScore combine (5-dim, no AI)
# ---------------------------------------------------------------------------


def test_combine_hot_score_default_weights():
    # authority=90, heat=70, freshness=80, multi_source=10, platform=50
    # total = .25*90 + .30*70 + .20*80 + .15*10 + .10*50 = 66.0
    bd = ScoreBreakdown(
        authority=90, heat=70, freshness=80, multi_source=10, platform=50
    )
    assert combine_hot_score(bd) == 66.0


def test_combine_hot_score_clamps_to_100():
    bd = ScoreBreakdown(
        authority=100, heat=100, freshness=100, multi_source=100, platform=100
    )
    assert combine_hot_score(bd) == 100.0


def test_combine_hot_score_custom_weights():
    bd = ScoreBreakdown(
        authority=100, heat=0, freshness=0, multi_source=0, platform=0
    )
    w = HotScoreWeights(authority=1.0, heat=0, freshness=0, multi_source=0, platform=0)
    assert combine_hot_score(bd, w) == 100.0


# ---------------------------------------------------------------------------
# 7. Deduplication key
# ---------------------------------------------------------------------------


def test_canonical_id_same_for_same_source_url():
    a = canonical_id("arxiv", canonicalize_url("https://arxiv.org/abs/123?utm=1"))
    b = canonical_id("arxiv", canonicalize_url("https://arxiv.org/abs/123"))
    assert a == b  # same source + canonical url -> dedup collision


def test_canonical_id_differs_for_different_url():
    a = canonical_id("arxiv", "https://arxiv.org/abs/123")
    b = canonical_id("arxiv", "https://arxiv.org/abs/999")
    assert a != b  # different url -> NOT dedup (belongs to Event Aggregation)


# ---------------------------------------------------------------------------
# 8. Top-20 cap
# ---------------------------------------------------------------------------


def _trend(i: int) -> Trend:
    raw = _raw(url=f"https://example.com/{i}")
    norm = raw.as_normalized("ai_research")
    norm.canonical_url = f"https://example.com/{i}"
    return build_trend(
        norm,
        hot_score=float(i),
        breakdown=ScoreBreakdown(
            authority=50, heat=50, freshness=50, multi_source=50, platform=50
        ),
    )


def test_cap_items_never_exceeds_20():
    items = [_trend(i) for i in range(25)]
    assert len(cap_items(items)) == 20


def test_cap_items_never_pads():
    items = [_trend(i) for i in range(5)]
    assert len(cap_items(items)) == 5  # keep real count, do NOT pad


# ---------------------------------------------------------------------------
# 9. AI boundary (disabled = passthrough)
# ---------------------------------------------------------------------------


def test_null_ai_processor_passthrough():
    trend = _trend(1)
    out = NullAIProcessor().enrich(trend)
    assert out is trend or out == trend  # unchanged content


def test_null_ai_fact_check_always_true():
    trend = _trend(1)
    assert NullAIProcessor().fact_check(trend, trend) is True


def test_ai_processor_protocol_satisfied_by_null():
    assert isinstance(NullAIProcessor(), AIProcessor)


# ---------------------------------------------------------------------------
# 10. Assembler boundaries (build_trend / build_event)
# ---------------------------------------------------------------------------


def test_build_trend_keeps_source_identity():
    norm = _valid_normalized()
    trend = build_trend(
        norm,
        hot_score=80.0,
        breakdown=ScoreBreakdown(
            authority=90, heat=70, freshness=80, multi_source=10, platform=50
        ),
    )
    assert trend.source_id == "arxiv"
    assert trend.original_url == "https://arxiv.org/abs/123"
    assert trend.is_mock is False
    assert trend.status == TrendStatus.PUBLISHED


def test_build_event_keeps_all_sources():
    a = _raw("arxiv", "https://arxiv.org/abs/1").as_normalized("ai_research")
    b = _raw("github", "https://github.com/x").as_normalized("opensource")
    event = build_event("evt1", [a, b])
    assert event.source_count == 2
    assert len(event.sources) == 2
    assert {s.source_id for s in event.sources} == {"arxiv", "github"}
    # original_urls preserved for traceability
    assert {s.original_url for s in event.sources} == {
        "https://arxiv.org/abs/1",
        "https://github.com/x",
    }


# ---------------------------------------------------------------------------
# 11. Q1 -- NormalizedItem is a PURE internal intermediate (not Trend/Published)
# ---------------------------------------------------------------------------


def test_normalized_has_no_production_score_fields():
    norm = _valid_normalized()
    # NormalizedItem must NOT carry the production scoring fields.
    assert "hot_score" not in type(norm).model_fields
    assert "score_breakdown" not in type(norm).model_fields
    assert not isinstance(norm, Trend)  # distinct type from the published model


def test_normalized_draft_is_not_production_ready():
    norm = _valid_normalized()  # is_mock=False, status=DRAFT, no score
    # (a) It PASSES pipeline validation -> it entered the pipeline...
    assert validate_pipeline_item(norm, {"ai_research"}) == []
    # (b) ...but is_mock=False does NOT mean "trusted production".
    # (c) ...and status=DRAFT does NOT mean "passed production validation".
    bd = ScoreBreakdown(
        authority=50, heat=50, freshness=50, multi_source=50, platform=50
    )
    draft_trend = build_trend(norm, 80.0, bd, status=TrendStatus.DRAFT)
    prod_errs = validate_production_trend(draft_trend)
    assert any("status" in e for e in prod_errs)
    # Only status=PUBLISHED + real score promotes it to production.
    pub_trend = build_trend(norm, 80.0, bd, status=TrendStatus.PUBLISHED)
    assert validate_production_trend(pub_trend) == []


# ---------------------------------------------------------------------------
# 12. Q2 -- Source verification: allowed_domains is a SET, not one domain
# ---------------------------------------------------------------------------


def test_host_of_lowercases_and_handles_garbage():
    assert host_of("https://Example.com/foo") == "example.com"
    assert host_of("not a url") is None
    assert host_of("") is None


def test_verify_original_url_matches_allowed_set():
    allowed = ["github.com", "github.blog"]
    assert verify_original_url("https://github.com/foo", allowed) is True
    assert verify_original_url("https://github.blog/post", allowed) is True
    # registered subdomain of an allowed official domain is accepted
    assert verify_original_url("https://gist.github.com/x", allowed) is True


def test_verify_original_url_rejects_unknown_and_suffix_attacks():
    allowed = ["github.com"]
    assert verify_original_url("https://gitlab.com/x", allowed) is False
    # suffix-attack hosts must NOT match
    assert verify_original_url("https://github.com.evil.net", allowed) is False
    assert verify_original_url("https://notgithub.com", allowed) is False


def test_verify_original_url_requires_https_by_default():
    allowed = ["example.com"]
    assert verify_original_url("http://example.com/x", allowed) is False
    assert (
        verify_original_url("http://example.com/x", allowed, require_https=False)
        is True
    )


def test_verify_original_url_empty_allowed_is_false():
    assert verify_original_url("https://example.com/x", []) is False


# ---------------------------------------------------------------------------
# 13. Q3 -- Trend.hot_score vs Event.hot_score timing consistency
# ---------------------------------------------------------------------------


def _scored_trend(source_id: str, url: str, score: float) -> Trend:
    raw = _raw(source_id, url)
    norm = raw.as_normalized("ai_research")
    norm.canonical_url = canonicalize_url(url)
    return build_trend(
        norm,
        hot_score=score,
        breakdown=ScoreBreakdown(
            authority=score, heat=score, freshness=score,
            multi_source=score, platform=score,
        ),
    )


def test_finalize_event_takes_max_member_score():
    # Cluster produced an Event; HotScore then scored the member Trends.
    members = [
        _scored_trend("arxiv", "https://arxiv.org/abs/1", 50.0),
        _scored_trend("github", "https://github.com/x", 80.0),
        _scored_trend("openai", "https://openai.com/y", 60.0),
    ]
    # The Event was built earlier by the Cluster stage from NormalizedItems.
    norms = [
        _raw("arxiv", "https://arxiv.org/abs/1").as_normalized("ai_research"),
        _raw("github", "https://github.com/x").as_normalized("opensource"),
        _raw("openai", "https://openai.com/y").as_normalized("ai_official"),
    ]
    event = build_event("evt1", norms)
    finalized = finalize_event(event, members)
    # Event.hot_score = max(member Trend.hot_score) = 80.0
    assert finalized.hot_score == 80.0
    # Event.score_breakdown = element-wise max of members
    assert finalized.score_breakdown.authority == 80.0
    assert finalized.score_breakdown.heat == 80.0
    # sources / source_count / trend_ids untouched by finalize_event
    assert finalized.source_count == event.source_count


def test_finalize_event_empty_members_keeps_event():
    event = build_event(
        "evt1", [_raw("arxiv", "https://arxiv.org/abs/1").as_normalized("ai_research")]
    )
    # cannot backfill if members don't correspond; ensure it doesn't crash
    assert finalize_event(event, []).event_id == "evt1"


# ---------------------------------------------------------------------------
# 14. Q5 -- Conservative MVP event-merge (never on title similarity alone)
# ---------------------------------------------------------------------------


def _ctx(
    url: str,
    entity: Optional[str],
    keywords: tuple[str, ...],
    title: str,
    when: Optional[datetime] = None,
) -> MergeContext:
    return MergeContext(
        canonical_url=canonicalize_url(url),
        entity=entity,
        keywords=keywords,
        title=title,
        published_at=when or _now(),
    )


def test_merge_same_canonical_url():
    a = _ctx("https://arxiv.org/abs/123", "paper X", ("a", "b"), "Title")
    b = _ctx("https://arxiv.org/abs/123?utm=1", "paper X", ("a", "b"), "Other")
    assert decide_event_merge(a, b) is True  # same artifact -> merge


def test_no_merge_on_title_similarity_alone():
    a = _ctx("https://site-a.com/1", None, ("x",), "GPT-5 发布", _now())
    b = _ctx("https://site-b.com/2", None, ("y",), "GPT-5 发布", _now())
    # title identical but no entity/keyword match and different URLs -> NOT merged
    assert decide_event_merge(a, b) is False


def test_merge_on_entity_plus_window_plus_keywords():
    when = _now()
    a = _ctx(
        "https://news.com/1", "GPT-5", ("llm", "release", "openai"),
        "OpenAI 发布 GPT-5", when,
    )
    b = _ctx(
        "https://blog.com/2", "GPT-5", ("llm", "openai", "model"),
        "GPT-5 技术细节", when,
    )
    assert decide_event_merge(a, b) is True


def test_no_merge_when_keyword_overlap_too_small():
    when = _now()
    a = _ctx("https://news.com/1", "GPT-5", ("llm", "release"), "X", when)
    b = _ctx("https://blog.com/2", "GPT-5", ("openai",), "Y", when)
    # entity matches + window ok, but only 0 shared keywords (< min 2)
    assert decide_event_merge(a, b) is False


def test_no_merge_outside_time_window():
    a = _ctx("https://news.com/1", "GPT-5", ("llm", "openai"), "X", _now())
    b = _ctx(
        "https://blog.com/2", "GPT-5", ("llm", "openai"),
        "Y", datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc),
    )
    # entity + keywords match, but 23 days apart (> 48h window)
    assert decide_event_merge(a, b) is False


# ---------------------------------------------------------------------------
# 15. Q4 (Stage 1-2.2) -- source_count = distinct source_id count
# ---------------------------------------------------------------------------


def _evt_sources(specs) -> list:
    """Build NormalizedItems from (source_id, url) pairs."""
    return [_raw(sid, url).as_normalized("ai_research") for sid, url in specs]


def test_source_count_one_source_one_url():
    ev = build_event("e1", _evt_sources([("tc", "https://tc.com/a")]))
    assert len(ev.sources) == 1
    assert ev.source_count == 1


def test_source_count_two_distinct_sources():
    ev = build_event(
        "e1",
        _evt_sources([("tc", "https://tc.com/a"), ("oa", "https://openai.com/b")]),
    )
    assert len(ev.sources) == 2
    assert ev.source_count == 2


def test_source_count_two_same_source_diff_url():
    # same source, two different URLs -> still ONE distinct source
    ev = build_event(
        "e1",
        _evt_sources([("tc", "https://tc.com/a"), ("tc", "https://tc.com/b")]),
    )
    assert len(ev.sources) == 2  # all evidence kept
    assert ev.source_count == 1  # but counted once


def test_source_count_aa_b_is_two():
    # evidence A + A + B -> source_count = 2 (distinct = {tc, oa})
    ev = build_event(
        "e1",
        _evt_sources([
            ("tc", "https://tc.com/a"),
            ("tc", "https://tc.com/b"),
            ("oa", "https://openai.com/c"),
        ]),
    )
    assert len(ev.sources) == 3
    assert ev.source_count == 2


def test_source_count_wrong_value_fails_validation():
    ev = build_event(
        "e1",
        _evt_sources([
            ("tc", "https://tc.com/a"),
            ("tc", "https://tc.com/b"),
            ("oa", "https://openai.com/c"),
        ]),
    )
    assert ev.source_count == 2  # correct value passes
    assert validate_event(ev) == []
    ev.source_count = 3  # claims 3 distinct but only 2 -> must fail
    assert validate_event(ev) != []


def test_sources_not_deduped_on_same_source_id():
    ev = build_event(
        "e1",
        _evt_sources([
            ("tc", "https://tc.com/a"),
            ("tc", "https://tc.com/b"),
            ("oa", "https://openai.com/c"),
        ]),
    )
    # every source evidence is preserved despite a repeated source_id
    assert len(ev.sources) == 3
    assert {s.source_id for s in ev.sources} == {"tc", "oa"}
    assert {s.original_url for s in ev.sources} == {
        "https://tc.com/a",
        "https://tc.com/b",
        "https://openai.com/c",
    }
    tc_refs = [s for s in ev.sources if s.source_id == "tc"]
    assert len(tc_refs) == 2  # both tc reposts retained
    assert {r.original_url for r in tc_refs} == {
        "https://tc.com/a",
        "https://tc.com/b",
    }


def _multi_source_score(source_count: int, k: int = 5) -> float:
    """Mirror the HotScore MultiSource dimension: min(1, source_count / K)."""
    return min(1.0, source_count / k) * 100.0


def test_multisource_score_uses_distinct_source_count():
    # sources A + A + B -> source_count = 2 (NOT len(sources) = 3)
    ev = build_event(
        "e1",
        _evt_sources([
            ("tc", "https://tc.com/a"),
            ("tc", "https://tc.com/b"),
            ("oa", "https://openai.com/c"),
        ]),
    )
    assert ev.source_count == 2
    # MultiSourceScore reads Event.source_count, not len(sources)
    score = _multi_source_score(ev.source_count)  # 2/5 -> 40.0
    assert score == 40.0
    # explicit guard: it must NOT have used len(sources) = 3 -> 60.0
    assert score != _multi_source_score(len(ev.sources))

