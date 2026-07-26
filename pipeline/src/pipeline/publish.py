"""Production file publisher (Stage 1-4A).

Concrete writer for the static-data architecture:

    data/YYYY/MM/YYYY-MM-DD.json   (the daily shard -- date-sharded)
    data/index.json                  (DateIndex pointer; UPDATED, never replaced wholesale)
    data/health.json                (HealthSnapshot)
    data/sources_state.json         (SourcesState)

NO ``latest.json`` is ever written -- the frontend reads ``index.json``
as the pointer (PROJECT_RULES / v2 section 9).

This is the concrete implementation of the interface-only repository in
``repository.py``. We deliberately do NOT modify that file; new file
IO belongs here.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta
from typing import Dict, List

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .adapters.base import AdapterResult
from .models import (
    DateIndex,
    DateIndexEntry,
    HealthSnapshot,
    HealthStatus,
    PublishedData,
    SourceConfig,
    SourceHealth,
    SourceRuntimeState,
    SourcesState,
)
from .validation import validate_published_data


# project_root located robustly (holds schemas/ + config/); not a fixed
# parent index, so it works under both ``python -m`` and ``sys.path``.
def _find_project_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in [here, *here.parents]:
        if (cand / "schemas").is_dir() and (cand / "config").is_dir():
            return cand
    return here.parents[4]


_PROJECT_ROOT = _find_project_root()
SCHEMA_DIR = _PROJECT_ROOT / "schemas"
DEFAULT_DATA_HOME = _PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# JSON-Schema contract gate (refuse to publish on failure)
# ---------------------------------------------------------------------------


def _schema_registry(schema_dir: pathlib.Path) -> Registry:
    resources: Dict[str, Resource] = {}
    for f in schema_dir.glob("*.schema.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        resources[s["$id"]] = Resource.from_contents(s)
    return Registry().with_resources(resources.items())


def validate_published_data_schema(data: PublishedData) -> List[str]:
    """Validate a ``PublishedData`` against its JSON Schema.

    Mirrors the offline contract test (``test_contracts.py``): loads every
    schema into a shared registry so ``$ref`` resolution works, then runs
    the 2020-12 validator against the produced document.
    """
    schema = json.loads((SCHEMA_DIR / "published-data.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_schema_registry(SCHEMA_DIR))
    return [e.message for e in validator.iter_errors(data.model_dump(mode="json"))]


# ---------------------------------------------------------------------------
# Shard + index + health + sources_state writers
# ---------------------------------------------------------------------------


def write_daily_shard(data_home: pathlib.Path, data: PublishedData) -> pathlib.Path:
    """Write the date-sharded daily file ``data/YYYY/MM/YYYY-MM-DD.json``."""
    y, m, _ = data.date.split("-")
    shard = data_home / y / m / f"{data.date}.json"
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    return shard


def update_index(data_home: pathlib.Path, data: PublishedData) -> DateIndex:
    """Update ``data/index.json`` as a pointer (never a single latest file)."""
    idx_path = data_home / "index.json"
    if idx_path.exists():
        idx = DateIndex.model_validate(json.loads(idx_path.read_text(encoding="utf-8")))
    else:
        idx = DateIndex(schema_version="1.0")

    cat_counts = {cat: len(block.items) for cat, block in data.categories.items()}
    entry = DateIndexEntry(
        path=f"{data.date[:4]}/{data.date[5:7]}/{data.date}.json",
        total_items=len(data.trends),
        categories=cat_counts,
    )
    idx.date_index[data.date] = entry

    dates = sorted(set(idx.available_dates) | {data.date})
    # Keep only the last 7 days (today + 6 prior) so the date-picker
    # in the frontend stays usable.  Older dates remain in date_index
    # for backward-looking queries, but are removed from the quick-pick list.
    today = datetime.strptime(data.date, "%Y-%m-%d").date()
    cutoff = (today - timedelta(days=6)).isoformat()
    dates = [d for d in dates if d >= cutoff]
    idx.available_dates = dates
    idx.latest_date = dates[-1]
    idx.categories = sorted(set(idx.categories) | set(data.categories.keys()))
    idx.updated_at = data.generated_at

    idx_path.write_text(idx.model_dump_json(indent=2), encoding="utf-8")
    return idx


def write_health(
    data_home: pathlib.Path,
    results: Dict[str, AdapterResult],
    configs: List[SourceConfig],
    now: datetime,
) -> HealthSnapshot:
    """Write ``data/health.json`` from adapter results."""
    healths: List[SourceHealth] = []
    statuses: List[str] = []
    for cfg in configs:
        res = results.get(cfg.id)
        if res is not None and res.health is not None:
            healths.append(res.health)
            statuses.append(res.health.status.value)
        else:
            # Configured but not attempted this run (e.g. disabled).
            healths.append(
                SourceHealth(
                    source_id=cfg.id,
                    name=cfg.name,
                    category=cfg.category,
                    status=HealthStatus.DISABLED,
                    last_attempt=None,
                )
            )
    if not statuses:
        overall = None
    elif all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif all(s == "failed" for s in statuses):
        overall = "failed"
    else:
        overall = "degraded"
    snap = HealthSnapshot(
        schema_version="1.0",
        generated_at=now,
        overall=overall,
        sources=healths,
    )
    (data_home / "health.json").write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    return snap


def write_sources_state(
    data_home: pathlib.Path,
    results: Dict[str, AdapterResult],
    configs: List[SourceConfig],
    now: datetime,
) -> SourcesState:
    """Write ``data/sources_state.json`` (runtime state, separate from config)."""
    states: List[SourceRuntimeState] = []
    for cfg in configs:
        res = results.get(cfg.id)
        h = res.health if res is not None else None
        status = h.status if h is not None else HealthStatus.DISABLED
        states.append(
            SourceRuntimeState(
                source_id=cfg.id,
                name=cfg.name,
                category=cfg.category,
                enabled=cfg.enabled,
                status=status,
                last_success=h.last_success if h is not None else None,
                last_attempt=h.last_attempt if h is not None else None,
                last_error=h.last_error if h is not None else None,
                item_count=h.item_count if h is not None else 0,
                response_time_ms=h.response_time_ms if h is not None else None,
                consecutive_failures=h.consecutive_failures if h is not None else 0,
                success_rate_7d=h.success_rate_7d if h is not None else None,
            )
        )
    st = SourcesState(schema_version="1.0", updated_at=now, sources=states)
    (data_home / "sources_state.json").write_text(st.model_dump_json(indent=2), encoding="utf-8")
    return st


# ---------------------------------------------------------------------------
# Publish orchestration (the contract gate runs first)
# ---------------------------------------------------------------------------


def publish_all(
    data: PublishedData,
    results: Dict[str, AdapterResult],
    configs: List[SourceConfig],
    now: datetime,
    data_home: pathlib.Path = DEFAULT_DATA_HOME,
) -> Dict[str, pathlib.Path]:
    """Validate, then write the daily shard + index/health/sources_state.

    Raises ``ValueError`` (and writes NOTHING) if either contract gate
    fails: the model-level ``validate_published_data`` or the JSON-Schema
    ``validate_published_data_schema``.
    """
    errs = validate_published_data(data) + validate_published_data_schema(data)
    if errs:
        raise ValueError("PublishedData contract invalid: " + "; ".join(errs))

    data_home = pathlib.Path(data_home)
    data_home.mkdir(parents=True, exist_ok=True)

    shard = write_daily_shard(data_home, data)
    update_index(data_home, data)
    write_health(data_home, results, configs, now)
    write_sources_state(data_home, results, configs, now)
    return {
        "shard": shard,
        "index": data_home / "index.json",
        "health": data_home / "health.json",
        "sources_state": data_home / "sources_state.json",
    }
