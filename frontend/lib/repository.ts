// DataRepository abstract interface (frontend side).
//
// The frontend MUST read published data only through this interface, never by
// importing JSON file paths directly. This keeps storage swappable
// (JsonFileRepository now, SupabaseRepository later) with zero UI changes.
//
// Interface only -- NO implementation in this file (see PROJECT_RULES / v2).

import type {
  DateIndex,
  Event,
  HealthSnapshot,
  PublishedData,
  SourcesState,
  Trend,
} from "./types";

export interface DataRepository {
  /** Return the most recent PublishedData (by latest_date), or null. */
  getLatest(): Promise<PublishedData | null>;
  /** Return PublishedData for a specific YYYY-MM-DD, or null. */
  getByDate(date: string): Promise<PublishedData | null>;
  /** Return the global date index (index.json). */
  getHistoryIndex(): Promise<DateIndex>;
  /** Return the data-source health snapshot (health.json). */
  getHealth(): Promise<HealthSnapshot>;
  /** Return runtime source states (sources_state.json). */
  getSourcesState(): Promise<SourcesState>;
  /** Return published trends of a category, optionally for a date. */
  getByCategory(category: string, date?: string): Promise<Trend[]>;
  /** Return aggregated events, optionally for a date. */
  getEvents(date?: string): Promise<Event[]>;
}
