"""Tests for the rule-based Trend Scoring System (Stage 4-3)."""

from __future__ import annotations

from datetime import datetime, timezone

from pipeline.models import AISummary, ScoreBreakdown, Trend, TrendStatus
from pipeline.scoring import score_trend, score_trends, _source_score, _hot_score_component, _freshness_score, _ai_relevance_score, _determine_impact_level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_trend(
    title: str = "Test Trend",
    source_id: str = "github",
    source_name: str = "GitHub",
    hot_score: float = 50.0,
    published_at: datetime | None = None,
    ai_summary: AISummary | None = None,
    summary: str | None = None,
) -> Trend:
    return Trend(
        id="test-id-001",
        source_id=source_id,
        source_name=source_name,
        category="opensource",
        title=title,
        summary=summary,
        summary_origin="original",
        original_url="https://github.com/test/repo",
        tags=["test"],
        tags_origin="rule",
        published_at=published_at or _FIXED_NOW,
        collected_at=_FIXED_NOW,
        updated_at=_FIXED_NOW,
        hot_score=hot_score,
        score_breakdown=ScoreBreakdown(
            authority=50.0,
            heat=50.0,
            freshness=50.0,
            multi_source=0.0,
            platform=50.0,
        ),
        status=TrendStatus.PUBLISHED,
    )


# ---------------------------------------------------------------------------
# Component tests
# ---------------------------------------------------------------------------


class TestSourceScore:
    def test_github_gets_high_weight(self):
        trend = _make_trend(source_id="github")
        score, reason = _source_score(trend)
        assert score == 28.0
        assert "GitHub" in reason

    def test_arxiv_gets_medium_high_weight(self):
        trend = _make_trend(source_id="arxiv", source_name="arXiv")
        score, reason = _source_score(trend)
        assert score == 26.0
        assert "arXiv" in reason

    def test_unknown_source_gets_default(self):
        trend = _make_trend(source_id="rss_blog")
        score, reason = _source_score(trend)
        assert score == 20.0


class TestHotScoreComponent:
    def test_hot_100_maps_to_30(self):
        trend = _make_trend(hot_score=100.0)
        score, reason = _hot_score_component(trend)
        assert score == 30.0

    def test_hot_50_maps_to_15(self):
        trend = _make_trend(hot_score=50.0)
        score, reason = _hot_score_component(trend)
        assert score == 15.0

    def test_hot_0_maps_to_0(self):
        trend = _make_trend(hot_score=0.0)
        score, reason = _hot_score_component(trend)
        assert score == 0.0


class TestFreshnessScore:
    def test_now_gets_max(self):
        trend = _make_trend(published_at=_FIXED_NOW)
        score, reason = _freshness_score(trend, _FIXED_NOW)
        assert score == 20.0

    def test_two_days_ago_gets_half(self):
        two_days = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        trend = _make_trend(published_at=two_days)
        score, reason = _freshness_score(trend, _FIXED_NOW)
        assert 9.5 < score < 10.5  # roughly half of 20

    def test_no_timestamp_gets_zero(self):
        """Very old timestamp → freshness exponentially close to 0."""
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        trend = _make_trend(published_at=old, summary="old trend")
        score, reason = _freshness_score(trend, _FIXED_NOW)
        assert score == 0.0  # 6.5 years old → rounds to 0


class TestAIRelevanceScore:
    def test_title_with_ai_keyword_scores(self):
        trend = _make_trend(title="A new LLM for chat applications")
        score, reason = _ai_relevance_score(trend)
        assert score > 0.0
        assert "1 keywords" in reason or "AI" in reason

    def test_multiple_keywords_score_higher(self):
        trend = _make_trend(
            title="LLM Agent with Transformer Architecture and Deep Learning",
            summary="Fine tuning and RLHF for language models",
            ai_summary=AISummary(
                summary="AI model summary",
                why_it_matters="Important for ML community",
                keywords=["neural", "diffusion", "rag"],
            ),
        )
        score, reason = _ai_relevance_score(trend)
        assert score > 10.0
        assert "keywords" in reason

    def test_no_keywords_gets_low(self):
        trend = _make_trend(title="My Weekend Cooking Blog")
        score, reason = _ai_relevance_score(trend)
        assert score == 0.0


class TestImpactLevel:
    def test_critical_at_80(self):
        assert _determine_impact_level(80.0) == "critical"

    def test_high_at_70(self):
        assert _determine_impact_level(70.0) == "high"

    def test_medium_at_50(self):
        assert _determine_impact_level(50.0) == "medium"

    def test_low_at_30(self):
        assert _determine_impact_level(30.0) == "low"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestScoreTrend:
    def test_sets_all_fields(self):
        trend = _make_trend(
            title="LLM Agent Framework",
            source_id="github",
            hot_score=80.0,
            published_at=_FIXED_NOW,
            ai_summary=AISummary(
                summary="New LLM agent framework",
                why_it_matters="Important for AI development",
                keywords=["llm", "agent"],
            ),
        )
        result = score_trend(trend, now=_FIXED_NOW)

        assert result.trend_score is not None
        assert 0 <= result.trend_score <= 100
        assert result.impact_level in ("critical", "high", "medium", "low")
        assert isinstance(result.score_reason, list)
        assert len(result.score_reason) == 4

    def test_low_scoring_trend_gets_low_impact(self):
        trend = _make_trend(
            title="My personal blog",
            source_id="rss_blog",
            hot_score=5.0,
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        result = score_trend(trend, now=_FIXED_NOW)
        assert result.trend_score is not None
        assert result.trend_score < 40.0  # likely low
        assert result.impact_level == "low"

    def test_fields_are_serializable(self):
        trend = _make_trend()
        result = score_trend(trend, now=_FIXED_NOW)
        d = result.model_dump()
        assert "trend_score" in d
        assert "impact_level" in d
        assert "score_reason" in d
        assert isinstance(d["trend_score"], float)
        assert isinstance(d["impact_level"], str)
        assert isinstance(d["score_reason"], list)


class TestScoreTrends:
    def test_returns_same_order(self):
        t1 = _make_trend(title="Trend A", hot_score=90.0)
        t2 = _make_trend(title="Trend B", hot_score=30.0)
        t3 = _make_trend(title="Trend C", hot_score=60.0)
        results = score_trends([t1, t2, t3], now=_FIXED_NOW)
        assert len(results) == 3
        assert results[0].title == "Trend A"
        assert results[1].title == "Trend B"
        assert results[2].title == "Trend C"

    def test_all_get_scored(self):
        trends = [_make_trend(title=f"Trend {i}") for i in range(10)]
        results = score_trends(trends, now=_FIXED_NOW)
        for t in results:
            assert t.trend_score is not None
            assert t.impact_level is not None
            assert t.score_reason is not None
