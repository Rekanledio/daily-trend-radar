"""Daily Trend Radar - 数据采集与处理 Pipeline 包。

阶段 0 第三轮：已定义核心数据契约（models / validation / repository）。
后续阶段将在此之下添加 core / adapters / stages / ai 等子模块。
"""

from .models import (
    CategoryBlock,
    DateIndex,
    DateIndexEntry,
    Event,
    EventSourceRef,
    HealthSnapshot,
    HealthStatus,
    LegalStatus,
    PublishedData,
    PublishedMetadata,
    RunSummary,
    ScoreBreakdown,
    SourceConfig,
    SourceDefaults,
    SourceHealth,
    SourceRuntimeState,
    SourcesConfig,
    SourcesState,
    SourceType,
    SummaryOrigin,
    TagsOrigin,
    Trend,
    TrendStatus,
)
from .validation import (
    validate_event,
    validate_production_trend,
    validate_published_data,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "Trend",
    "Event",
    "EventSourceRef",
    "ScoreBreakdown",
    "TrendStatus",
    "SummaryOrigin",
    "TagsOrigin",
    "SourceType",
    "LegalStatus",
    "HealthStatus",
    "SourceConfig",
    "SourceDefaults",
    "SourcesConfig",
    "SourceHealth",
    "HealthSnapshot",
    "CategoryBlock",
    "RunSummary",
    "PublishedMetadata",
    "PublishedData",
    "DateIndexEntry",
    "DateIndex",
    "SourceRuntimeState",
    "SourcesState",
    "validate_production_trend",
    "validate_event",
    "validate_published_data",
]
