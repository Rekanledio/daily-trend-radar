// Focused runtime validation guards for data read by JsonFileRepository.
//
// IMPORTANT (see docs/DATA_CONTRACT.md §9 and PROJECT_RULES):
//   The *authoritative* JSON Schema validation is owned by the Python pipeline
//   (jsonschema) and enforced in CI. The frontend does NOT re-implement a
//   full JSON Schema engine (that would be dual-maintenance + an extra dep).
//   Instead these guards catch (a) corrupt JSON structures and (b) the
//   project's hard red lines -- no mock in production, every trend carries a
//   real original_url, and category counts match item lengths.
//   On any failure the caller must NOT render the data (fails safe -> null).

import type {
  PublishedData,
  DateIndex,
  HealthSnapshot,
  SourcesState,
} from "../types";

const HEALTH_STATUSES = new Set(["healthy", "degraded", "failed", "disabled"]);

export class DataValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataValidationError";
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isString(v: unknown): v is string {
  return typeof v === "string";
}

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new DataValidationError(msg);
}

/** Red-line check for one trend, wherever it appears (trends[] or
 *  categories[*].items). No mock in production; every trend must carry a
 *  real, non-empty original_url. */
function checkTrend(t: unknown, where: string): void {
  assert(isObject(t), `${where} must be an object`);
  const tr = t as Record<string, unknown>;
  assert(
    tr["is_mock"] === false,
    `${where}.is_mock must be false (no mock data in production)`,
  );
  assert(
    isString(tr["original_url"]) && (tr["original_url"] as string).length > 0,
    `${where}.original_url must be a non-empty string`,
  );
}

/** Enforce red lines + critical structure of a PublishedData payload. */
export function validatePublishedData(input: unknown): PublishedData {
  assert(isObject(input), "PublishedData must be an object");
  const o = input as Record<string, unknown>;

  assert(isString(o["date"]), "date must be a string");
  assert(isString(o["schema_version"]), "schema_version must be a string");
  assert(isString(o["generated_at"]), "generated_at must be a string");
  assert(isString(o["pipeline_version"]), "pipeline_version must be a string");
  assert(typeof o["ai_enabled"] === "boolean", "ai_enabled must be boolean");
  assert(isObject(o["categories"]), "categories must be an object");
  assert(Array.isArray(o["trends"]), "trends must be an array");
  assert(Array.isArray(o["events"]), "events must be an array");
  assert(isObject(o["metadata"]), "metadata must be an object");

  const trends = o["trends"] as unknown[];
  trends.forEach((t, i) => checkTrend(t, `trends[${i}]`));

  const categories = o["categories"] as Record<string, unknown>;
  Object.entries(categories).forEach(([cat, block]) => {
    assert(isObject(block), `categories.${cat} must be an object`);
    const b = block as Record<string, unknown>;
    assert(Array.isArray(b["items"]), `categories.${cat}.items must be an array`);
    const items = b["items"] as unknown[];
    assert(
      typeof b["count"] === "number" && b["count"] === items.length,
      `categories.${cat}.count must equal items.length`,
    );
    // categories.*.items is the per-category data the UI reads -> red line applies here too
    items.forEach((t, i) => checkTrend(t, `categories.${cat}.items[${i}]`));
  });

  return input as PublishedData;
}

export function validateHealth(input: unknown): HealthSnapshot {
  assert(isObject(input), "HealthSnapshot must be an object");
  const o = input as Record<string, unknown>;
  assert(isString(o["schema_version"]), "schema_version must be a string");
  const overall = o["overall"];
  assert(
    overall === null || (isString(overall) && HEALTH_STATUSES.has(overall)),
    "overall must be null or a valid HealthStatus",
  );
  assert(Array.isArray(o["sources"]), "sources must be an array");
  return input as HealthSnapshot;
}

export function validateDateIndex(input: unknown): DateIndex {
  assert(isObject(input), "DateIndex must be an object");
  const o = input as Record<string, unknown>;
  assert(isString(o["schema_version"]), "schema_version must be a string");
  const latest = o["latest_date"];
  assert(latest === null || isString(latest), "latest_date must be null or string");
  assert(Array.isArray(o["available_dates"]), "available_dates must be an array");
  assert(isObject(o["date_index"]), "date_index must be an object");
  return input as DateIndex;
}

export function validateSourcesState(input: unknown): SourcesState {
  assert(isObject(input), "SourcesState must be an object");
  const o = input as Record<string, unknown>;
  assert(isString(o["schema_version"]), "schema_version must be a string");
  assert(Array.isArray(o["sources"]), "sources must be an array");
  return input as SourcesState;
}
