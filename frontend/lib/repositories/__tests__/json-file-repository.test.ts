// JsonFileRepository tests — run with Node's built-in test runner:
//   node --experimental-strip-types --test lib/repositories/__tests__
//
// No extra test framework: we use `node:test` + `node:assert/strict`
// (Node 22 ships both). Fixtures live under ../__fixtures__ (never in
// the production data/ dir) and are is_mock=false samples except the
// explicitly broken one used to prove invalid data is never returned.

import { test } from "node:test";
import assert from "node:assert/strict";
import path from "path";
import { fileURLToPath } from "url";

import {
  JsonFileRepository,
  InvalidDateError,
} from "../json-file-repository.ts";
import { DataValidationError, validatePublishedData } from "../validate.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIX = path.join(__dirname, "..", "__fixtures__");

// --- Real project data/ (no production data yet) -------------------------

test("getLatest returns production data when index has latest_date", async () => {
  const repo = new JsonFileRepository(); // default -> project data/
  const data = await repo.getLatest();
  // Now that production data exists (Phase 1), getLatest returns real data.
  assert.ok(data !== null, "expected real production data");
  assert.ok(typeof data!.date === "string" && data!.date.length === 10);
  assert.ok(data!.trends.length > 0);
});

test("getByDate returns null for a valid date with no file", async () => {
  const repo = new JsonFileRepository();
  const data = await repo.getByDate("2026-07-24");
  assert.equal(data, null);
});

test("getHistoryIndex reads the committed index.json", async () => {
  const repo = new JsonFileRepository();
  const idx = await repo.getHistoryIndex();
  assert.ok(Array.isArray(idx.available_dates));
  // Production data exists: latest_date is a YYYY-MM-DD string, not null.
  assert.ok(typeof idx.latest_date === "string" && idx.latest_date.length === 10);
});

test("getHealth reads health.json (overall reflects pipeline state)", async () => {
  const repo = new JsonFileRepository();
  const h = await repo.getHealth();
  assert.ok("overall" in h);
  // Production data exists: overall is a valid health status string.
  assert.ok(h.overall === null || ["healthy", "degraded", "failed", "disabled"].includes(h.overall));
  assert.ok(Array.isArray(h.sources));
});

test("getSourcesState reads sources_state.json", async () => {
  const repo = new JsonFileRepository();
  const s = await repo.getSourcesState();
  assert.ok(Array.isArray(s.sources));
});

// --- Fixture-backed (valid production-shaped data) -------------------------

test("getLatest succeeds on a valid fixture", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  const data = await repo.getLatest();
  assert.ok(data, "expected valid fixture data");
  assert.equal(data!.date, "2026-07-24");
  assert.equal(data!.categories["ai_research"].items.length, 2);
});

test("getByDate succeeds for a legal date with a file", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  const data = await repo.getByDate("2026-07-24");
  assert.ok(data);
  assert.equal(data!.trends.length, 2);
});

test("getByCategory filters by category", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  const items = await repo.getByCategory("ai_research");
  assert.equal(items.length, 2);
  assert.equal(items[0].source_id, "arxiv");
});

test("getEvents returns aggregated events", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  const events = await repo.getEvents();
  assert.equal(events.length, 1);
  assert.equal(events[0].event_id, "ev1");
  assert.equal(events[0].source_count, 2);
});

// --- Red lines / safety ------------------------------------------------

test("illegal dates are rejected (bad format, traversal, impossible calendar)", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  await assert.rejects(() => repo.getByDate("not-a-date"), InvalidDateError);
  await assert.rejects(() => repo.getByDate("../../etc/passwd"), InvalidDateError);
  await assert.rejects(() => repo.getByDate("2026-13-01"), InvalidDateError);
  await assert.rejects(() => repo.getByDate("2026-02-30"), InvalidDateError);
});

test("invalid data (is_mock=true) is never returned — fails safe to null", async () => {
  const repo = new JsonFileRepository({ dataDir: FIX });
  const broken = await repo.getByDate("2026-07-25"); // 2026-07-25.json has is_mock=true
  assert.equal(broken, null);
  // The validation guard itself throws on the red line (production must
  // never carry is_mock data). Use an async fn so rejects() awaits it.
  await assert.rejects(
    async () => {
      validatePublishedData({
        date: "x",
        schema_version: "1.0",
        generated_at: "x",
        pipeline_version: "x",
        ai_enabled: false,
        categories: {},
        trends: [{ is_mock: true, original_url: "" }],
        events: [],
        metadata: {},
      });
    },
    DataValidationError,
  );
});
