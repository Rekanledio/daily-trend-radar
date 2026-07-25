import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "每日热点雷达 | Daily Trend Radar",
  description:
    "AI 研究与开源项目每日热点 — 真实、可追溯的每日热点聚合平台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-white text-gray-900 antialiased dark:bg-gray-950 dark:text-gray-100">
        {children}
      </body>
    </html>
  );
}
