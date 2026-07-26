// Daily Trend Radar — 首页
// Server Component：读取 data/ JSON 并传递给 Client Component 实现交互
// 支持 URL 参数 ?date=YYYY-MM-DD 浏览历史日期
// 同时加载所有可用日期的数据，供客户端进行跨日期趋势计算

import { createRepository } from "../lib/repositories/json-file-repository";
import TrendExplorer from "./components/TrendExplorer";
import type { Trend } from "../lib/types";

export const revalidate = 86400; // 24h ISR
export const dynamic = "force-dynamic";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function Home(props: {
  searchParams: Promise<{ date?: string }>;
}) {
  const params = await props.searchParams;
  const dateParam = params.date;

  const repo = createRepository();

  const [index, health] = await Promise.all([
    repo.getHistoryIndex(),
    repo.getHealth(),
  ]);

  const availableDates = index.available_dates ?? [];
  const latestDate = index.latest_date ?? null;

  let targetDate = dateParam ?? null;
  let publishedData = null;

  if (targetDate && availableDates.includes(targetDate)) {
    publishedData = await repo.getByDate(targetDate);
  }
  if (!publishedData) {
    targetDate = null;
    publishedData = await repo.getLatest();
  }

  const dateStr = publishedData?.date ?? latestDate ?? null;

  const allTrends: Trend[] = [];
  if (publishedData) {
    for (const block of Object.values(publishedData.categories)) {
      allTrends.push(...block.items);
    }
  }

  // Load historical data for trend visualization (all available dates)
  const historicalDataByDate = new Map<string, Trend[]>();
  if (availableDates.length >= 1) {
    for (const date of availableDates) {
      try {
        const data = await repo.getByDate(date);
        if (data) {
          const trends: Trend[] = [];
          for (const block of Object.values(data.categories)) {
            trends.push(...block.items);
          }
          historicalDataByDate.set(date, trends);
        }
      } catch {
        // Skip dates that fail to load
      }
    }
  }

  const totalItems = allTrends.length;
  const sourceCount = Object.keys(publishedData?.categories ?? {}).length;

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* Header */}
      <header className="border-b border-gray-200/60 dark:border-gray-800/60 bg-white/50 dark:bg-gray-950/50 backdrop-blur-xl sticky top-0 z-10">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className="text-xl sm:text-2xl font-bold gradient-text tracking-tight">
                Daily Trend Radar
              </h1>
              <p className="text-xs sm:text-sm gradient-sub mt-0.5 font-medium">
                每日 AI 与开源热点追踪
              </p>
            </div>
            <div className="flex items-center gap-4 text-xs sm:text-sm">
              {dateStr && (
                <span className="text-gray-500 dark:text-gray-400">
                  📅 {dateStr}
                </span>
              )}
              <div className="flex items-center gap-3">
                <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500" />
                  arXiv
                </span>
                <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500" />
                  GitHub
                </span>
                <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500" />
                  OpenAI
                </span>
              </div>
            </div>
          </div>
          {/* Quick stats bar */}
          <div className="flex items-center gap-4 mt-2 text-xs text-gray-400 dark:text-gray-500">
            {totalItems > 0 && (
              <span className="flex items-center gap-1">
                <span className="font-medium text-gray-600 dark:text-gray-300">{totalItems}</span> 条热点
              </span>
            )}
            {sourceCount > 0 && (
              <span className="flex items-center gap-1">
                <span className="font-medium text-gray-600 dark:text-gray-300">{sourceCount}</span> 个分类
              </span>
            )}
            <span className="text-gray-300 dark:text-gray-700">·</span>
            <span>arXiv API + GitHub API + OpenAI RSS</span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-8">
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
          <TrendExplorer
            trends={allTrends}
            currentDate={dateStr}
            availableDates={availableDates}
            latestDate={latestDate}
            health={health}
            historicalDataByDate={historicalDataByDate}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-200/60 dark:border-gray-800/60 mt-12">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-6 text-center text-xs text-gray-400 dark:text-gray-500">
          Daily Trend Radar · {dateStr ?? "—"} · 数据来源：arXiv API + GitHub API + OpenAI RSS
        </div>
      </footer>
    </div>
  );
}
