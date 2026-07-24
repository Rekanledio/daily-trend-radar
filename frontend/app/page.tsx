// Minimal Server Component smoke-check for the DataRepository.
// Purpose of stage-1 round 1 ONLY: prove the repo can read data
// server-side. NOT the real UI (that comes later).
//
// Data updates daily, so cache for 24h (ISR). A new deploy (or a
// Vercel deploy hook fired by the data-update Action) is what ships
// fresh data to production — see docs/DATA_CONTRACT.md §8 / round notes.

import { createRepository } from "../lib/repositories/json-file-repository";

export const revalidate = 86400; // 24h

function healthLabel(overall: string | null): string {
  if (overall === null) return "未运行（初始化态）";
  return overall;
}

export default async function Home() {
  const repo = createRepository();
  const [latest, health] = await Promise.all([
    repo.getLatest(),
    repo.getHealth(),
  ]);

  const totalItems = latest
    ? Object.values(latest.categories).reduce((sum, b) => sum + b.items.length, 0)
    : 0;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-8 py-16 text-center">
      <h1 className="text-3xl font-bold tracking-tight">Daily Trend Radar</h1>
      <p className="text-lg text-gray-600 dark:text-gray-300">每日热点雷达</p>

      <section className="mt-4 rounded-2xl border border-gray-200 px-6 py-4 text-left text-sm dark:border-gray-700">
        <h2 className="mb-2 font-semibold">数据通道自检（Repository）</h2>
        <ul className="space-y-1 text-gray-700 dark:text-gray-300">
          <li>最新数据日期：<code>{latest?.date ?? "暂无（尚未产出）"}</code></li>
          <li>当前数据条数：<code>{totalItems}</code></li>
          <li>健康状态：<code>{healthLabel(health.overall)}</code></li>
        </ul>
      </section>

      <p className="max-w-md text-sm text-gray-500 dark:text-gray-400">
        项目工程骨架与数据闭环已就绪（阶段 1）。UI 正式设计尚未开始。
      </p>
    </main>
  );
}
