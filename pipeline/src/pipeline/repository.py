"""DataRepository abstract interface (Protocol).

Frontend and any future consumer MUST read data only through this interface,
never directly from JSON file paths. This keeps storage swappable
(``JsonFileRepository`` now, ``SupabaseRepository`` later) with zero UI changes.

Interface only -- NO implementation in this file (see PROJECT_RULES / v2).
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from .models import (
    DateIndex,
    Event,
    HealthSnapshot,
    PublishedData,
    SourcesState,
    Trend,
)


@runtime_checkable
class DataRepository(Protocol):
    """Unified read access to all published data."""

    def get_latest(self) -> Optional[PublishedData]:
        """Return the most recent PublishedData (by latest_date), or None."""
        ...

    def get_by_date(self, date: str) -> Optional[PublishedData]:
        """Return PublishedData for a specific YYYY-MM-DD, or None."""
        ...

    def get_history_index(self) -> DateIndex:
        """Return the global date index (index.json)."""
        ...

    def get_health(self) -> HealthSnapshot:
        """Return the data-source health snapshot (health.json)."""
        ...

    def get_sources_state(self) -> SourcesState:
        """Return runtime source states (sources_state.json)."""
        ...

    def get_by_category(self, category: str, date: Optional[str] = None) -> list[Trend]:
        """Return published trends of a category, optionally for a date."""
        ...

    def get_events(self, date: Optional[str] = None) -> list[Event]:
        """Return aggregated events, optionally for a date."""
        ...
