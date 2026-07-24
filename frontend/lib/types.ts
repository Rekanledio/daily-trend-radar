// Core data contracts for Daily Trend Radar (TypeScript side).
//
// These types mirror schemas/*.schema.json and pipeline/src/pipeline/models.py.
// They are the single shared vocabulary between the Python pipeline and the
// Next.js frontend. Keep them in sync with the JSON Schemas (see
// docs/DATA_CONTRACT.md, section "Python / TypeScript Schema 同步方案").

export type TrendStatus = "draft" | "verified" | "published" | "rejected";
export type SummaryOrigin = "original" | "ai" | "none";
export type TagsOrigin = "rule" | "ai" | "none";
export type SourceType = "api" | "rss" | "page";
export type LegalStatus =
  | "official_api"
  | "official_rss"
  | "public_page"
  | "third_party_legal"
  | "manual";
export type HealthStatus = "healthy" | "degraded" | "failed" | "disabled";

export interface ScoreBreakdown {
  authority: number; // 0-100
  heat: number; // 0-100
  freshness: number; // 0-100
  multi_source: number; // 0-100
  platform: number; // 0-100
}

export interface Trend {
  id: string;
  event_id: string | null;
  source_id: string;
  source_name: string; // denormalized snapshot
  category: string; // category id (configurable, not a fixed enum)
  title: string;
  summary: string | null;
  summary_origin: SummaryOrigin;
  original_url: string; // required for production, must be a real URL
  canonical_url: string | null; // normalized URL used for dedup / stable id
  author: string | null;
  tags: string[];
  tags_origin: TagsOrigin;
  published_at: string | null; // ISO 8601 UTC
  collected_at: string; // ISO 8601 UTC
  updated_at: string; // ISO 8601 UTC
  heat_raw: Record<string, unknown> | null;
  hot_score: number; // 0-100
  score_breakdown: ScoreBreakdown;
  rank_in_source: number | null;
  status: TrendStatus;
  lang: string;
  is_mock: boolean; // production MUST be false
}

export interface EventSourceRef {
  source_id: string;
  source_name: string;
  trend_id: string;
  original_url: string; // per-source link, kept for traceability
  title: string;
  hot_score: number; // 0-100
}

export interface Event {
  event_id: string;
  title: string;
  summary: string | null;
  category: string;
  sources: EventSourceRef[];
  source_count: number; // == distinct source_id count (NOT sources.length)
  trend_ids: string[]; // == sources.map(s => s.trend_id)
  hot_score: number; // 0-100
  score_breakdown: ScoreBreakdown;
  published_at: string; // ISO 8601 UTC
  updated_at: string; // ISO 8601 UTC
}

export interface SourceConfig {
  id: string;
  name: string;
  category: string;
  type: SourceType;
  enabled: boolean;
  priority: number;
  max_items: number; // 1-20
  timeout: number;
  retry_count: number;
  rate_limit: string;
  legal_status: LegalStatus;
  terms_url: string | null;
  endpoint?: string | null;
  query?: string | null;
  fallback?: string | null;
  notes?: string | null;
}

export interface SourcesConfig {
  version: number;
  defaults?: {
    timeout?: number;
    retry_count?: number;
    rate_limit?: string;
    max_items?: number;
  };
  sources: SourceConfig[];
}

export interface SourceHealth {
  source_id: string;
  name: string;
  category: string;
  status: HealthStatus;
  last_success: string | null; // ISO 8601 UTC
  last_attempt: string | null; // ISO 8601 UTC
  last_error: string | null;
  item_count: number;
  response_time_ms: number | null;
  success_rate_7d?: number | null;
  consecutive_failures: number;
}

export interface HealthSnapshot {
  schema_version: string;
  generated_at: string | null; // ISO 8601 UTC
  overall: "healthy" | "degraded" | "failed" | null; // null until first run
  sources: SourceHealth[];
}

export interface CategoryBlock {
  count: number; // 0-20, == items.length
  items: Trend[]; // <= 20
}

export interface RunSummary {
  sources_ok: number;
  sources_failed: number;
  total_dropped: number;
  generated_by?: string | null;
}

export interface PublishedMetadata {
  run_summary: RunSummary;
  [key: string]: unknown;
}

export interface PublishedData {
  date: string; // YYYY-MM-DD
  schema_version: string;
  generated_at: string; // ISO 8601 UTC
  pipeline_version: string;
  ai_enabled: boolean;
  categories: Record<string, CategoryBlock>;
  trends: Trend[]; // union of all categories' items
  events: Event[];
  metadata: PublishedMetadata;
}

export interface DateIndexEntry {
  path: string; // YYYY/MM/YYYY-MM-DD.json
  total_items: number;
  categories: Record<string, number>;
}

export interface DateIndex {
  schema_version: string;
  updated_at: string | null; // ISO 8601 UTC
  latest_date: string | null; // pointer, NOT the only source
  available_dates: string[]; // YYYY-MM-DD[]
  categories: string[];
  date_index: Record<string, DateIndexEntry>;
}

export interface SourceRuntimeState {
  source_id: string;
  name: string;
  category: string;
  enabled: boolean;
  status: HealthStatus;
  last_success: string | null;
  last_attempt: string | null;
  last_error: string | null;
  item_count: number;
  response_time_ms: number | null;
  consecutive_failures: number;
  success_rate_7d?: number | null;
}

export interface SourcesState {
  schema_version: string;
  updated_at: string | null;
  sources: SourceRuntimeState[];
}
