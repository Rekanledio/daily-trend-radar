"""Core data contracts for Daily Trend Radar (Pydantic models).

Single Python source of truth that mirrors ``schemas/*.schema.json``.
These are pure data models -- no IO, no network, no business pipeline logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


def _iso_utc(value: datetime) -> str:
    """Serialize a datetime to ISO 8601 UTC with a trailing 'Z'."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Enumerations (shared across Trend / Event / Source / Health)
# ---------------------------------------------------------------------------


class TrendStatus(str, Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    PUBLISHED = "published"
    REJECTED = "rejected"


class SummaryOrigin(str, Enum):
    ORIGINAL = "original"
    AI = "ai"
    NONE = "none"


class TagsOrigin(str, Enum):
    RULE = "rule"
    AI = "ai"
    NONE = "none"


class SourceType(str, Enum):
    API = "api"
    RSS = "rss"
    PAGE = "page"


class LegalStatus(str, Enum):
    OFFICIAL_API = "official_api"
    OFFICIAL_RSS = "official_rss"
    PUBLIC_PAGE = "public_page"
    THIRD_PARTY_LEGAL = "third_party_legal"
    MANUAL = "manual"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Reusable fragments
# ---------------------------------------------------------------------------


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: float = Field(..., ge=0, le=100)
    heat: float = Field(..., ge=0, le=100)
    freshness: float = Field(..., ge=0, le=100)
    multi_source: float = Field(..., ge=0, le=100)
    platform: float = Field(..., ge=0, le=100)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


class Trend(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    id: str
    event_id: Optional[str] = None
    source_id: str
    source_name: str
    category: str
    title: str
    summary: Optional[str] = None
    summary_origin: SummaryOrigin
    original_url: str
    canonical_url: Optional[str] = None
    author: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    tags_origin: TagsOrigin
    published_at: Optional[datetime] = None
    collected_at: datetime
    updated_at: datetime
    heat_raw: Optional[dict[str, Any]] = None
    hot_score: float = Field(..., ge=0, le=100)
    score_breakdown: ScoreBreakdown
    rank_in_source: Optional[int] = Field(default=None, ge=1)
    status: TrendStatus
    lang: str = "en"
    is_mock: bool = False


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class EventSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    source_id: str
    source_name: str
    trend_id: str
    original_url: str
    title: str
    hot_score: float = Field(..., ge=0, le=100)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    event_id: str
    title: str
    summary: Optional[str] = None
    category: str
    sources: list[EventSourceRef]
    source_count: int = Field(..., ge=0)
    trend_ids: list[str]
    hot_score: float = Field(..., ge=0, le=100)
    score_breakdown: ScoreBreakdown
    published_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Source config (config/sources.yaml)
# ---------------------------------------------------------------------------


class SourceDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout: Optional[int] = Field(default=None, ge=1)
    retry_count: Optional[int] = Field(default=None, ge=0)
    rate_limit: Optional[str] = None
    max_items: Optional[int] = Field(default=None, ge=1, le=20)


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    id: str = Field(..., pattern=r"^[a-z0-9_]+$")
    name: str
    category: str
    type: SourceType
    enabled: bool
    priority: int = Field(..., ge=1)
    max_items: int = Field(..., ge=1, le=20)
    timeout: int = Field(..., ge=1)
    retry_count: int = Field(..., ge=0)
    rate_limit: str
    legal_status: LegalStatus
    terms_url: Optional[str] = None
    endpoint: Optional[str] = None
    query: Optional[str] = None
    fallback: Optional[str] = None
    notes: Optional[str] = None
    # Domains this source is ALLOWED to publish ``original_url`` on.
    # Consumed by the SourceVerify stage (``verify_original_url``). A SET
    # (not a single domain) because a real source may serve from several
    # official hosts. ``None`` => no per-source domain check (not
    # recommended for a real source). Added when the first real source
    # (ArXiv, Stage 1-3A) was connected -- see PIPELINE_DESIGN.md
    # section 17 Q2 (the schema change was deliberately deferred there
    # until a real source needed it).
    allowed_domains: Optional[list[str]] = None


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(..., ge=1)
    defaults: Optional[SourceDefaults] = None
    sources: list[SourceConfig]


# ---------------------------------------------------------------------------
# Health (data/health.json)
# ---------------------------------------------------------------------------


class SourceHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    source_id: str
    name: str
    category: str
    status: HealthStatus
    last_success: Optional[datetime] = None
    last_attempt: Optional[datetime] = None
    last_error: Optional[str] = None
    item_count: int = 0
    response_time_ms: Optional[int] = None
    success_rate_7d: Optional[float] = Field(default=None, ge=0, le=1)
    consecutive_failures: int = 0


class HealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    schema_version: str
    generated_at: Optional[datetime] = None
    overall: Optional[Literal["healthy", "degraded", "failed"]] = None
    sources: list[SourceHealth] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# PublishedData (data/YYYY/MM/YYYY-MM-DD.json)
# ---------------------------------------------------------------------------


class CategoryBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    count: int = Field(..., ge=0, le=20)
    items: list[Trend] = Field(..., max_length=20)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources_ok: int = 0
    sources_failed: int = 0
    total_dropped: int = 0
    generated_by: Optional[str] = None


class PublishedMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_summary: RunSummary


class PublishedData(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    schema_version: str
    generated_at: datetime
    pipeline_version: str
    ai_enabled: bool
    categories: dict[str, CategoryBlock]
    trends: list[Trend]
    events: list[Event] = Field(default_factory=list)
    metadata: PublishedMetadata


# ---------------------------------------------------------------------------
# Index (data/index.json)
# ---------------------------------------------------------------------------


class DateIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., pattern=r"^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}\.json$")
    total_items: int = Field(..., ge=0)
    categories: dict[str, int] = Field(default_factory=dict)


class DateIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    schema_version: str
    updated_at: Optional[datetime] = None
    latest_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    available_dates: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    date_index: dict[str, DateIndexEntry] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SourcesState (data/sources_state.json)
# ---------------------------------------------------------------------------


class SourceRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    source_id: str
    name: str
    category: str
    enabled: bool
    status: HealthStatus
    last_success: Optional[datetime] = None
    last_attempt: Optional[datetime] = None
    last_error: Optional[str] = None
    item_count: int = 0
    response_time_ms: Optional[int] = None
    consecutive_failures: int = 0
    success_rate_7d: Optional[float] = Field(default=None, ge=0, le=1)


class SourcesState(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={datetime: _iso_utc})
    schema_version: str
    updated_at: Optional[datetime] = None
    sources: list[SourceRuntimeState] = Field(default_factory=list)
