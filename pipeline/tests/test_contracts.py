"""Contract tests for Daily Trend Radar data models and JSON Schemas.

Pure offline tests -- no network, no API, no RSS, no AI, no real data sources.
They assert:
  1. A valid Trend passes production validation.
  2. A production Trend missing original_url (or empty) fails.
  3. A production Trend with is_mock=true fails.
  4. Each category is capped at 20 items; 20 is OK, 21 raises.
  5. status must be a valid enum value.
  6. summary_origin must be a valid enum value.
  7. Health status enum is enforced; overall may be null (never "unknown").
  8. Event <-> Trend association fields are consistent.
  + JSON Schemas are valid and validate a real PublishedData dict.
  + Pydantic field names match JSON Schema properties (anti-drift guard).
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from pipeline import (
    CategoryBlock,
    Event,
    EventSourceRef,
    HealthSnapshot,
    PublishedData,
    PublishedMetadata,
    RunSummary,
    ScoreBreakdown,
    SourceHealth,
    SummaryOrigin,
    TagsOrigin,
    Trend,
    TrendStatus,
)
from pipeline import models as models_mod
from pipeline.validation import (
    validate_event,
    validate_production_trend,
    validate_published_data,
)

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 7, 24, 9, 0, 0, tzinfo=timezone.utc)


def _valid_trend(**overrides) -> Trend:
    base = dict(
        id="t1",
        event_id=None,
        source_id="arxiv",
        source_name="arXiv",
        category="ai_research",
        title="Test paper",
        summary="A paper",
        summary_origin=SummaryOrigin.ORIGINAL,
        original_url="https://arxiv.org/abs/123",
        canonical_url="https://arxiv.org/abs/123",
        author=None,
        tags=["llm"],
        tags_origin=TagsOrigin.RULE,
        published_at=_now(),
        collected_at=_now(),
        updated_at=_now(),
        heat_raw={"rank": 1},
        hot_score=80.0,
        score_breakdown=ScoreBreakdown(
            authority=90, heat=70, freshness=80, multi_source=10, platform=50
        ),
        rank_in_source=1,
        status=TrendStatus.PUBLISHED,
        lang="en",
        is_mock=False,
    )
    base.update(overrides)
    return Trend(**base)


def _valid_event(trend: Trend) -> Event:
    ref = EventSourceRef(
        source_id=trend.source_id,
        source_name=trend.source_name,
        trend_id=trend.id,
        original_url=trend.original_url,
        title=trend.title,
        hot_score=trend.hot_score,
    )
    return Event(
        event_id="e1",
        title=trend.title,
        summary=trend.summary,
        category=trend.category,
        sources=[ref],
        source_count=1,
        trend_ids=[trend.id],
        hot_score=trend.hot_score,
        score_breakdown=trend.score_breakdown,
        published_at=trend.published_at or _now(),
        updated_at=trend.updated_at,
    )


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    resources = {}
    for f in SCHEMA_DIR.glob("*.schema.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        resources[s["$id"]] = Resource.from_contents(s)
    return Registry().with_resources(resources.items())


# ---------------------------------------------------------------------------
# 1. valid trend passes production validation
# ---------------------------------------------------------------------------


def test_valid_trend_passes_production_validation():
    assert validate_production_trend(_valid_trend()) == []


# ---------------------------------------------------------------------------
# 2. missing / empty original_url fails (production rule + schema)
# ---------------------------------------------------------------------------


def test_missing_original_url_rejected_by_schema():
    # Truly missing key -> Pydantic construction fails.
    with pytest.raises(ValidationError):
        _valid_trend(original_url=None)  # type: ignore[arg-type]


def test_empty_original_url_fails_production_rule():
    errs = validate_production_trend(_valid_trend(original_url=""))
    assert any("original_url" in e for e in errs)


# ---------------------------------------------------------------------------
# 3. is_mock=true fails production
# ---------------------------------------------------------------------------


def test_is_mock_fails_production():
    errs = validate_production_trend(_valid_trend(is_mock=True))
    assert any("is_mock" in e for e in errs)


# ---------------------------------------------------------------------------
# 4. each category capped at 20
# ---------------------------------------------------------------------------


def test_category_20_items_ok():
    items = [
        _valid_trend(id=f"t{i}", original_url=f"https://example.com/{i}",
                     canonical_url=f"https://example.com/{i}")
        for i in range(20)
    ]
    block = CategoryBlock(count=20, items=items)
    assert len(block.items) == 20


def test_category_21_items_rejected():
    items = [
        _valid_trend(id=f"t{i}", original_url=f"https://example.com/{i}",
                     canonical_url=f"https://example.com/{i}")
        for i in range(21)
    ]
    with pytest.raises(ValidationError):
        CategoryBlock(count=21, items=items)


# ---------------------------------------------------------------------------
# 5. status enum enforced
# ---------------------------------------------------------------------------


def test_status_enum_enforced():
    with pytest.raises(ValidationError):
        _valid_trend(status="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. summary_origin enum enforced
# ---------------------------------------------------------------------------


def test_summary_origin_enum_enforced():
    with pytest.raises(ValidationError):
        _valid_trend(summary_origin="generated")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. health status enum enforced; overall may be null (never "unknown")
# ---------------------------------------------------------------------------


def test_health_overall_null_allowed():
    h = HealthSnapshot(schema_version="1.0", generated_at=None, overall=None, sources=[])
    assert h.overall is None


def test_health_status_enum_enforced():
    with pytest.raises(ValidationError):
        SourceHealth(source_id="x", name="X", category="c", status="weird")  # type: ignore[arg-type]


def test_health_overall_unknown_rejected():
    with pytest.raises(ValidationError):
        HealthSnapshot(schema_version="1.0", overall="unknown")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. event <-> trend association consistency
# ---------------------------------------------------------------------------


def test_event_trend_association_valid():
    assert validate_event(_valid_event(_valid_trend())) == []


def test_event_trend_association_mismatch_detected():
    event = _valid_event(_valid_trend())
    event.source_count = 2  # mismatch with len(sources)
    assert validate_event(event) != []


def test_event_trend_ids_mismatch_detected():
    event = _valid_event(_valid_trend())
    event.trend_ids = ["nonexistent"]
    assert validate_event(event) != []


# ---------------------------------------------------------------------------
# JSON Schema validity + a real PublishedData validates against it
# ---------------------------------------------------------------------------


def test_json_schemas_are_valid():
    for f in SCHEMA_DIR.glob("*.schema.json"):
        Draft202012Validator.check_schema(_load_schema(f.name))


def test_published_data_validates_against_json_schema():
    trend = _valid_trend()
    data = PublishedData(
        date="2026-07-24",
        schema_version="1.0",
        generated_at=_now(),
        pipeline_version="0.2.0",
        ai_enabled=False,
        categories={"ai_research": CategoryBlock(count=1, items=[trend])},
        trends=[trend],
        events=[],
        metadata=PublishedMetadata(
            run_summary=RunSummary(sources_ok=1, sources_failed=0, total_dropped=0)
        ),
    )
    validator = Draft202012Validator(
        _load_schema("published-data.schema.json"), registry=_registry()
    )
    errors = list(validator.iter_errors(data.model_dump(mode="json")))
    assert errors == [], [e.message for e in errors]


def test_validate_published_data_count_mismatch():
    trend = _valid_trend()
    data = PublishedData(
        date="2026-07-24",
        schema_version="1.0",
        generated_at=_now(),
        pipeline_version="0.2.0",
        ai_enabled=False,
        categories={"ai_research": CategoryBlock(count=5, items=[trend])},  # count != len
        trends=[trend],
        events=[],
        metadata=PublishedMetadata(
            run_summary=RunSummary(sources_ok=1, sources_failed=0, total_dropped=0)
        ),
    )
    errs = validate_published_data(data)
    assert any("count" in e for e in errs)


# ---------------------------------------------------------------------------
# Anti-drift: Pydantic field names must match JSON Schema properties
# ---------------------------------------------------------------------------


def _schema_props(schema_file: str, defs_key: str | None = None) -> set[str]:
    s = _load_schema(schema_file)
    node = s["$defs"][defs_key] if defs_key else s
    return set(node.get("properties", {}).keys())


@pytest.mark.parametrize(
    "model_name,schema_file,defs_key",
    [
        ("Trend", "trend.schema.json", None),
        ("Event", "event.schema.json", None),
        ("EventSourceRef", "event.schema.json", "EventSourceRef"),
        ("SourcesConfig", "source.schema.json", None),
        ("SourceConfig", "source.schema.json", "Source"),
        ("HealthSnapshot", "health.schema.json", None),
        ("PublishedData", "published-data.schema.json", None),
        ("DateIndex", "index.schema.json", None),
        ("SourcesState", "sources-state.schema.json", None),
    ],
)
def test_pydantic_matches_json_schema_fields(model_name, schema_file, defs_key):
    model_cls = getattr(models_mod, model_name)
    schema_props = _schema_props(schema_file, defs_key)
    pydantic_fields = set(model_cls.model_fields.keys())
    assert schema_props == pydantic_fields, (
        f"{model_name}: schema={sorted(schema_props)} != pydantic={sorted(pydantic_fields)}"
    )
