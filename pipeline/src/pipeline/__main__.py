"""CLI entry point: ``python -m pipeline``.

Runs the full ArXiv single-source pipeline end-to-end and writes the
production shard + index/health/sources_state. This is a LOCAL runner
only:

    - NO scheduler, NO GitHub Actions, NO Cron, NO deploy.
    - AI is DISABLED this round (``ai_enabled=False``); the
      ``NullAIProcessor`` passthrough is used.

Usage (from the ``pipeline/`` package root, where ``src/`` sits)::

    PYTHONPATH=src python -m pipeline
    PYTHONPATH=src python -m pipeline --date 2026-07-24
    PYTHONPATH=src python -m pipeline --config /path/sources.yaml --data-dir /path/data
    PYTHONPATH=src python -m pipeline --no-write     # dry-run, no files
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from datetime import datetime, timezone

from .adapters.base import run_sources
from .adapters.registry import build_registry
from .core.config import default_config_path, load_sources_config, project_root
from .pipeline import run_pipeline
from .publish import publish_all
from .validation import validate_published_data


def _project_root() -> pathlib.Path:
    return project_root()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Daily Trend Radar -- ArXiv single-source pipeline runner",
    )
    parser.add_argument("--config", type=str, default=None, help="path to config/sources.yaml")
    parser.add_argument("--data-dir", type=str, default=None, help="path to the data/ directory")
    parser.add_argument(
        "--date", type=str, default=None, help="batch date YYYY-MM-DD (default today, UTC)"
    )
    parser.add_argument(
        "--no-write", action="store_true", help="run pipeline without writing files (dry-run)"
    )
    args = parser.parse_args(argv)

    root = _project_root()
    config_path = pathlib.Path(args.config) if args.config else default_config_path(root)
    data_home = pathlib.Path(args.data_dir) if args.data_dir else (root / "data")

    config = load_sources_config(config_path)
    registry = build_registry(config.sources)

    now = datetime.now(timezone.utc)
    batch_date = args.date or now.strftime("%Y-%m-%d")

    # 1. Collect (single-source failure isolation built into run_sources).
    results = run_sources(list(registry.values()), now)

    # 2. Run the pipeline (AI disabled this round).
    data, summary = run_pipeline(
        results,
        config.sources,
        now=now,
        batch_date=batch_date,
        ai_enabled=False,
    )

    # 3. Local contract gate (mirrors the publisher's; refuse on failure).
    errs = validate_published_data(data)
    if errs:
        for e in errs:
            print(f"[ERROR] published_data: {e}", file=sys.stderr)
        print("Refusing to publish: local contract validation failed.", file=sys.stderr)
        return 2

    if args.no_write:
        print(
            f"[dry-run] batch={batch_date} trends={len(data.trends)} "
            f"events={len(data.events)} ok={summary.sources_ok} "
            f"failed={summary.sources_failed} dropped={summary.total_dropped}"
        )
        return 0

    paths = publish_all(data, results, config.sources, now, data_home=data_home)
    print(f"[ok] wrote {paths['shard']}")
    print(
        f"     date={batch_date} ai_enabled={data.ai_enabled} "
        f"trends={len(data.trends)} events={len(data.events)} "
        f"sources_ok={summary.sources_ok} sources_failed={summary.sources_failed} "
        f"dropped={summary.total_dropped}"
    )
    print(f"     pipeline_version={data.pipeline_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
