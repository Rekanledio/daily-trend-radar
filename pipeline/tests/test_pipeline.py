"""Offline integration tests for the ArXiv single-source pipeline (Stage 1-4A).

NO real network, NO real API, NO real data, NO AI. Every test is
fully offline -- either injecting ``AdapterResult``s directly into
``run_pipeline`` or driving the REAL ``ArxivAdapter`` with a stub
``urlopen``.

These tests pin the authoritative 14-step order and the production
red lines:
  - SourceVerify drops suffix-forgery URLs (arxiv.org.evil.com).
  - Dedup collapses same source + same canonical URL.
  - Cluster is conservative (distinct URLs => independent Events).
  - ArXiv has NO platform heat => the ``heat`` dimension is 0 (never fabricated).
  - Cap is <=20 per category and runs BEFORE any AI effect.
  - AI disabled => trends unchanged (NullAIProcessor passthrough).
  - PublishedData passes BOTH the model validator and the JSON Schema.
  - The publisher writes the date shard + index/health/sources_state,
    and NEVER writes a ``latest.json`` file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pipeline import publish_all, run_pipeline, validate_published_data_schema
from pipeline.adapters.arxiv import ArxivAdapter, _Response
from pipeline.adapters.base import AdapterResult, run_sources
from pipeline.adapters.github import GitHubAdapter
from pipeline.adapters.registry import build_adapter, build_registry
from pipeline.core.config import default_config_path, load_categories, load_sources_config
from pipeline.models import (
    HealthStatus,
    LegalStatus,
    SourceConfig,
    SourceHealth,
    SourceType,
)
from pipeline.pipeline import _score_item
from pipeline.raw import RawItem
from pipeline.stages import validate_pipeline_item
from pipeline.validation import validate_published_data

NOW = datetime(2026, 7, 24, 9, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arxiv_config(**over) -> SourceConfig:
    base = dict(
        id="arxiv",
        name="arXiv",
        category="ai_research",
        type=SourceType.API,
        enabled=True,
        priority=1,
        max_items=20,
        timeout=20,
        retry_count=2,
        rate_limit="1/3s",
        legal_status=LegalStatus.OFFICIAL_API,
        terms_url="https://arxiv.org/help/api/tou",
        endpoint="http://export.arxiv.org/api/query",
        query="cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
        allowed_domains=["arxiv.org"],
    )
    base.update(over)
    return SourceConfig(**base)


def _raw(url: str, title: str = "T", published_at: datetime = NOW, sid: str = "arxiv") -> RawItem:
    aid = url.rstrip("/").split("/")[-1]
    return RawItem(
        source_id=sid,
        source_name="arXiv",
        original_url=url,
        title=title,
        published_at=published_at,
        source_item_id=aid,
        fetched_at=NOW,
        lang="en",
        summary=f"summary {aid}",
    )


def _healthy_result(items, sid: str = "arxiv") -> AdapterResult:
    return AdapterResult(
        source_id=sid,
        items=items,
        error=None,
        health=SourceHealth(
            source_id=sid,
            name="arXiv",
            category="ai_research",
            status=HealthStatus.HEALTHY,
            last_success=NOW,
            last_attempt=NOW,
            item_count=len(items),
            consecutive_failures=0,
        ),
    )


# ---------------------------------------------------------------------------
# Config + Registry (no hardcoded source branching)
# ---------------------------------------------------------------------------


def test_config_loads_real_sources_yaml():
    cfg = load_sources_config(default_config_path())
    arx = next(s for s in cfg.sources if s.id == "arxiv")
    assert arx.enabled is True
    assert arx.category == "ai_research"
    assert arx.allowed_domains == ["arxiv.org"]


def test_load_categories_includes_ai_research():
    cfg = load_sources_config(default_config_path())
    assert "ai_research" in load_categories(cfg)


def test_registry_only_registers_enabled_sources():
    cfg = load_sources_config(default_config_path())
    reg = build_registry(cfg.sources)
    # arxiv + github are enabled in the real config.
    assert set(reg.keys()) == {"arxiv", "github"}
    assert isinstance(reg["arxiv"], ArxivAdapter)
    assert isinstance(reg["github"], GitHubAdapter)


def test_registry_unknown_source_raises():
    with pytest.raises(ValueError):
        build_adapter(_arxiv_config(id="nope"))


def test_arxiv_adapter_is_registered_class():
    # The orchestrator relies on the registry map, NOT `if source_id == 'arxiv'`.
    from pipeline.adapters.registry import _ADAPTER_REGISTRY

    assert _ADAPTER_REGISTRY.get("arxiv") is ArxivAdapter


# ---------------------------------------------------------------------------
# Pipeline stages (inject AdapterResults directly)
# ---------------------------------------------------------------------------


def test_normalize_sets_canonical_url_and_category():
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    t = data.trends[0]
    assert t.canonical_url == "https://arxiv.org/abs/2401.00001"
    assert t.category == "ai_research"


def test_validate_drops_empty_title():
    items = [_raw("https://arxiv.org/abs/2401.00001", title="")]
    res = _healthy_result(items)
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert data.trends == []
    assert summ.total_dropped == 1


def test_validate_drops_unknown_category():
    # Red line: a normalized item whose category is NOT in the configured
    # set is dropped at the Validate stage.
    from pipeline.models import SummaryOrigin, TagsOrigin
    from pipeline.raw import NormalizedItem

    bad = NormalizedItem(
        source_id="arxiv",
        source_name="arXiv",
        category="not_a_real_category",
        title="X",
        original_url="https://arxiv.org/abs/2401.00001",
        collected_at=NOW,
        updated_at=NOW,
        summary_origin=SummaryOrigin.ORIGINAL,
        tags_origin=TagsOrigin.NONE,
    )
    errs = validate_pipeline_item(bad, {"ai_research"}, now=NOW)
    assert any("category" in e for e in errs)


def test_source_verify_drops_suffix_forgery():
    items = [
        _raw("https://arxiv.org/abs/2401.00001"),
        _raw("https://arxiv.org.evil.com/abs/x", sid="arxiv"),
    ]
    res = _healthy_result(items)
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    urls = {t.original_url for t in data.trends}
    assert "https://arxiv.org/abs/2401.00001" in urls
    assert "https://arxiv.org.evil.com/abs/x" not in urls
    assert summ.total_dropped == 1


def test_source_verify_keeps_good_domain():
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert len(data.trends) == 1


def test_dedup_same_canonical_url():
    items = [
        _raw("https://arxiv.org/abs/2401.00001", title="A"),
        _raw("https://arxiv.org/abs/2401.00001", title="A DUPLICATE"),
    ]
    res = _healthy_result(items)
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert len(data.trends) == 1
    assert summ.total_dropped == 1


def test_dedup_keeps_different_urls():
    items = [
        _raw("https://arxiv.org/abs/2401.00001", title="A"),
        _raw("https://arxiv.org/abs/2401.00002", title="B"),
    ]
    res = _healthy_result(items)
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert len(data.trends) == 2
    assert summ.total_dropped == 0


def test_cluster_conservative_one_event_per_item():
    items = [
        _raw("https://arxiv.org/abs/2401.00001"),
        _raw("https://arxiv.org/abs/2401.00002"),
        _raw("https://arxiv.org/abs/2401.00003"),
    ]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    # Distinct canonical URLs => each Trend is its own Event (under-aggregation).
    assert len(data.events) == len(data.trends) == 3
    for ev in data.events:
        assert ev.source_count == 1


def test_hot_score_heat_is_zero_no_fabrication():
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    for t in data.trends:
        assert t.score_breakdown.heat == 0.0
        assert 0.0 <= t.hot_score <= 100.0


def test_hot_score_formula_matches_expected():
    cfg = _arxiv_config(priority=1)
    item = _raw("https://arxiv.org/abs/2401.00001")
    bd = _score_item(item, cfg, source_count=1, now=NOW)
    # authority 90 (priority 1), heat 0, freshness 100 (published==now),
    # multi_source 33.33 (1/3 * 100), platform 80 (official_api).
    assert bd.authority == 90.0
    assert bd.heat == 0.0
    assert bd.freshness == 100.0
    assert bd.multi_source == pytest.approx(33.33, abs=0.1)
    assert bd.platform == 80.0


def test_freshness_decays_with_age():
    old = NOW - timedelta(days=7)
    recent = _raw("https://arxiv.org/abs/2401.00001", published_at=NOW)
    aged = _raw("https://arxiv.org/abs/2401.99999", published_at=old)
    cfg = _arxiv_config()
    bd_recent = _score_item(recent, cfg, 1, NOW)
    bd_aged = _score_item(aged, cfg, 1, NOW)
    assert bd_recent.freshness > bd_aged.freshness


def test_multi_source_dim_single_source():
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    # 1 distinct source in the event => min(1, 1/3)*100 = 33.33.
    assert data.trends[0].score_breakdown.multi_source == pytest.approx(33.33, abs=0.1)


def test_rank_and_cap_orders_desc_and_caps():
    # Inject 25 items; the pipeline cap is always <=20 per category regardless
    # of the source's max_items (which is itself capped at 20 by contract).
    items = [_raw(f"https://arxiv.org/abs/2401.{i:05d}", title=f"P{i}") for i in range(25)]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    # Single category => capped at 20, sorted by hot_score descending.
    assert len(data.trends) == 20
    scores = [t.hot_score for t in data.trends]
    assert scores == sorted(scores, reverse=True)


def test_ai_disabled_passthrough_untouched():
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    t = data.trends[0]
    # No AI ran: summary_origin stays 'original', status published, no fabrications.
    assert t.summary_origin.value == "original"
    assert t.status.value == "published"
    assert data.ai_enabled is False


def test_published_data_structure_and_counts():
    items = [_raw("https://arxiv.org/abs/2401.00001"), _raw("https://arxiv.org/abs/2401.00002")]
    res = _healthy_result(items)
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert data.date == "2026-07-24"
    assert data.ai_enabled is False
    assert data.pipeline_version
    # categories count must equal items length.
    for block in data.categories.values():
        assert block.count == len(block.items)
    # flat trends == union of category items.
    flat = [t for b in data.categories.values() for t in b.items]
    assert len(flat) == len(data.trends)


def test_published_data_passes_json_schema():
    items = [_raw("https://arxiv.org/abs/2401.00001"), _raw("https://arxiv.org/abs/2401.00002")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert validate_published_data(data) == []
    assert validate_published_data_schema(data) == []


def test_date_label_distinct_from_published_at():
    pub = NOW - timedelta(days=2)
    items = [_raw("https://arxiv.org/abs/2401.00001", published_at=pub)]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert data.date == "2026-07-24"  # batch date
    assert data.trends[0].published_at == pub  # real source time preserved


def test_failed_source_isolated_no_crash():
    class _Boom:
        source_id = "arxiv"
        category = "ai_research"
        config = _arxiv_config()

        def fetch(self):
            raise RuntimeError("boom")

    results = run_sources([_Boom()], now=NOW)
    assert results["arxiv"].error is not None
    assert results["arxiv"].health.status.value == "failed"
    # Pipeline still runs and yields an empty (but valid) PublishedData.
    data, summ = run_pipeline(results, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert data.trends == []
    assert summ.sources_failed == 1


def test_empty_run_degraded_but_valid():
    res = _healthy_result([], sid="arxiv")  # 0 items => degraded
    res.health.status = HealthStatus.DEGRADED
    data, summ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    assert data.trends == []
    assert validate_published_data(data) == []


# ---------------------------------------------------------------------------
# Real ArxivAdapter driven by a stub urlopen (still fully offline)
# ---------------------------------------------------------------------------


def _atom(entry_ids):
    entries = "".join(
        f'<entry><id>http://arxiv.org/abs/{i}</id>'
        f"<title>Paper {i}</title>"
        f"<summary>abstract {i}</summary>"
        f"<published>2026-07-24T09:00:00Z</published>"
        f"<updated>2026-07-24T09:00:00Z</updated>"
        f"<author><name>Author {i}</name></author>"
        f'<category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>'
        f'<primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>'
        f"</entry>"
        for i in entry_ids
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + "</feed>"
    ).encode()


class _StubUrlopen:
    def __init__(self, pages):
        self._pages = list(pages)
        self.calls = 0

    def __call__(self, url, timeout):
        idx = min(self.calls, len(self._pages) - 1)
        self.calls += 1
        return _Response(self._pages[idx])


def test_real_adapter_full_pipeline_via_stub_pagination():
    # Two pages of 2 entries each; max_items=3 -> pagination then cap at 3.
    pages = [_atom(["1", "2"]), _atom(["3", "4"])]
    adapter = ArxivAdapter(
        _arxiv_config(max_items=3),
        urlopen=_StubUrlopen(pages),
        now_provider=lambda: NOW,
    )
    results = run_sources([adapter], now=NOW)
    assert results["arxiv"].error is None
    cfg = _arxiv_config(max_items=3)
    data, summ = run_pipeline(results, [cfg], now=NOW, batch_date="2026-07-24")
    assert len(data.trends) == 3
    assert summ.sources_ok == 1
    assert all(t.original_url.startswith("https://arxiv.org/abs/") for t in data.trends)
    assert all(t.score_breakdown.heat == 0.0 for t in data.trends)


def test_real_adapter_emits_clean_url_and_title():
    adapter = ArxivAdapter(
        _arxiv_config(),
        urlopen=_StubUrlopen([_atom(["42"])]),
        now_provider=lambda: NOW,
    )
    results = run_sources([adapter], now=NOW)
    data, _ = run_pipeline(results, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    t = data.trends[0]
    assert t.original_url == "https://arxiv.org/abs/42"
    assert t.title == "Paper 42"
    assert t.summary_origin.value == "original"


# ---------------------------------------------------------------------------
# Publisher (filesystem, isolated via tmp_path)
# ---------------------------------------------------------------------------


def test_publisher_writes_shard_index_health_state(tmp_path):
    items = [_raw("https://arxiv.org/abs/2401.00001"), _raw("https://arxiv.org/abs/2401.00002")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    paths = publish_all(data, {"arxiv": res}, [_arxiv_config()], NOW, data_home=tmp_path)
    shard = paths["shard"]
    assert shard.exists()
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "health.json").exists()
    assert (tmp_path / "sources_state.json").exists()
    # Red line: NO latest.json file is ever written.
    assert not (tmp_path / "latest.json").exists()


def test_publisher_index_pointer_shape(tmp_path):
    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    publish_all(data, {"arxiv": res}, [_arxiv_config()], NOW, data_home=tmp_path)
    import json

    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["latest_date"] == "2026-07-24"
    assert "2026-07-24" in idx["available_dates"]
    entry = idx["date_index"]["2026-07-24"]
    assert entry["total_items"] == 1
    assert entry["path"] == "2026/07/2026-07-24.json"
    assert "ai_research" in idx["categories"]


def test_publisher_index_accumulates(tmp_path):
    import json

    for d in ("2026-07-23", "2026-07-24"):
        items = [_raw("https://arxiv.org/abs/2401.00001")]
        res = _healthy_result(items)
        data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date=d)
        publish_all(data, {"arxiv": res}, [_arxiv_config()], NOW, data_home=tmp_path)
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["latest_date"] == "2026-07-24"
    assert set(idx["available_dates"]) == {"2026-07-23", "2026-07-24"}


def test_publisher_health_shape(tmp_path):
    import json

    items = [_raw("https://arxiv.org/abs/2401.00001")]
    res = _healthy_result(items)
    data, _ = run_pipeline({"arxiv": res}, [_arxiv_config()], now=NOW, batch_date="2026-07-24")
    publish_all(data, {"arxiv": res}, [_arxiv_config()], NOW, data_home=tmp_path)
    h = json.loads((tmp_path / "health.json").read_text())
    assert h["overall"] == "healthy"
    assert h["sources"][0]["source_id"] == "arxiv"
    assert h["sources"][0]["status"] == "healthy"


def test_publisher_contract_gate_refuses_invalid(tmp_path):

    from pipeline.models import (
        CategoryBlock,
        PublishedData,
        PublishedMetadata,
        RunSummary,
    )

    # Build an INVALID PublishedData: category count != items length.
    bad = PublishedData(
        date="2026-07-24",
        schema_version="1.0",
        generated_at=NOW,
        pipeline_version="0.2.0",
        ai_enabled=False,
        categories={"ai_research": CategoryBlock(count=5, items=[])},  # count mismtch
        trends=[],
        events=[],
        metadata=PublishedMetadata(
            run_summary=RunSummary(sources_ok=1, sources_failed=0, total_dropped=0)
        ),
    )
    with pytest.raises(ValueError):
        publish_all(bad, {}, [_arxiv_config()], NOW, data_home=tmp_path)
    # And the shard must NOT have been written.
    assert not (tmp_path / "2026" / "07" / "2026-07-24.json").exists()


def test_cli_dry_run_no_files(tmp_path, monkeypatch):
    # Exercise __main__.main in dry-run mode (no real network: monkeypatch the
    # registry build to return a stub adapter).
    import pipeline.__main__ as m
    from pipeline.adapters.arxiv import ArxivAdapter

    class _Stub(ArxivAdapter):
        def fetch(self):
            return [_raw("https://arxiv.org/abs/2401.00001")]

    monkeypatch.setattr(m, "build_registry", lambda configs: {"arxiv": _Stub(_arxiv_config())})
    rc = m.main(["--date", "2026-07-24", "--data-dir", str(tmp_path), "--no-write"])
    assert rc == 0
    assert not (tmp_path / "2026").exists()
