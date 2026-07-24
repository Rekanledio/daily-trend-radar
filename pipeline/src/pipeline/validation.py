"""Contract-level validation helpers (pure functions, no IO).

These enforce PROJECT_RULES production red lines that go *beyond* schema typing:
- production Trend must have ``is_mock=false``, ``original_url`` present, ``status=published``
- Event.source_count must equal len(sources) and trend_ids must match
- PublishedData category counts must equal their items length (and never exceed 20)

This is NOT the business pipeline; it is a thin guard used by tests and (later) the
publisher. It never performs network/API/AI calls.
"""

from __future__ import annotations

from .models import Event, PublishedData, Trend, TrendStatus


def validate_production_trend(trend: Trend) -> list[str]:
    """Return a list of violation messages; empty list means OK for production."""
    errors: list[str] = []
    if trend.is_mock:
        errors.append("is_mock must be false for production data")
    if not trend.original_url:
        errors.append("original_url is required for production data")
    if trend.status != TrendStatus.PUBLISHED:
        errors.append("production trend must have status=published")
    return errors


def validate_event(event: Event) -> list[str]:
    """Return a list of violation messages; empty list means OK."""
    errors: list[str] = []
    if event.source_count != len(event.sources):
        errors.append(
            f"event.source_count ({event.source_count}) != len(sources) ({len(event.sources)})"
        )
    if set(event.trend_ids) != {s.trend_id for s in event.sources}:
        errors.append("event.trend_ids must match sources[].trend_id set")
    return errors


def validate_published_data(data: PublishedData) -> list[str]:
    """Return a list of violation messages; empty list means OK."""
    errors: list[str] = []
    for category, block in data.categories.items():
        if block.count != len(block.items):
            errors.append(
                f"category '{category}': count ({block.count}) != items length ({len(block.items)})"
            )
        if len(block.items) > 20:
            errors.append(f"category '{category}': exceeds 20 items")
    return errors
