// Tests for trend history utilities (Stage 4-5 / 5-B)

import * as assert from "node:assert";
import { describe, it } from "node:test";

import {
  buildHistoryMap,
  buildRankMap,
  getTrendHistory,
  calcDirection,
  renderSparkline,
} from "../trend-utils.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emptyRankMap(): Map<string, Map<string, number>> {
  return new Map();
}

function makeRankMap(
  entries: Record<string, Record<string, number>>
): Map<string, Map<string, number>> {
  const map = new Map<string, Map<string, number>>();
  for (const [id, dateRanks] of Object.entries(entries)) {
    const inner = new Map<string, number>();
    for (const [d, r] of Object.entries(dateRanks)) {
      inner.set(d, r);
    }
    map.set(id, inner);
  }
  return map;
}

function makeScoreMap(
  entries: Record<string, Record<string, number | null>>
): Map<string, Map<string, number | null>> {
  const map = new Map<string, Map<string, number | null>>();
  for (const [id, dateScores] of Object.entries(entries)) {
    const inner = new Map<string, number | null>();
    for (const [d, s] of Object.entries(dateScores)) {
      inner.set(d, s);
    }
    map.set(id, inner);
  }
  return map;
}

// ---------------------------------------------------------------------------
// buildHistoryMap
// ---------------------------------------------------------------------------

describe("buildHistoryMap", () => {
  it("builds map from multi-date data", () => {
    const dataByDate = new Map([
      ["2026-07-25", [
        { id: "trend-1", trend_score: 50 },
        { id: "trend-2", trend_score: 40 },
      ]],
      ["2026-07-26", [
        { id: "trend-1", trend_score: 65 },
        { id: "trend-2", trend_score: 35 },
        { id: "trend-3", trend_score: 55 },
      ]],
    ]);
    const map = buildHistoryMap(dataByDate);
    assert.equal(map.size, 3);
    assert.equal(map.get("trend-1")?.get("2026-07-25"), 50);
    assert.equal(map.get("trend-1")?.get("2026-07-26"), 65);
    assert.equal(map.get("trend-3")?.get("2026-07-26"), 55);
  });

  it("handles null scores", () => {
    const dataByDate = new Map([
      ["2026-07-26", [{ id: "trend-1", trend_score: null }]],
    ]);
    const map = buildHistoryMap(dataByDate);
    assert.equal(map.get("trend-1")?.get("2026-07-26"), null);
  });

  it("handles empty data", () => {
    const map = buildHistoryMap(new Map());
    assert.equal(map.size, 0);
  });

  it("handles missing trend_score field", () => {
    const dataByDate = new Map([
      ["2026-07-25", [{ id: "trend-1" }]],
    ]);
    const map = buildHistoryMap(dataByDate);
    assert.equal(map.get("trend-1")?.get("2026-07-25"), null);
  });
});

// ---------------------------------------------------------------------------
// buildRankMap
// ---------------------------------------------------------------------------

describe("buildRankMap", () => {
  it("assigns ranks by hot_score descending", () => {
    const dataByDate = new Map([
      ["2026-07-26", [
        { id: "a", hot_score: 50 },
        { id: "b", hot_score: 80 },
        { id: "c", hot_score: 30 },
      ]],
    ]);
    const map = buildRankMap(dataByDate);
    assert.equal(map.get("b")?.get("2026-07-26"), 1); // highest score → rank 1
    assert.equal(map.get("a")?.get("2026-07-26"), 2);
    assert.equal(map.get("c")?.get("2026-07-26"), 3);
  });

  it("handles multi-date data", () => {
    const dataByDate = new Map([
      ["2026-07-25", [
        { id: "a", hot_score: 50 },
        { id: "b", hot_score: 80 },
      ]],
      ["2026-07-26", [
        { id: "a", hot_score: 90 },
        { id: "b", hot_score: 40 },
      ]],
    ]);
    const map = buildRankMap(dataByDate);
    assert.equal(map.get("a")?.get("2026-07-25"), 2);
    assert.equal(map.get("b")?.get("2026-07-25"), 1);
    assert.equal(map.get("a")?.get("2026-07-26"), 1);
    assert.equal(map.get("b")?.get("2026-07-26"), 2);
  });

  it("handles empty data", () => {
    const map = buildRankMap(new Map());
    assert.equal(map.size, 0);
  });
});

// ---------------------------------------------------------------------------
// getTrendHistory (updated for Stage 5-B)
// ---------------------------------------------------------------------------

describe("getTrendHistory", () => {
  const allDates = ["2026-07-25", "2026-07-26"];

  it("returns defaults for unknown trend", () => {
    const result = getTrendHistory("unknown", new Map(), emptyRankMap(), allDates, "2026-07-26");
    assert.equal(result.points.length, 0);
    assert.equal(result.change, null);
    assert.equal(result.direction, "insufficient_data");
    assert.equal(result.rankChange, null);
    assert.equal(result.daysPresent, 0);
    assert.equal(result.firstSeen, null);
  });

  it("returns insufficient_data for single data point", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-26": 50 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-26": 1 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.direction, "insufficient_data");
    assert.equal(result.points.length, 1);
    assert.equal(result.change, null);
    assert.equal(result.rankChange, null);
    assert.equal(result.daysPresent, 1);
    assert.equal(result.firstSeen, "2026-07-26");
  });

  it("calculates score change and rank change from two data points", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": 50, "2026-07-26": 65 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 10, "2026-07-26": 7 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.direction, "up");
    assert.equal(result.change, 15);
    assert.equal(result.rankChange, 3); // 10 - 7 = +3 (moved up)
    assert.equal(result.daysPresent, 2);
    assert.equal(result.firstSeen, "2026-07-25");
  });

  it("rankChange positive when rank improves (smaller number)", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": 40, "2026-07-26": 60 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 10, "2026-07-26": 7 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.rankChange, 3); // moved up 3 spots
  });

  it("rankChange negative when rank declines (larger number)", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": 60, "2026-07-26": 40 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 7, "2026-07-26": 10 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.rankChange, -3); // moved down 3 spots
  });

  it("rankChange zero when rank unchanged", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": 50, "2026-07-26": 50 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 5, "2026-07-26": 5 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.rankChange, 0);
  });

  it("detects downward trend", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": 60, "2026-07-26": 45 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 3, "2026-07-26": 8 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.direction, "down");
    assert.equal(result.change, -15);
    assert.equal(result.rankChange, -5);
  });

  it("handles null scores gracefully", () => {
    const sm = makeScoreMap({ "trend-1": { "2026-07-25": null, "2026-07-26": 50 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-25": 5, "2026-07-26": 3 } });
    const result = getTrendHistory("trend-1", sm, rm, allDates, "2026-07-26");
    assert.equal(result.direction, "insufficient_data"); // only 1 valid score
    assert.equal(result.rankChange, 2); // rank still works (5 - 3 = 2)
    assert.equal(result.daysPresent, 2);
  });

  it("handles three data points", () => {
    const dates = ["2026-07-24", "2026-07-25", "2026-07-26"];
    const sm = makeScoreMap({ "trend-1": { "2026-07-24": 30, "2026-07-25": 50, "2026-07-26": 65 } });
    const rm = makeRankMap({ "trend-1": { "2026-07-24": 15, "2026-07-25": 10, "2026-07-26": 5 } });
    const result = getTrendHistory("trend-1", sm, rm, dates, "2026-07-26");
    assert.equal(result.change, 15);
    assert.equal(result.rankChange, 5); // 10 - 5 = +5
    assert.equal(result.points.length, 3);
    assert.equal(result.daysPresent, 3);
    assert.equal(result.firstSeen, "2026-07-24");
  });

  it("compares rank against most recent previous appearance (non-consecutive days)", () => {
    const dates = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"];
    // trend-1 appears on 07-20, 07-21, 07-23 (NOT 07-22)
    const sm = makeScoreMap({
      "trend-1": { "2026-07-20": 30, "2026-07-21": 50, "2026-07-23": 70 },
    });
    const rm = makeRankMap({
      "trend-1": { "2026-07-20": 10, "2026-07-21": 7, "2026-07-23": 5 },
    });
    const result = getTrendHistory("trend-1", sm, rm, dates, "2026-07-23");
    // Should compare 07-23 rank(5) vs 07-21 rank(7): 7 - 5 = +2
    assert.equal(result.rankChange, 2);
    assert.equal(result.daysPresent, 3);
    assert.equal(result.firstSeen, "2026-07-20");
  });
});

// ---------------------------------------------------------------------------
// calcDirection
// ---------------------------------------------------------------------------

describe("calcDirection", () => {
  it('returns "up" for change > +5', () => {
    assert.equal(calcDirection(5.1), "up");
    assert.equal(calcDirection(10), "up");
    assert.equal(calcDirection(100), "up");
  });

  it('returns "down" for change < -5', () => {
    assert.equal(calcDirection(-5.1), "down");
    assert.equal(calcDirection(-10), "down");
    assert.equal(calcDirection(-100), "down");
  });

  it('returns "stable" for changes within ±5', () => {
    assert.equal(calcDirection(5), "stable");
    assert.equal(calcDirection(-5), "stable");
    assert.equal(calcDirection(0), "stable");
    assert.equal(calcDirection(2.5), "stable");
    assert.equal(calcDirection(-2.5), "stable");
  });
});

// ---------------------------------------------------------------------------
// renderSparkline
// ---------------------------------------------------------------------------

describe("renderSparkline", () => {
  it("returns null for < 2 points", () => {
    assert.equal(renderSparkline([]), null);
    assert.equal(renderSparkline([50]), null);
  });

  it("returns SVG string for 2+ points", () => {
    const svg = renderSparkline([40, 60]);
    assert.ok(svg?.startsWith("<svg"));
    assert.ok(svg?.includes("<path"));
    assert.ok(svg?.endsWith("</svg>"));
  });

  it("handles flat line (same values)", () => {
    const svg = renderSparkline([50, 50, 50]);
    assert.ok(svg?.startsWith("<svg"));
  });

  it("trending up path color is green", () => {
    const svg = renderSparkline([30, 70], 48, 16);
    assert.ok(svg?.includes('stroke="#22c55e"'));
  });

  it("trending down path color is red", () => {
    const svg = renderSparkline([70, 30], 48, 16);
    assert.ok(svg?.includes('stroke="#ef4444"'));
  });

  it("handles custom dimensions", () => {
    const svg = renderSparkline([10, 20, 30], 64, 24);
    assert.ok(svg?.includes('width="64"'));
    assert.ok(svg?.includes('height="24"'));
  });
});
