// Daily Trend Radar — 首页
// 显示 AI 研究（arXiv）与开源项目（GitHub）每日热点数据
// Server Component：直接通过 DataRepository 读取 data/ JSON，无需后端 API

import { createRepository } from "../lib/repositories/json-file-repository";
import type { Trend } from "../lib/types";

export const revalidate = 86400; // 24h ISR

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

// ---------------------------------------------------------------------------
// TrendCard
// ---------------------------------------------------------------------------

function TrendCard({ trend }: { trend: Trend }) {
  const { source_id, metadata } = trend;
  const md = metadata ?? {};

  // GitHub metadata helpers
  const stars = md["stars"];
  const forks = md["forks"];
  const language = md["language"];
  const hasGithubMeta = source_id === "github";

  // arXiv metadata helpers
  const authors = source_id === "arxiv" ? safeArr(md["authors"]) : [];
  const categories = source_id === "arxiv" ? safeArr(md["categories"]) : [];
  const displayAuthors = authors.slice(0, 3);
  const extraAuthorCount = authors.length - 3;

  // Hot score display
  const hs = trend.hot_score;
  const hsValid = typeof hs === "number" && !isNaN(hs);

  return (
    <div className="glass-card rounded-xl p-5 flex flex-col gap-3">
      {/* Title + source badge row */}
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

      {/* Summary */}
      {trend.summary && (
        <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400 line-clamp-3">
          {trend.summary.length > 300
            ? trend.summary.slice(0, 300) + "…"
            : trend.summary}
        </p>
      )}

      {/* Metadata row */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* GitHub metadata */}
        {hasGithubMeta && (
          <>
            <span className="meta-tag">
              ⭐ {stars !== null && stars !== undefined ? safeStr(stars) : "—"}
            </span>
            <span className="meta-tag">
              🍴 {forks !== null && forks !== undefined ? safeStr(forks) : "—"}
            </span>
            <span className="meta-tag">
              {language !== null && language !== undefined
                ? safeStr(language)
                : "—"}
            </span>
          </>
        )}

        {/* arXiv metadata */}
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

        {/* Published time */}
        <span className="meta-tag ml-auto">{formatTime(trend.published_at)}</span>
      </div>

      {/* Hot score bar */}
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
// Section
// ---------------------------------------------------------------------------

function TrendSection({
  title,
  icon,
  trends,
  emptyMsg,
}: {
  title: string;
  icon: string;
  trends: Trend[];
  emptyMsg: string;
}) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-5">
        <span className="text-2xl">{icon}</span>
        <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
          {title}
        </h2>
        <span className="text-sm text-gray-500 dark:text-gray-400 ml-auto">
          {trends.length > 0 ? `${trends.length} 条热点` : ""}
        </span>
      </div>

      {trends.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center text-gray-500 dark:text-gray-400">
          {emptyMsg}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {trends.map((t) => (
            <TrendCard key={t.id} trend={t} />
          ))}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function Home() {
  const repo = createRepository();
  const [latest, health] = await Promise.all([
    repo.getLatest(),
    repo.getHealth(),
  ]);

  const dateStr = latest?.date ?? null;

  // Extract trends by category
  const aiTrends = latest?.categories?.["ai_research"]?.items ?? [];
  const githubTrends = latest?.categories?.["opensource"]?.items ?? [];
  const totalItems = aiTrends.length + githubTrends.length;

  // Source health
  const arxivHealth = health.sources.find((s) => s.source_id === "arxiv");
  const githubHealth = health.sources.find((s) => s.source_id === "github");

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* Header */}
      <header className="border-b border-gray-200/60 dark:border-gray-800/60 bg-white/50 dark:bg-gray-950/50 backdrop-blur-xl sticky top-0 z-10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold gradient-text tracking-tight">
              每日热点雷达
            </h1>
            <p className="text-xs sm:text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              AI 研究与开源项目每日热点
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs sm:text-sm">
            {/* Date */}
            {dateStr && (
              <span className="text-gray-500 dark:text-gray-400 hidden sm:inline">
                📅 {dateStr}
              </span>
            )}

            {/* Source status */}
            <div className="flex items-center gap-3">
              <span
                className={`inline-flex items-center gap-1 ${
                  arxivHealth?.status === "healthy"
                    ? "text-green-600 dark:text-green-400"
                    : "text-gray-400"
                }`}
              >
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    arxivHealth?.status === "healthy"
                      ? "bg-green-500"
                      : "bg-gray-400"
                  }`}
                />
                arXiv
              </span>
              <span
                className={`inline-flex items-center gap-1 ${
                  githubHealth?.status === "healthy"
                    ? "text-green-600 dark:text-green-400"
                    : "text-gray-400"
                }`}
              >
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    githubHealth?.status === "healthy"
                      ? "bg-green-500"
                      : "bg-gray-400"
                  }`}
                />
                GitHub
              </span>
            </div>

            {/* Total */}
            <span className="text-gray-400 dark:text-gray-500 hidden sm:inline">
              {totalItems > 0 ? `共 ${totalItems} 条` : ""}
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-8 space-y-10">
        {totalItems === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-16 text-center">
            <p className="text-lg font-medium text-gray-500 dark:text-gray-400">
              暂无热点数据
            </p>
            <p className="text-sm text-gray-400 dark:text-gray-500 mt-2">
              请先运行 Pipeline 生成数据，或确认 data/ 目录存在
            </p>
          </div>
        ) : (
          <>
            <TrendSection
              title="AI 研究热点"
              icon="🧪"
              trends={aiTrends}
              emptyMsg="暂无 AI 研究热点数据"
            />
            <TrendSection
              title="开源项目热点"
              icon="💻"
              trends={githubTrends}
              emptyMsg="暂无开源项目热点数据"
            />
          </>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200/60 dark:border-gray-800/60 mt-12">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-6 text-center text-xs text-gray-400 dark:text-gray-500">
          Daily Trend Radar · {dateStr ?? "—"} · 数据来源：arXiv API + GitHub API
        </div>
      </footer>
    </div>
  );
}
