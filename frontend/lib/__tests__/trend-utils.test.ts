// Tests for trend history utilities (Stage 4-5)

import * as assert from "node:assert";
import { describe, it } from "node:test";

import {
  buildHistoryMap,
  getTrendHistory,
  calcDirection,
  renderSparkline,
} from "../trend-utils.ts";

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
      ["2026-07-25", [{ id: "trend-1" }]], // no trend_score
    ]);
    const map = buildHistoryMap(dataByDate);
    assert.equal(map.get("trend-1")?.get("2026-07-25"), null);
  });
});

// ---------------------------------------------------------------------------
// getTrendHistory
// ---------------------------------------------------------------------------

describe("getTrendHistory", () => {
  const allDates = ["2026-07-25", "2026-07-26"];

  function makeMap(
    entries: Record<string, Record<string, number | null>>
  ): Map<string, Map<string, number | null>> {
    const map = new Map();
    for (const [id, dateScores] of Object.entries(entries)) {
      const inner = new Map();
      for (const [d, s] of Object.entries(dateScores)) {
        inner.set(d, s);
      }
      map.set(id, inner);
    }
    return map;
  }

  it("returns insufficient_data for unknown trend", () => {
    const result = getTrendHistory("unknown", new Map(), allDates, "2026-07-26");
    assert.equal(result.direction, "insufficient_data");
    assert.equal(result.points.length, 0);
    assert.equal(result.change, null);
  });

  it("returns insufficient_data for single data point", () => {
    const map = makeMap({ "trend-1": { "2026-07-26": 50 } });
    const result = getTrendHistory("trend-1", map, allDates, "2026-07-26");
    assert.equal(result.direction, "insufficient_data");
    assert.equal(result.points.length, 1);
    assert.equal(result.change, null);
  });

  it("calculates change from two data points", () => {
    const map = makeMap({
      "trend-1": { "2026-07-25": 50, "2026-07-26": 65 },
    });
    const result = getTrendHistory("trend-1", map, allDates, "2026-07-26");
    assert.equal(result.direction, "up");
    assert.equal(result.change, 15);
    assert.equal(result.points.length, 2);
  });

  it("detects downward trend", () => {
    const map = makeMap({
      "trend-1": { "2026-07-25": 60, "2026-07-26": 45 },
    });
    const result = getTrendHistory("trend-1", map, allDates, "2026-07-26");
    assert.equal(result.direction, "down");
    assert.equal(result.change, -15);
  });

  it("detects stable trend within threshold", () => {
    const map = makeMap({
      "trend-1": { "2026-07-25": 50, "2026-07-26": 53 },
    });
    const result = getTrendHistory("trend-1", map, allDates, "2026-07-26");
    assert.equal(result.direction, "stable");
    assert.equal(result.change, 3);
  });

  it("handles null scores gracefully", () => {
    const map = makeMap({
      "trend-1": { "2026-07-25": null, "2026-07-26": 50 },
    });
    const result = getTrendHistory("trend-1", map, allDates, "2026-07-26");
    // Only 1 valid score, should be insufficient
    assert.equal(result.direction, "insufficient_data");
  });

  it("handles three data points", () => {
    const dates = ["2026-07-24", "2026-07-25", "2026-07-26"];
    const map = makeMap({
      "trend-1": { "2026-07-24": 30, "2026-07-25": 50, "2026-07-26": 65 },
    });
    const result = getTrendHistory("trend-1", map, dates, "2026-07-26");
    assert.equal(result.direction, "up");
    assert.equal(result.change, 15); // 65 - 50
    assert.equal(result.points.length, 3);
    assert.equal(result.points[0].date, "2026-07-24");
    assert.equal(result.points[2].date, "2026-07-26");
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
