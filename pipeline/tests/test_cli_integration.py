"""Offline integration tests for the CLI + Adapter Registry + Pipeline.

These tests verify the REAL integration wiring of:

    config/sources.yaml  ->  build_registry  ->  run_sources
        ->  run_pipeline  ->  validate_published_data  ->  publish_all

WITHOUT any real network call and WITHOUT writing ``data/2026``.

Every adapter here is a stub that returns canned ``RawItem`` objects, so
the links SourceConfig -> Registry -> Adapter -> Pipeline -> PublishedData
are exercised end-to-end while staying inside the project's network /
data-write discipline (Stage 1-4: no real API, no production data).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pipeline.__main__ import main
from pipeline.adapters.base import run_sources
from pipeline.adapters.registry import build_registry
from pipeline.core.config import (
    default_config_path,
    load_sources_config,
    project_root,
)
from pipeline.models import (
    LegalStatus,
    SourceConfig,
    SourcesConfig,
    SourceType,
)
from pipeline.pipeline import run_pipeline
from pipeline.raw import RawItem
from pipeline.validation import validate_published_data

# ---------------------------------------------------------------------------
# Stub fixtures (no network, no real data)
# ---------------------------------------------------------------------------


class _StubAdapter:
    """Minimal ``SourceAdapter`` returning canned ``RawItem`` (no network).

    Tracks ``calls`` so tests can assert the CLI ran exactly the sources it
    was told to. It intentionally mirrors only the attributes/methods the
    orchestrator touches: ``config``, ``source_id``, ``category``, ``fetch()``.
    """

    def __init__(self, config: SourceConfig, items: Optional[List[RawItem]] = None) -> None:
        self.config = config
        self.source_id = config.id
        self.category = config.category
        self.calls = 0
        self._items = items if items is not None else []

    def fetch(self) -> List[RawItem]:
        self.calls += 1
        return self._items


def _stub_config(source_id: str, category: str = "ai_research") -> SourceConfig:
    """A minimal but fully valid ``SourceConfig`` (enabled, public, example.com)."""
    return SourceConfig(
        id=source_id,
        name=f"Stub {source_id}",
        category=category,
        type=SourceType.API,
        enabled=True,
        priority=1,
        max_items=5,
        timeout=10,
        retry_count=0,
        rate_limit="1/1s",
        legal_status=LegalStatus.PUBLIC_PAGE,
        endpoint="https://example.com/feed",
        allowed_domains=["example.com"],
    )


def _stub_item(source_id: str, n: int, now: datetime) -> RawItem:
    """A valid ``RawItem`` (https, allowed domain, non-future published_at)."""
    return RawItem(
        source_id=source_id,
        source_name=f"Stub {source_id}",
        original_url=f"https://example.com/item{n}",
        title=f"Stub item {n}",
        source_item_id=f"i{n}",
        fetched_at=now,
        published_at=now - timedelta(hours=5),
        lang="en",
        summary=f"stub summary {n}",
    )


def _stub_sources_config(*cfgs: SourceConfig) -> SourcesConfig:
    return SourcesConfig(version=1, sources=list(cfgs))


# ---------------------------------------------------------------------------
# 1. Registry honors `enabled` (real sources.yaml)
# ---------------------------------------------------------------------------


def test_build_registry_only_instantiates_enabled_sources():
    """Only ``enabled: true`` sources are registered; disabled stay uninstantiated."""
    root = project_root()
    cfg = load_sources_config(default_config_path(root))
    registry = build_registry(cfg.sources)

    # arxiv + github are enabled=true; openai_blog must be absent.
    assert set(registry.keys()) == {"arxiv", "github"}
    for sid in ("openai_blog",):
        assert sid not in registry


# ---------------------------------------------------------------------------
# 2. Full offline chain: SourceConfig -> Adapter -> Pipeline -> PublishedData
# ---------------------------------------------------------------------------


def test_run_pipeline_offline_with_stub_adapter():
    """A stub adapter's RawItem[] flows through the whole pipeline offline."""
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    cfg = _stub_config("stub_src")
    items = [_stub_item("stub_src", i, now) for i in range(3)]
    adapter = _StubAdapter(cfg, items)

    results = run_sources([adapter], now)
    assert "stub_src" in results
    assert results["stub_src"].error is None
    assert results["stub_src"].health is not None
    assert results["stub_src"].health.status.value == "healthy"

    data, summary = run_pipeline(
        results, [cfg], now=now, batch_date="2026-07-24", ai_enabled=False
    )

    # The published data satisfies the production contract.
    errs = validate_published_data(data)
    assert errs == [], errs

    assert len(data.trends) == 3
    assert summary.sources_ok == 1
    assert summary.sources_failed == 0
    # Truth core preserved: real https url, never mock.
    for t in data.trends:
        assert t.original_url.startswith("https://example.com/")
        assert t.is_mock is False


# ---------------------------------------------------------------------------
# 3. CLI dry-run writes NOTHING (--no-write)
# ---------------------------------------------------------------------------


def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    cfg = _stub_config("stub_src")
    items = [_stub_item("stub_src", i, datetime.now(timezone.utc)) for i in range(2)]
    adapter = _StubAdapter(cfg, items)
    monkeypatch.setattr(
        "pipeline.__main__.load_sources_config",
        lambda *a, **k: _stub_sources_config(cfg),
    )
    monkeypatch.setattr(
        "pipeline.__main__.build_registry",
        lambda configs: {cfg.id: adapter},
    )

    rc = main(["--no-write", "--data-dir", str(tmp_path), "--date", "2026-07-24"])

    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().out
    # No production files anywhere under data_home.
    assert not (tmp_path / "index.json").exists()
    assert not (tmp_path / "health.json").exists()
    assert not (tmp_path / "sources_state.json").exists()
    assert not (tmp_path / "2026").exists()


# ---------------------------------------------------------------------------
# 4. CLI --dry-run is an alias for --no-write
# ---------------------------------------------------------------------------


def test_cli_dry_run_alias_writes_nothing(tmp_path, monkeypatch, capsys):
    cfg = _stub_config("stub_src")
    items = [_stub_item("stub_src", i, datetime.now(timezone.utc)) for i in range(2)]
    adapter = _StubAdapter(cfg, items)
    monkeypatch.setattr(
        "pipeline.__main__.load_sources_config",
        lambda *a, **k: _stub_sources_config(cfg),
    )
    monkeypatch.setattr(
        "pipeline.__main__.build_registry",
        lambda configs: {cfg.id: adapter},
    )

    rc = main(["--dry-run", "--data-dir", str(tmp_path), "--date", "2026-07-24"])

    assert rc == 0
    assert "[dry-run]" in capsys.readouterr().out
    assert not (tmp_path / "index.json").exists()
    assert not (tmp_path / "2026").exists()


# ---------------------------------------------------------------------------
# 5. CLI --source runs ONLY the selected source
# ---------------------------------------------------------------------------


def test_cli_source_filter_runs_only_selected(tmp_path, monkeypatch, capsys):
    cfg_a = _stub_config("src_a")
    cfg_b = _stub_config("src_b")
    adapter_a = _StubAdapter(cfg_a, [_stub_item("src_a", 1, datetime.now(timezone.utc))])
    adapter_b = _StubAdapter(cfg_b, [_stub_item("src_b", 1, datetime.now(timezone.utc))])
    registry = {cfg_a.id: adapter_a, cfg_b.id: adapter_b}
    monkeypatch.setattr(
        "pipeline.__main__.load_sources_config",
        lambda *a, **k: _stub_sources_config(cfg_a, cfg_b),
    )
    monkeypatch.setattr("pipeline.__main__.build_registry", lambda configs: registry)

    rc = main(
        ["--source", "src_a", "--no-write", "--data-dir", str(tmp_path), "--date", "2026-07-24"]
    )

    assert rc == 0
    assert adapter_a.calls == 1
    assert adapter_b.calls == 0  # the unselected source must NOT be fetched
    assert "sources=1" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 6. CLI --source on a disabled/missing source is a hard error (no fetch)
# ---------------------------------------------------------------------------


def test_cli_source_not_enabled_errors(tmp_path, monkeypatch, capsys):
    cfg = _stub_config("stub_src")
    adapter = _StubAdapter(cfg, [])
    # Registry deliberately does NOT contain "ghost" -- a disabled/missing source.
    monkeypatch.setattr(
        "pipeline.__main__.load_sources_config",
        lambda *a, **k: _stub_sources_config(cfg),
    )
    monkeypatch.setattr(
        "pipeline.__main__.build_registry",
        lambda configs: {cfg.id: adapter},
    )

    rc = main(["--source", "ghost", "--no-write", "--data-dir", str(tmp_path)])

    assert rc == 3
    assert "not enabled or not registered" in capsys.readouterr().err
    # The real adapter must NOT have been touched.
    assert adapter.calls == 0
