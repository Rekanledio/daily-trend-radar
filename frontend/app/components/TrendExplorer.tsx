"use client";

import { useState, useMemo } from "react";
import type { Trend, HealthSnapshot } from "@/lib/types";
import {
  buildHistoryMap,
  getTrendHistory,
  renderSparkline,
} from "@/lib/trend-utils";

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

function statusBorderColor(status: string | null): string {
  switch (status) {
    case "healthy": return "border-l-green-500";
    case "degraded": return "border-l-yellow-500";
    case "failed": return "border-l-red-500";
    case "disabled": return "border-l-gray-400";
    default: return "border-l-gray-300";
  }
}

/** Format number with K/M suffix for display. */
function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SourceFilter = "all" | "arxiv" | "github" | "openai_blog";
type CategoryFilter = "all" | "ai_research" | "opensource" | "ai_official";
type SortMode = "hot" | "latest";

// ---------------------------------------------------------------------------
// TrendCard
// ---------------------------------------------------------------------------

function TrendCard({
  trend,
  historyMap,
  allDates,
  currentDate,
}: {
  trend: Trend;
  historyMap: Map<string, Map<string, number | null>>;
  allDates: string[];
  currentDate: string | null;
}) {
  const { source_id, metadata } = trend;
  const md = metadata ?? {};

  // Compute historical trend data
  const trendHistory = useMemo(
    () => getTrendHistory(trend.id, historyMap, allDates, currentDate),
    [trend.id, historyMap, allDates, currentDate]
  );
  const validScores = trendHistory.points
    .filter((p) => p.score !== null && p.score !== undefined)
    .map((p) => p.score!);

  const direction = trendHistory.direction;
  const change = trendHistory.change;
  const sparklineHtml = useMemo(
    () => renderSparkline(validScores, 48, 16),
    [validScores]
  );

  const directionEmoji =
    direction === "up" ? "📈" :
    direction === "down" ? "📉" :
    direction === "stable" ? "➡️" :
    null;

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
    <div className="glass-card rounded-xl p-5 flex flex-col gap-3 relative">
      {/* Top row: badge + external link */}
      <div className="flex items-center justify-between">
        <span
          className={`source-badge ${
            source_id === "arxiv"
              ? "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300"
              : source_id === "openai_blog"
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
              : "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300"
          }`}
        >
          {source_id === "arxiv" ? "arXiv" : source_id === "openai_blog" ? "OpenAI" : "GitHub"}
        </span>
        <a
          href={trend.original_url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="ext-link"
          title="打开原文"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
            <polyline points="15 3 21 3 21 9" />
            <line x1="10" y1="14" x2="21" y2="3" />
          </svg>
        </a>
      </div>

      {/* Title */}
      <a
        href={trend.original_url || "#"}
        target="_blank"
        rel="noopener noreferrer"
        className="text-base font-semibold leading-snug link-hover text-gray-900 dark:text-gray-100 no-underline"
      >
        {trend.title || "—"}
      </a>

      {/* Summary */}
      {trend.summary && (
        <p className="text-sm leading-relaxed text-gray-500 dark:text-gray-400 line-clamp-3">
          {trend.summary.length > 250
            ? trend.summary.slice(0, 250) + "…"
            : trend.summary}
        </p>
      )}

      {/* Metadata + time row */}
      <div className="flex flex-wrap gap-1.5 items-center">
        {hasGithubMeta && (
          <>
            <span className="meta-tag">
              ⭐ {stars !== null && stars !== undefined ? fmtCount(Number(stars)) : "—"}
            </span>
            <span className="meta-tag">
              🍴 {forks !== null && forks !== undefined ? fmtCount(Number(forks)) : "—"}
            </span>
            {language !== null && language !== undefined && (
              <span className="meta-tag">{safeStr(language)}</span>
            )}
          </>
        )}

        {source_id === "arxiv" && (
          <>
            {displayAuthors.length > 0 && (
              <span className="meta-tag max-w-[180px] truncate" title={authors.join(", ")}>
                {displayAuthors.join(", ")}
                {extraAuthorCount > 0 ? ` +${extraAuthorCount}` : ""}
              </span>
            )}
            {categories.length > 0 && (
              <span className="meta-tag">{safeStr(categories[0])}</span>
            )}
          </>
        )}

        <span className="meta-tag ml-auto">{formatTime(trend.published_at)}</span>
      </div>

      {/* Hot score bar */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold shrink-0 tabular-nums"
          style={{ color: hsValid ? (hs >= 50 ? "#ef4444" : hs >= 25 ? "#eab308" : "#22c55e") : undefined }}
        >
          {hsValid ? hs.toFixed(1) : "—"}
        </span>
        <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          {hsValid && (
            <div
              className="hot-bar"
              style={{ width: `${Math.max(1, hs)}%` }}
            />
          )}
        </div>
        <span className="text-[10px] text-gray-400 dark:text-gray-500 shrink-0">热度</span>
      </div>

      {/* AI Summary */}
      {trend.ai_summary && (
        <div className="mt-1 pt-3 border-t border-gray-100 dark:border-gray-800 space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 dark:text-indigo-400">
            <span>🤖</span>
            <span>AI Summary</span>
          </div>
          <p className="text-xs leading-relaxed text-gray-600 dark:text-gray-400">
            {trend.ai_summary.summary}
          </p>
          <p className="text-xs leading-relaxed text-gray-500 dark:text-gray-400 italic">
            {trend.ai_summary.why_it_matters}
          </p>
          {trend.ai_summary.keywords.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {trend.ai_summary.keywords.map((kw) => (
                <span
                  key={kw}
                  className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-300"
                >
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Trend Score */}
      {trend.trend_score != null && (
        <div className="mt-1 pt-3 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-medium">
              <span>🔥</span>
              <span 
                className={`px-1.5 py-0.5 rounded text-[11px] font-bold ${
                  trend.impact_level === "critical" 
                    ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300"
                    : trend.impact_level === "high"
                    ? "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300"
                    : trend.impact_level === "medium"
                    ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300"
                    : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                }`}
              >
                {trend.impact_level}
              </span>
            </div>
            <span className="text-xs font-bold text-gray-700 dark:text-gray-300">
              {trend.trend_score.toFixed(1)} / 100
            </span>
          </div>
          <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden mt-1.5">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, Math.max(0, trend.trend_score))}%`,
                background: `linear-gradient(90deg, ${
                  trend.trend_score >= 80 ? "#ef4444" :
                  trend.trend_score >= 60 ? "#f97316" :
                  trend.trend_score >= 40 ? "#eab308" :
                  "#6b7280"
                }, ${
                  trend.trend_score >= 80 ? "#dc2626" :
                  trend.trend_score >= 60 ? "#ea580c" :
                  trend.trend_score >= 40 ? "#ca8a04" :
                  "#4b5563"
                })`,
              }}
            />
          </div>
          {trend.score_reason && trend.score_reason.length > 0 && (
            <details className="group mt-1.5">
              <summary className="text-[11px] text-gray-400 dark:text-gray-500 cursor-pointer hover:text-gray-600 dark:hover:text-gray-300 select-none">
                Details
              </summary>
              <ul className="mt-1 space-y-0.5">
                {trend.score_reason.map((r, i) => (
                  <li key={i} className="text-[11px] text-gray-400 dark:text-gray-500">
                    {r}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      {/* Historical Trend */}
      {direction !== "insufficient_data" && (
        <div className="mt-1 pt-3 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs">
              {directionEmoji && <span>{directionEmoji}</span>}
              <span className={`text-xs font-medium ${
                direction === "up" ? "text-green-600 dark:text-green-400" :
                direction === "down" ? "text-red-500 dark:text-red-400" :
                "text-gray-500 dark:text-gray-400"
              }`}>
                {direction === "up" ? `上升 +${change}` :
                 direction === "down" ? `下降 ${change}` :
                 direction === "stable" ? "稳定" : ""}
              </span>
            </div>
            {sparklineHtml && (
              <div
                className="shrink-0"
                dangerouslySetInnerHTML={{ __html: sparklineHtml }}
              />
            )}
          </div>
          {validScores.length >= 2 && (
            <div className="flex items-center gap-1 mt-1.5">
              <span className="text-[10px] text-gray-400 dark:text-gray-500">近 {validScores.length} 天</span>
              <div className="flex items-center gap-0.5 ml-auto">
                {validScores.map((s, i) => {
                  const barH = Math.max(3, (s / 100) * 10);
                  return (
                    <div
                      key={i}
                      className="w-1.5 rounded-full bg-gray-300 dark:bg-gray-600"
                      style={{ height: `${barH}px` }}
                      title={`${trendHistory.points[i]?.date ?? "?"}: ${s.toFixed(1)}`}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
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
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${
        active
          ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300 ring-1 ring-indigo-300 dark:ring-indigo-700 shadow-sm"
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
  historicalDataByDate,
}: {
  trends: Trend[];
  currentDate: string | null;
  availableDates: string[];
  latestDate: string | null;
  health: HealthSnapshot;
  historicalDataByDate: Map<string, Trend[]>;
}) {
  const totalCount = trends.length;
  const [healthOpen, setHealthOpen] = useState(false);

  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [sortBy, setSortBy] = useState<SortMode>("hot");

  // Build history map for cross-date trend matching
  const historyMap = useMemo(() => {
    return buildHistoryMap(historicalDataByDate);
  }, [historicalDataByDate]);

  // Filter + sort (unchanged)
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

  function handleDateChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    if (val === currentDate || (!val && !currentDate)) return;
    const url = val ? `/?date=${val}` : "/";
    window.location.href = url;
  }

  const sortedDates = useMemo(() => {
    return [...availableDates].sort().reverse();
  }, [availableDates]);

  const enabledSources = health.sources.filter(s => s.status !== "disabled");

  return (
    <div className="space-y-6">
      {/* ── Date selector + overall health ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
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
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          ) : (
            <span className="text-gray-400">—</span>
          )}
        </div>

        <div className="flex items-center gap-2 text-sm">
          {health.overall && (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 text-xs font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
              {statusLabel(health.overall)}
            </span>
          )}
        </div>
      </div>

      {/* ── Health panel (collapsible, card-based) ── */}
      <div className="rounded-xl border border-gray-200/60 dark:border-gray-800/60 overflow-hidden bg-white/40 dark:bg-gray-900/40">
        <button
          type="button"
          onClick={() => setHealthOpen(!healthOpen)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-900/60 transition-colors"
        >
          <span className="font-medium flex items-center gap-2">
            <span className="text-xs">{healthOpen ? "▼" : "▶"}</span>
            数据源健康状态
          </span>
          <span className="text-xs text-gray-400">{health.sources.length} 个数据源</span>
        </button>
        {healthOpen && (
          <div className="px-4 pb-4 grid gap-2 sm:grid-cols-2">
            {health.sources.map((s) => (
              <div
                key={s.source_id}
                className={`health-card bg-gray-50 dark:bg-gray-900/50 ${statusBorderColor(s.status)}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span>{statusEmoji(s.status)}</span>
                    <span className="font-medium text-gray-700 dark:text-gray-300">
                      {s.name}
                    </span>
                  </div>
                  <span className={`text-xs font-medium ${
                    s.status === "healthy" ? "text-green-600 dark:text-green-400" :
                    s.status === "disabled" ? "text-gray-400" :
                    s.status === "failed" ? "text-red-500" :
                    s.status === "degraded" ? "text-yellow-600" : ""
                  }`}>
                    {statusLabel(s.status)}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
                  {s.item_count > 0 && <span>{s.item_count} 条数据</span>}
                  {s.last_success && <span>最近更新 {formatTime(s.last_success)}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Search bar ── */}
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

      {/* ── Filter row (responsive) ── */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-gray-500 dark:text-gray-400 mr-1">数据源</span>
          <FilterBtn label="全部" active={sourceFilter === "all"} onClick={() => setSourceFilter("all")} />
          <FilterBtn label="arXiv" active={sourceFilter === "arxiv"} onClick={() => setSourceFilter("arxiv")} />
          <FilterBtn label="GitHub" active={sourceFilter === "github"} onClick={() => setSourceFilter("github")} />
          <FilterBtn label="OpenAI" active={sourceFilter === "openai_blog"} onClick={() => setSourceFilter("openai_blog")} />
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-gray-500 dark:text-gray-400 mr-1">分类</span>
          <FilterBtn label="全部" active={categoryFilter === "all"} onClick={() => setCategoryFilter("all")} />
          <FilterBtn label="AI 研究" active={categoryFilter === "ai_research"} onClick={() => setCategoryFilter("ai_research")} />
          <FilterBtn label="开源项目" active={categoryFilter === "opensource"} onClick={() => setCategoryFilter("opensource")} />
          <FilterBtn label="AI 官方" active={categoryFilter === "ai_official"} onClick={() => setCategoryFilter("ai_official")} />
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
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
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filteredTrends.map((t) => (
            <TrendCard
              key={t.id}
              trend={t}
              historyMap={historyMap}
              allDates={sortedDates}
              currentDate={currentDate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
