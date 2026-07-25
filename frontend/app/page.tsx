// Daily Trend Radar — 首页
// Server Component：读取 data/ JSON 并传递给 Client Component 实现交互
// 搜索/筛选/排序逻辑在 TrendExplorer 中处理

import { createRepository } from "../lib/repositories/json-file-repository";
import TrendExplorer from "./components/TrendExplorer";

export const revalidate = 86400; // 24h ISR

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

  // Merge all trends into a single array for client-side exploration
  const allTrends: import("../lib/types").Trend[] = [];
  if (latest) {
    for (const block of Object.values(latest.categories)) {
      allTrends.push(...block.items);
    }
  }
  const totalItems = allTrends.length;

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
            {dateStr && (
              <span className="text-gray-500 dark:text-gray-400 hidden sm:inline">
                📅 {dateStr}
              </span>
            )}
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
          <TrendExplorer trends={allTrends} />
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
