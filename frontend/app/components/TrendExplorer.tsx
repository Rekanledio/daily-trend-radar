"use client";

import { useState, useMemo } from "react";
import type { Trend, HealthSnapshot } from "@/lib/types";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const y = d.getUTCFullYear();
    const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    const h = String(d.getUTCHours()).padStart(2, "0");
    const mi = String(d.getUTCMinutes()).padStart(2, "0");
    return `${y}-${mo}-${dd} ${h}:${mi}`;
  } catch {
    return iso || "—";
  }
}

function safeStr(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

function safeArr(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  return [];
}

function pubEpoch(iso: string | null): number {
  if (!iso) return 0;
  try {
    const n = new Date(iso).getTime();
    return isNaN(n) ? 0 : n;
  } catch {
    return 0;
  }
}

/** Human-readable status label with emoji. */
function statusEmoji(status: string | null): string {
  switch (status) {
    case "healthy": return "🟢";
    case "degraded": return "🟡";
    case "failed": return "🔴";
    case "disabled": return "⚪";
    default: return "⚫";
  }
}

function statusLabel(status: string | null): string {
  switch (status) {
    case "healthy": return "正常";
    case "degraded": return "部分异常";
    case "failed": return "异常";
    case "disabled": return "未启用";
    default: return "未知";
  }
}

// ---------------------------------------------------------------------------
// Sort / Filter types
// ---------------------------------------------------------------------------

type SourceFilter = "all" | "arxiv" | "github";
type CategoryFilter = "all" | "ai_research" | "opensource";
type SortMode = "hot" | "latest";

// ---------------------------------------------------------------------------
// TrendCard
// ---------------------------------------------------------------------------

function TrendCard({ trend }: { trend: Trend }) {
  const { source_id, metadata } = trend;
  const md = metadata ?? {};

  const stars = md["stars"];
  const forks = md["forks"];
  const language = md["language"];
  const hasGithubMeta = source_id === "github";

  const authors = source_id === "arxiv" ? safeArr(md["authors"]) : [];
  const categories = source_id === "arxiv" ? safeArr(md["categories"]) : [];
  const displayAuthors = authors.slice(0, 3);
  const extraAuthorCount = authors.length - 3;

  const hs = trend.hot_score;
  const hsValid = typeof hs === "number" && !isNaN(hs);

  return (
    <div className="glass-card rounded-xl p-5 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <a
          href={trend.original_url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="text-base font-semibold leading-snug link-hover text-gray-900 dark:text-gray-100 no-underline flex-1 min-w-0"
        >
          {trend.title || "—"}
        </a>
        <span
          className={`source-badge shrink-0 ${
            source_id === "arxiv"
              ? "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
              : "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300"
          }`}
        >
          {source_id === "arxiv" ? "arXiv" : "GitHub"}
        </span>
      </div>

      {trend.summary && (
        <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400 line-clamp-3">
          {trend.summary.length > 300
            ? trend.summary.slice(0, 300) + "…"
            : trend.summary}
        </p>
      )}

      <div className="flex flex-wrap gap-2 items-center">
        {hasGithubMeta && (
          <>
            <span className="meta-tag">
              ⭐ {stars !== null && stars !== undefined ? safeStr(stars) : "—"}
            </span>
            <span className="meta-tag">
              🍴 {forks !== null && forks !== undefined ? safeStr(forks) : "—"}
            </span>
            <span className="meta-tag">
              {language !== null && language !== undefined ? safeStr(language) : "—"}
            </span>
          </>
        )}

        {source_id === "arxiv" && (
          <>
            {displayAuthors.length > 0 && (
              <span className="meta-tag max-w-[200px] truncate" title={authors.join(", ")}>
                {displayAuthors.join(", ")}
                {extraAuthorCount > 0 ? ` +${extraAuthorCount}` : ""}
              </span>
            )}
            {categories.length > 0 && (
              <span className="meta-tag">
                {String(categories[0])}
                {categories.length > 1 ? ` +${categories.length - 1}` : ""}
              </span>
            )}
          </>
        )}

        <span className="meta-tag ml-auto">{formatTime(trend.published_at)}</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 shrink-0">
          {hsValid ? `热度 ${hs.toFixed(1)}` : "热度 —"}
        </span>
        <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          {hsValid && (
            <div
              className="hot-bar"
              style={{ width: `${Math.max(1, hs)}%` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter button
// ---------------------------------------------------------------------------

function FilterBtn<T extends string>({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors duration-200 ${
        active
          ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 ring-1 ring-indigo-300 dark:ring-indigo-700"
          : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
      }`}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// TrendExplorer — Client Component
// ---------------------------------------------------------------------------

export default function TrendExplorer({
  trends,
  currentDate,
  availableDates,
  latestDate: _latestDate,
  health,
}: {
  trends: Trend[];
  currentDate: string | null;
  availableDates: string[];
  latestDate: string | null;
  health: HealthSnapshot;
}) {
  const totalCount = trends.length;
  const [healthOpen, setHealthOpen] = useState(false);

  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [sortBy, setSortBy] = useState<SortMode>("hot");

  // Filter + sort
  const filteredTrends = useMemo(() => {
    const q = query.toLowerCase().trim();
    let result = trends;
    if (q) {
      result = result.filter((t) => {
        const md = t.metadata ?? {};
        const name = md["name"];
        const owner = md["owner"];
        return (
          t.title.toLowerCase().includes(q) ||
          (t.summary?.toLowerCase().includes(q) ?? false) ||
          (name != null && String(name).toLowerCase().includes(q)) ||
          (owner != null && String(owner).toLowerCase().includes(q))
        );
      });
    }

    if (sourceFilter !== "all") {
      result = result.filter((t) => t.source_id === sourceFilter);
    }

    if (categoryFilter !== "all") {
      result = result.filter((t) => t.category === categoryFilter);
    }

    const sorted = [...result];
    if (sortBy === "hot") {
      sorted.sort((a, b) => {
        const sa = typeof a.hot_score === "number" && !isNaN(a.hot_score) ? a.hot_score : 0;
        const sb = typeof b.hot_score === "number" && !isNaN(b.hot_score) ? b.hot_score : 0;
        return sb - sa;
      });
    } else {
      sorted.sort((a, b) => pubEpoch(b.published_at) - pubEpoch(a.published_at));
    }

    return sorted;
  }, [query, sourceFilter, categoryFilter, sortBy, trends]);

  const showCount = filteredTrends.length;
  const hasActiveFilter = query || sourceFilter !== "all" || categoryFilter !== "all" || sortBy !== "hot";

  function clearAll() {
    setQuery("");
    setSourceFilter("all");
    setCategoryFilter("all");
    setSortBy("hot");
  }

  // Date change handler — navigate to ?date=YYYY-MM-DD
  function handleDateChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    if (val === currentDate || (!val && !currentDate)) return;
    const url = val ? `/?date=${val}` : "/";
    window.location.href = url;
  }

  // Build sorted date options (newest first)
  const sortedDates = useMemo(() => {
    return [...availableDates].sort().reverse();
  }, [availableDates]);

  return (
    <div className="space-y-6">
      {/* ── Top bar: Date selector + overall health ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Date selector */}
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500 dark:text-gray-400">📅 日期</span>
          {sortedDates.length > 0 ? (
            <select
              value={currentDate ?? ""}
              onChange={handleDateChange}
              disabled={sortedDates.length <= 1}
              className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {sortedDates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-gray-400">—</span>
          )}
        </div>

        {/* Overall health badge */}
        <div className="flex items-center gap-1 text-sm">
          <span title={`整体状态: ${statusLabel(health.overall)}`}>
            {health.overall ? statusEmoji(health.overall) : "⚪"} 运行
            {health.overall ? statusLabel(health.overall) : "未知"}
          </span>
        </div>
      </div>

      {/* ── Collapsible health panel ── */}
      <div className="rounded-xl border border-gray-200/60 dark:border-gray-800/60 overflow-hidden">
        <button
          type="button"
          onClick={() => setHealthOpen(!healthOpen)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors"
        >
          <span className="font-medium">{healthOpen ? "▼" : "▶"} 数据源健康状态</span>
          <span className="text-xs text-gray-400">
            {health.sources.length} 个数据源
          </span>
        </button>
        {healthOpen && (
          <div className="px-4 pb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {health.sources.map((s) => (
              <div
                key={s.source_id}
                className="flex items-center justify-between rounded-lg bg-gray-50 dark:bg-gray-900/50 px-3 py-2 text-xs"
              >
                <div className="flex items-center gap-2">
                  <span>{statusEmoji(s.status)}</span>
                  <span className="font-medium text-gray-700 dark:text-gray-300">
                    {s.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                  <span>{statusLabel(s.status)}</span>
                  {s.item_count > 0 && <span>({s.item_count} 条)</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Search bar + controls ── */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 max-w-md">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索标题、摘要、GitHub 仓库..."
            className="w-full px-4 py-2.5 rounded-xl border border-gray-300 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500 transition-shadow"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-lg leading-none"
              aria-label="清空搜索"
            >
              &times;
            </button>
          )}
        </div>

        <div className="flex items-center gap-3 text-sm shrink-0">
          <span className="text-gray-500 dark:text-gray-400">
            显示 {showCount} / {totalCount} 条
          </span>
          {hasActiveFilter && (
            <button
              type="button"
              onClick={clearAll}
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              清空筛选
            </button>
          )}
        </div>
      </div>

      {/* ── Filter row ── */}
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500 dark:text-gray-400 mr-1">数据源</span>
          <FilterBtn label="全部" active={sourceFilter === "all"} onClick={() => setSourceFilter("all")} />
          <FilterBtn label="arXiv" active={sourceFilter === "arxiv"} onClick={() => setSourceFilter("arxiv")} />
          <FilterBtn label="GitHub" active={sourceFilter === "github"} onClick={() => setSourceFilter("github")} />
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500 dark:text-gray-400 mr-1">分类</span>
          <FilterBtn label="全部" active={categoryFilter === "all"} onClick={() => setCategoryFilter("all")} />
          <FilterBtn label="AI 研究" active={categoryFilter === "ai_research"} onClick={() => setCategoryFilter("ai_research")} />
          <FilterBtn label="开源项目" active={categoryFilter === "opensource"} onClick={() => setCategoryFilter("opensource")} />
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-gray-500 dark:text-gray-400 mr-1">排序</span>
          <FilterBtn label="最热" active={sortBy === "hot"} onClick={() => setSortBy("hot")} />
          <FilterBtn label="最新" active={sortBy === "latest"} onClick={() => setSortBy("latest")} />
        </div>
      </div>

      {/* ── Results grid ── */}
      {showCount === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center">
          <p className="text-base font-medium text-gray-500 dark:text-gray-400">
            未找到匹配的热点
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-2 mb-4">
            试试调整搜索关键词或筛选条件
          </p>
          {hasActiveFilter && (
            <button
              type="button"
              onClick={clearAll}
              className="px-4 py-2 rounded-lg bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 text-sm font-medium hover:bg-indigo-200 dark:hover:bg-indigo-800/60 transition-colors"
            >
              清空所有筛选
            </button>
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredTrends.map((t) => (
            <TrendCard key={t.id} trend={t} />
          ))}
        </div>
      )}
    </div>
  );
}
