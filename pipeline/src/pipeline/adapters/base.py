"""Unified ``SourceAdapter`` contract + error-isolation helper.

Design boundary (Stage 1-2, per v2 section 2.2 step [1] and PROJECT_RULES
section five):

    A SourceAdapter is responsible for ONE thing only:
        pull the raw entries of a SINGLE data source -> list[RawItem]

It is NOT responsible for (and must not implement):
    - HotScore / scoring
    - Event aggregation / clustering
    - AI processing (summary / tags / classification)
    - Top-20 capping
    - PublishedData assembly
    - Any UI

Source-specific *parsing* (turning the source's raw response into RawItems)
lives inside the adapter's ``fetch()``. The GENERIC Normalize / Validate
/ SourceVerify / Dedup / Cluster / HotScore / Cap / Publish are shared
PIPELINE stages (see ``pipeline/stages.py``), NOT adapter methods.

This reconciles two earlier sketches:
    - PROJECT_RULES section five / PROJECT_PLAN section 12 named a
      ``BaseAdapter`` with ``fetch/parse/normalize/validate/health``.
    - The refined v2 + Stage 1-2 design narrows the adapter to
      ``fetch`` (+ source-specific ``parse`` inside it) and self-describing
      config (timeout/retry/rate_limit/enabled/legal_status). The generic
      ``normalize`` / ``validate`` named earlier map to the shared pipeline
      stages. This is a CLARIFICATION, not a conflict (v2 step [1]
      already says adapters "拉原始数据 -> RawItem[]").

No network / API / RSS is performed by anything in this file. ``safe_fetch``
only wraps a (possibly failing) adapter in try/except to honor the
single-source error-isolation rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from ..models import HealthStatus, SourceConfig, SourceHealth
from ..raw import RawItem


class AdapterError(Exception):
    """Raised by an adapter on an unrecoverable source failure.

    Adapters MAY raise this (or any exception) from ``fetch()``; the
    orchestrator isolates it via ``safe_fetch`` so one bad source never
    breaks the whole run.
    """


@runtime_checkable
class SourceAdapter(Protocol):
    """Contract every data source must satisfy.

    Implementations receive their ``SourceConfig`` (carrying id/name/
    category/type/enabled/priority/timeout/retry_count/rate_limit/
    legal_status/...) at construction and expose:
        - ``source_id``   (== config.id)
        - ``category``    (== config.category, target board)
        - ``config``      (the SourceConfig, for timeout/retry/rate_limit/etc.)
        - ``fetch()``     -> list[RawItem]  (pull + source-specific parse)
    """

    source_id: str
    category: str
    config: SourceConfig

    def fetch(self) -> list[RawItem]:
        """Pull this source's raw entries and parse them into RawItems.

        MUST raise (or return []) on failure -- never emit fake data.
        MUST attach a real ``original_url`` to every emitted RawItem.
        MUST NOT call AI, compute HotScore, or build Events.
        """
        ...


@dataclass
class AdapterResult:
    """Outcome of running one adapter, isolated from the run."""

    source_id: str
    items: list[RawItem] = field(default_factory=list)
    error: Optional[str] = None
    health: Optional[SourceHealth] = None


def safe_fetch(adapter: SourceAdapter, now: Optional[datetime] = None) -> AdapterResult:
    """Run one adapter inside a try/except (single-source error isolation).

    - Success with >=1 item  -> status ``healthy``.
    - Success with 0 items    -> status ``degraded`` (source responded but
      yielded nothing; v2 section 6.2).
    - Any exception           -> status ``failed``, items=[]; the error is
      captured in ``last_error`` and NEVER propagated to the caller.

    This function performs NO network IO itself; it only invokes the
    adapter's ``fetch()`` (which the caller supplied). Fully testable
    with stub adapters.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    source_id = adapter.source_id
    name = adapter.config.name
    category = adapter.category
    try:
        items = adapter.fetch()
    except Exception as exc:  # noqa: BLE001 -- isolation is the whole point
        return AdapterResult(
            source_id=source_id,
            items=[],
            error=str(exc),
            health=SourceHealth(
                source_id=source_id,
                name=name,
                category=category,
                status=HealthStatus.FAILED,
                last_attempt=now,
                last_error=str(exc),
                item_count=0,
                consecutive_failures=1,
            ),
        )
    status = HealthStatus.HEALTHY if items else HealthStatus.DEGRADED
    return AdapterResult(
        source_id=source_id,
        items=items,
        error=None,
        health=SourceHealth(
            source_id=source_id,
            name=name,
            category=category,
            status=status,
            last_success=now if items else None,
            last_attempt=now,
            last_error=None,
            item_count=len(items),
            consecutive_failures=0,
        ),
    )


def run_sources(adapters: list[SourceAdapter], now: Optional[datetime] = None
                ) -> dict[str, AdapterResult]:
    """Run every adapter, isolating failures, and keep going.

    Returns ``{source_id: AdapterResult}``. A failing source is recorded
    as ``failed`` and the other sources are NOT affected (v2 section 6.3
    isolation principle). No source exception escapes this function.
    """
    results: dict[str, AdapterResult] = {}
    for adapter in adapters:
        if not adapter.config.enabled:
            continue
        results[adapter.source_id] = safe_fetch(adapter, now)
    return results
