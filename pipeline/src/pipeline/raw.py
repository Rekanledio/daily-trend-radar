"""Raw / Normalized internal data models for the Daily Trend Radar pipeline.

These models describe the *pre-publish* boundary of the pipeline:

- ``RawItem``   -- the output of a single ``SourceAdapter.fetch()``.
                          It is the unfiltered, source-specific entry as returned
                          by one data source. It carries NO HotScore, NO ``event_id``,
                          NO ``status`` and is never a ``Trend``.
- ``NormalizedItem`` -- the output of the shared ``Normalize`` stage. Field names,
                          URL canonicalization, time format and text cleanup have been
                          applied. It still has no score and no ``event_id``; it only
                          becomes a ``Trend`` after the HotScore stage fills the score.

These are NEW models. The production ``Trend`` / ``Event`` models in
``models.py`` are NOT touched -- they remain the single source of truth for
*published* data and their JSON-Schema mirror is unchanged.

Everything here is pure data + typing. No IO, no network, no AI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import SummaryOrigin, TagsOrigin, TrendStatus

# ---------------------------------------------------------------------------
# RawItem -- what a SourceAdapter must return
# ---------------------------------------------------------------------------


class RawItem(BaseModel):
    """A single entry as fetched from ONE data source, before any pipeline processing.

    Red lines enforced by design (not by code elsewhere):
    - Must carry ``original_url`` (the truth core). An adapter that cannot
      provide a real URL must NOT emit the item.
    - Must NOT contain a HotScore, an ``event_id`` or an ``is_mock`` flag.
    - Must NOT contain AI-generated text. ``summary`` if present is the
      *raw, source-provided* text only.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str  # which adapter produced this (== SourceConfig.id)
    source_name: str  # display name snapshot at fetch time (denormalized)
    original_url: str  # REQUIRED, real & traceable (truth core)
    title: Optional[str] = None  # source-provided title, if any
    published_at: Optional[datetime] = None  # source-provided time, if any
    source_item_id: str  # stable id within this source's fetch (dedup aid)
    fetched_at: datetime  # when this item was pulled
    lang: str = "en"
    # Source-specific key/values (rank, stars, view count, raw snippet...).
    # Carried as-is; never reinterpreted as a fact by the pipeline.
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Raw, source-provided summary (e.g. RSS description). NEVER AI text.
    summary: Optional[str] = None

    def as_normalized(self, category: str) -> "NormalizedItem":
        """Convenience bridge used by the Normalize stage.

        Carries the raw fields into a ``NormalizedItem`` for the given target
        ``category`` (taken from the source config). No facts are invented;
        scores and ``event_id`` are intentionally left unset.
        """
        return NormalizedItem(
            source_id=self.source_id,
            source_name=self.source_name,
            category=category,
            title=self.title if self.title is not None else "",
            original_url=self.original_url,
            published_at=self.published_at,
            collected_at=self.fetched_at,
            updated_at=self.fetched_at,
            lang=self.lang,
            summary=self.summary,
        )


# ---------------------------------------------------------------------------
# NormalizedItem -- output of the shared Normalize stage
# ---------------------------------------------------------------------------


class NormalizedItem(BaseModel):
    """A ``RawItem`` after field unification, URL canonicalization, time
    normalization and text cleanup. Still pre-score, pre-cluster.

    It mirrors the eventual ``Trend`` minus the scoring/aggregation fields:
    - no ``hot_score`` / ``score_breakdown`` (filled by HotScore stage)
    - no ``event_id`` (assigned by the Event Aggregation stage)
    - ``status`` is always ``draft`` at this boundary
    - ``is_mock`` is always ``False`` (raw data is never mock)
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_name: str
    category: str  # mapped from the source config during Normalize
    title: str  # cleaned; may be empty string -> will fail Validation
    original_url: str
    canonical_url: Optional[str] = None  # set by Normalize (URL canon)
    summary: Optional[str] = None
    summary_origin: SummaryOrigin = SummaryOrigin.ORIGINAL
    author: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    tags_origin: TagsOrigin = TagsOrigin.NONE
    published_at: Optional[datetime] = None
    collected_at: datetime  # == fetched_at
    updated_at: datetime
    heat_raw: Optional[dict[str, Any]] = None  # raw platform heat snapshot
    rank_in_source: Optional[int] = Field(default=None, ge=1)
    lang: str = "en"
    is_mock: bool = False
    event_id: Optional[str] = None  # assigned later by Cluster stage
    status: TrendStatus = TrendStatus.DRAFT
