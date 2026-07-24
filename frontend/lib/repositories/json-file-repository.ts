// JsonFileRepository — the MVP storage backend for DataRepository.
//
// Reads published data from local `data/*.json` files via the Node `fs`
// module, server-side only (used inside Next.js Server Components).
// It is the ONLY place that touches filesystem paths; the UI/consumers
// depend solely on the DataRepository interface, so swapping this for
// SupabaseRepository later is a one-line change in `createRepository`.
//
// Red lines honoured:
//   - No path traversal: dates are strictly validated (YYYY-MM-DD + real
//     calendar check) before a path is built; the resolved file must stay
//     inside the data dir.
//   - No unvalidated data: every payload is passed through a runtime
//     guard (see ./validate) and invalid data is dropped (null), never
//     rendered.

import { existsSync, readFileSync, statSync } from "fs";
import path from "path";
import type { DataRepository } from "../repository";
import type {
  DateIndex,
  Event,
  HealthSnapshot,
  PublishedData,
  SourcesState,
  Trend,
} from "../types";
import {
  validatePublishedData,
  validateHealth,
  validateDateIndex,
  validateSourcesState,
  DataValidationError,
} from "./validate.ts";

/** Thrown for malformed / out-of-range date inputs (incl. traversal). */
export class InvalidDateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidDateError";
  }
}

/** Thrown when a requested, well-formed data file does not exist. */
export class DataNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DataNotFoundError";
  }
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidCalendarDate(y: string, m: string, d: string): boolean {
  const yy = Number(y);
  const mm = Number(m);
  const dd = Number(d);
  if (!Number.isInteger(yy) || !Number.isInteger(mm) || !Number.isInteger(dd)) return false;
  if (mm < 1 || mm > 12) return false;
  const daysInMonth = new Date(Date.UTC(yy, mm, 0)).getUTCDate();
  if (dd < 1 || dd > daysInMonth) return false;
  return true;
}

export interface JsonFileRepositoryOptions {
  /** Override the data directory (mainly for tests / future adapters). */
  dataDir?: string;
}

export class JsonFileRepository implements DataRepository {
  private readonly dataDir: string;

  constructor(options: JsonFileRepositoryOptions = {}) {
    this.dataDir = options.dataDir
      ? path.resolve(options.dataDir)
      : JsonFileRepository.defaultDataDir();
  }

  /** Resolve the repo-root `data/` dir regardless of cwd (dev / test / Vercel). */
  private static defaultDataDir(): string {
    const cwd = process.cwd();
    const candidates = [path.join(cwd, "data"), path.join(cwd, "..", "data")];
    for (const c of candidates) {
      try {
        if (existsSync(c) && statSync(c).isDirectory()) return c;
      } catch {
        /* ignore and try next */
      }
    }
    return path.join(cwd, "data");
  }

  /**
   * Validate a YYYY-MM-DD string. Throws InvalidDateError on illegal
   * input (bad format, impossible calendar date, or anything that is not
   * strictly digits-and-dashes -> blocks path traversal).
   */
  private static parseDate(date: string): { y: string; m: string; full: string } {
    if (typeof date !== "string" || !DATE_RE.test(date)) {
      throw new InvalidDateError(
        `Invalid date format: ${JSON.stringify(date)} (expected YYYY-MM-DD)`,
      );
    }
    const [y, m, d] = date.split("-");
    if (!isValidCalendarDate(y!, m!, d!)) {
      throw new InvalidDateError(`Not a real calendar date: ${date}`);
    }
    return { y, m, full: date };
  }

  /**
   * Read + JSON.parse + validate a file. Returns null on: missing file,
   * unreadable, corrupt JSON, or validation failure (never returns
   * invalid data). `validate` is the focused runtime guard from ./validate.
   */
  private readJsonSafe<T>(file: string, validate: (u: unknown) => T): T | null {
    if (!existsSync(file)) return null;
    let raw: string;
    try {
      raw = readFileSync(file, "utf8");
    } catch {
      return null;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return null;
    }
    try {
      return validate(parsed);
    } catch (e) {
      if (e instanceof DataValidationError) return null;
      return null;
    }
  }

  /** Build (and guard) the per-date file path; rejects traversal. */
  private publishedPath(date: string): string {
    const { y, m, full } = JsonFileRepository.parseDate(date);
    const resolved = path.resolve(this.dataDir, y, m, `${full}.json`);
    const root = path.resolve(this.dataDir);
    if (resolved !== root && !resolved.startsWith(root + path.sep)) {
      throw new InvalidDateError(`Path traversal denied for date: ${date}`);
    }
    return resolved;
  }

  async getLatest(): Promise<PublishedData | null> {
    const index = await this.getHistoryIndex();
    if (!index.latest_date) return null;
    return this.getByDate(index.latest_date);
  }

  async getByDate(date: string): Promise<PublishedData | null> {
    const file = this.publishedPath(date);
    return this.readJsonSafe<PublishedData>(file, validatePublishedData);
  }

  async getHistoryIndex(): Promise<DateIndex> {
    const file = path.join(this.dataDir, "index.json");
    const v = this.readJsonSafe<DateIndex>(file, validateDateIndex);
    // index.json is committed in the skeleton; fall back only if genuinely absent.
    return (
      v ??
      ({
        schema_version: "1.0",
        updated_at: null,
        latest_date: null,
        available_dates: [],
        categories: [],
        date_index: {},
      } as DateIndex)
    );
  }

  async getHealth(): Promise<HealthSnapshot> {
    const file = path.join(this.dataDir, "health.json");
    const v = this.readJsonSafe<HealthSnapshot>(file, validateHealth);
    return (
      v ??
      ({ schema_version: "1.0", generated_at: null, overall: null, sources: [] } as HealthSnapshot)
    );
  }

  async getSourcesState(): Promise<SourcesState> {
    const file = path.join(this.dataDir, "sources_state.json");
    const v = this.readJsonSafe<SourcesState>(file, validateSourcesState);
    return (
      v ?? ({ schema_version: "1.0", updated_at: null, sources: [] } as SourcesState)
    );
  }

  async getByCategory(category: string, date?: string): Promise<Trend[]> {
    const data = date ? await this.getByDate(date) : await this.getLatest();
    if (!data) return [];
    return data.categories[category]?.items ?? [];
  }

  async getEvents(date?: string): Promise<Event[]> {
    const data = date ? await this.getByDate(date) : await this.getLatest();
    if (!data) return [];
    return data.events ?? [];
  }
}

/**
 * Factory: the single seam to swap storage backends.
 * Today: JsonFileRepository. Later: SupabaseRepository — change only here.
 */
export function createRepository(options?: JsonFileRepositoryOptions): DataRepository {
  return new JsonFileRepository(options);
}
