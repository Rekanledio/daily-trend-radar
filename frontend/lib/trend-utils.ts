// Trend history utilities for Daily Trend Radar (Stage 4-5 / 5-B).
//
// Pure, testable functions for:
// - Loading historical trend scores across dates
// - Matching trends across days by stable ID
// - Computing trend direction (up / down / stable)
// - Computing rank change across dates
// - Tracking days present and first seen date
//
// All functions are null-safe and handle missing data gracefully.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TrendDirection = "up" | "down" | "stable" | "insufficient_data";

export interface TrendDataPoint {
  date: string; // "YYYY-MM-DD"
  score: number | null;
  rank: number | null; // Position within that date (1 = highest hot_score)
}

export interface TrendHistory {
  /** Historical data points, ordered chronologically. */
  points: TrendDataPoint[];
  /** Score change from the most recent previous data point to the latest. */
  change: number | null;
  /** Trend direction based on score change threshold. */
  direction: TrendDirection;
  /**
   * Rank change: previousRank - currentRank.
   * Positive = ranking improved (moved up, smaller number).
   * Negative = ranking declined (moved down, larger number).
   * Null = insufficient data.
   */
  rankChange: number | null;
  /** Number of distinct dates this trend appeared in the historical data. */
  daysPresent: number;
  /** Earliest date this trend appeared, or null if never seen. */
  firstSeen: string | null;
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
      if (!dateMap.has(date)) {
        dateMap.set(date, t.trend_score ?? null);
      }
    }
  }

  return historyMap;
}

/**
 * Build a map of trend_id → Map<date, rank> from available historical data.
 * Rank is determined by ordering trends by hot_score DESC within each date
 * (position 1 = highest hot_score).
 *
 * @param dataByDate - Historical trends indexed by date
 * @returns Map<trend_id, Map<date, rank>>
 */
export function buildRankMap(
  dataByDate: Map<string, Array<{ id: string; hot_score?: number }>>
): Map<string, Map<string, number>> {
  const rankMap = new Map<string, Map<string, number>>();

  for (const [date, trends] of dataByDate) {
    // Sort by hot_score descending
    const sorted = [...trends]
      .filter((t) => t.id)
      .sort((a, b) => {
        const sa = typeof a.hot_score === "number" && !isNaN(a.hot_score) ? a.hot_score : 0;
        const sb = typeof b.hot_score === "number" && !isNaN(b.hot_score) ? b.hot_score : 0;
        return sb - sa;
      });

    // Assign rank to each trend
    for (let i = 0; i < sorted.length; i++) {
      const tid = sorted[i].id;
      if (!tid) continue;
      if (!rankMap.has(tid)) {
        rankMap.set(tid, new Map());
      }
      // Only set first occurrence per date (already guaranteed by single pass)
      const dateMap = rankMap.get(tid)!;
      if (!dateMap.has(date)) {
        dateMap.set(date, i + 1); // 1-based rank
      }
    }
  }

  return rankMap;
}

/**
 * Get historical data points and intelligence for a specific trend ID.
 *
 * Computes:
 * - Data points (score + rank per date)
 * - Score change (latest vs previous valid score)
 * - Rank change (previousRank - currentRank, positive = improved)
 * - Days present (number of distinct dates this trend appeared)
 * - First seen date
 *
 * @param trendId - Stable trend ID to look up
 * @param historyMap - Map built from buildHistoryMap()
 * @param rankMap - Map built from buildRankMap()
 * @param allDates - All available dates in chronological order
 * @param currentDate - The currently selected date (filter to ≤ this date)
 */
export function getTrendHistory(
  trendId: string,
  historyMap: Map<string, Map<string, number | null>>,
  rankMap: Map<string, Map<string, number>>,
  allDates: string[],
  currentDate: string | null
): TrendHistory {
  const dateScores = historyMap.get(trendId);

  // Collect points for dates that exist, in chronological order
  const points: TrendDataPoint[] = [];
  for (const date of allDates) {
    if (dateScores?.has(date)) {
      const rank = rankMap.get(trendId)?.get(date) ?? null;
      points.push({
        date,
        score: dateScores.get(date) ?? null,
        rank,
      });
    }
  }

  // Filter to only dates before or equal to currentDate
  const relevant = currentDate
    ? points.filter((p) => p.date <= currentDate)
    : points;

  const sorted = [...relevant].sort((a, b) => a.date.localeCompare(b.date));

  const daysPresent = sorted.length;

  // First seen
  const firstSeen = daysPresent > 0 ? sorted[0].date : null;

  // Score change: latest valid score vs most recent previous valid score
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

  // Rank change: compare current rank to most recent previous rank
  // rankChange = previousRank - currentRank (positive = moved up)
  const validRanks = sorted.filter((p) => p.rank !== null && p.rank !== undefined);
  let rankChange: number | null = null;
  if (validRanks.length >= 2) {
    const currentRank = validRanks[validRanks.length - 1].rank!;
    const previousRank = validRanks[validRanks.length - 2].rank!;
    rankChange = previousRank - currentRank; // positive = moved up
  }

  return {
    points: sorted,
    change,
    direction,
    rankChange,
    daysPresent,
    firstSeen,
  };
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
 */
export function renderSparkline(
  scores: number[],
  width: number = 48,
  height: number = 16
): string | null {
  if (scores.length < 2) return null;

  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;

  const padding = 1;
  const plotW = width - padding * 2;
  const plotH = height - padding * 2;

  const points = scores.map((s, i) => {
    const x = padding + (i / (scores.length - 1)) * plotW;
    const y = padding + plotH - ((s - min) / range) * plotH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const d = `M ${points.join(" L ")}`;

  const isUp = scores[scores.length - 1] >= scores[0];
  const strokeColor = isUp ? "#22c55e" : "#ef4444";

  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
    <path d="${d}" fill="none" stroke="${strokeColor}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}
