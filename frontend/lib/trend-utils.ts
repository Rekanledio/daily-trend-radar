// Trend history utilities for Daily Trend Radar (Stage 4-5).
//
// Pure, testable functions for:
// - Loading historical trend scores across dates
// - Matching trends across days by stable ID
// - Computing trend direction (up / down / stable)
//
// All functions are null-safe and handle missing data gracefully.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TrendDirection = "up" | "down" | "stable" | "insufficient_data";

export interface TrendDataPoint {
  date: string; // "YYYY-MM-DD"
  score: number | null;
}

export interface TrendHistory {
  /** Historical data points, ordered chronologically. */
  points: TrendDataPoint[];
  /** Score change from the most recent previous data point to the latest. */
  change: number | null;
  /** Trend direction based on change threshold. */
  direction: TrendDirection;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Score change threshold for trend direction. */
const CHANGE_THRESHOLD = 5.0;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a map of trend_id → Map<date, trend_score> from available historical data.
 * This is the core cross-date matching — uses stable `trend.id` as the key.
 */
export function buildHistoryMap(
  dataByDate: Map<string, Array<{ id: string; trend_score?: number | null }>>
): Map<string, Map<string, number | null>> {
  const historyMap = new Map<string, Map<string, number | null>>();

  for (const [date, trends] of dataByDate) {
    for (const t of trends) {
      if (!t.id) continue;
      if (!historyMap.has(t.id)) {
        historyMap.set(t.id, new Map());
      }
      const dateMap = historyMap.get(t.id)!;
      // Only set if not already present (first date wins — dataByDate should be ordered)
      if (!dateMap.has(date)) {
        dateMap.set(date, t.trend_score ?? null);
      }
    }
  }

  return historyMap;
}

/**
 * Get historical data points for a specific trend ID.
 * Filters only dates that have data for this trend.
 *
 * @param trendId - Stable trend ID to look up
 * @param historyMap - Map built from buildHistoryMap()
 * @param allDates - All available dates in chronological order
 * @param currentDate - The currently selected date (today's view)
 */
export function getTrendHistory(
  trendId: string,
  historyMap: Map<string, Map<string, number | null>>,
  allDates: string[],
  currentDate: string | null
): TrendHistory {
  const dateScores = historyMap.get(trendId);
  if (!dateScores) {
    return { points: [], change: null, direction: "insufficient_data" };
  }

  // Collect points for dates that exist in our data, in chronological order
  const points: TrendDataPoint[] = [];
  for (const date of allDates) {
    if (dateScores.has(date)) {
      points.push({ date, score: dateScores.get(date) ?? null });
    }
  }

  // Filter to only dates before or equal to currentDate (don't show future data)
  const relevant = currentDate
    ? points.filter((p) => p.date <= currentDate)
    : points;

  // Calculate change: latest vs previous
  const sorted = [...relevant].sort((a, b) => a.date.localeCompare(b.date));
  const validScores = sorted.filter((p) => p.score !== null && p.score !== undefined);

  let change: number | null = null;
  let direction: TrendDirection = "insufficient_data";

  if (validScores.length >= 2) {
    const latest = validScores[validScores.length - 1].score!;
    const previous = validScores[validScores.length - 2].score!;
    change = Math.round((latest - previous) * 10) / 10;
    direction = calcDirection(change);
  } else if (validScores.length === 1) {
    direction = "insufficient_data";
    change = null;
  }

  return { points: sorted, change, direction };
}

/**
 * Calculate trend direction from a score change value.
 */
export function calcDirection(change: number): TrendDirection {
  if (change > CHANGE_THRESHOLD) return "up";
  if (change < -CHANGE_THRESHOLD) return "down";
  return "stable";
}

// ---------------------------------------------------------------------------
// SVG Sparkline generator
// ---------------------------------------------------------------------------

/**
 * Generate a tiny inline SVG sparkline from a series of scores.
 * Returns an SVG string or null if there's insufficient data.
 *
 * @param scores - Array of valid (non-null) scores, typically 1-7 points.
 * @param width - SVG width in pixels
 * @param height - SVG height in pixels
 */
export function renderSparkline(
  scores: number[],
  width: number = 48,
  height: number = 16
): string | null {
  if (scores.length < 2) return null;

  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1; // avoid division by zero

  const padding = 1;
  const plotW = width - padding * 2;
  const plotH = height - padding * 2;

  const points = scores.map((s, i) => {
    const x = padding + (i / (scores.length - 1)) * plotW;
    const y = padding + plotH - ((s - min) / range) * plotH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const d = `M ${points.join(" L ")}`;

  // Color based on trend direction
  const isUp = scores[scores.length - 1] >= scores[0];
  const strokeColor = isUp ? "#22c55e" : "#ef4444";

  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
    <path d="${d}" fill="none" stroke="${strokeColor}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}
