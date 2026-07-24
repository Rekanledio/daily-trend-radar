# Daily Trend Radar · 每日热点雷达

> 真实、可追溯、合法合规的每日互联网热点与前沿资讯聚合平台。

## 项目简介

Daily Trend Radar（每日热点雷达）致力于每天聚合并展示真实存在的互联网热点与前沿资讯，覆盖
综合热点、AI 前沿、科技与开源动态，并规划在未来扩展主流平台（B站 / 微博 / 抖音 / 小黑盒 / 酷安）热点。

**核心原则（产品灵魂）**：

- 所有热点必须 **真实存在**，严禁虚构新闻、热点、标题、来源或热度。
- 每条信息必须提供 **原始来源**（`original_url`），可点击查看原文。
- 每个板块最多展示 **20 条**；若真实有效数据不足，宁可少展示，绝不凑数。
- 数据采集全程 **合法合规**，遵守 `robots.txt`、API 条款、频率限制与法律法规。
- AI 仅用于基于真实来源的摘要 / 分类 / 标签，**绝不创作事实**。

## 当前项目状态

> ⚠️ **本项目处于开发阶段（阶段 0：工程骨架）**。
> 当前仓库仅包含工程脚手架与开发规范，**尚未接入任何真实生产数据**，也未实现任何业务功能。
> 请勿将未实现的能力误认为已完成功能。

## 核心目标

- 聚合真实互联网热点、AI 前沿资讯、科技资讯、开源动态。
- 提供现代化 Web UI、响应式设计、深色模式、搜索、日期筛选、历史回看。
- 数据来源可追溯、采集合规、单源失败不拖垮全站。
- 形成可运行、可部署、可长期维护并开源的完整项目。

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | Next.js (App Router) + TypeScript + Tailwind CSS | 静态优先，Vercel 部署 |
| 采集 / 处理 | Python (≥3.12) | 跑在 GitHub Actions，产出按日期分片的 JSON |
| 数据层 (MVP) | JSON 文件（按日期分片） | 零运维、git 版本化、可追溯 |
| 定时 / 自动化 | GitHub Actions | cron + 手动触发 |
| 部署 | Vercel | 前端静态托管 |

**MVP 阶段明确不引入**：独立后端服务器、PostgreSQL、Redis、Kafka、Docker、Kubernetes。

## 当前架构

```
Python 数据采集与处理
    ↓
GitHub Actions（定时 cron + 手动 workflow_dispatch）
    ↓
生成按日期分片的 JSON 数据（+ index.json + health.json）
    ↓
GitHub Repository 保存与版本化（git 历史 = 历史热点）
    ↓
Next.js App Router + TypeScript + Tailwind
    ↓
Vercel 部署展示（ISR 增量再生成）
```

所有数据读取经过 `DataRepository` 抽象接口，未来可平滑切换至 Supabase / PostgreSQL，UI 零改动。

## 项目目录

```
daily-trend-radar/
├── frontend/              # Next.js 前端（App Router + TS + Tailwind）
├── pipeline/              # Python 采集与处理 Pipeline（阶段 0 仅骨架）
├── config/                # 统一数据源配置（sources.yaml）
├── data/                  # 产出数据（index.json / health.json / sources_state.json）
├── tests/                 # 根级测试目录（占位）
├── scripts/               # 辅助脚本目录（占位）
├── docs/                  # 规划 / 架构 / 合规文档
├── PROJECT_RULES.md       # 最高级开发规范（所有开发必须遵守）
├── README.md              # 本文件
├── LICENSE                # 开源协议（MIT）
├── .gitignore
└── .env.example           # 环境变量样例（不含真实密钥）
```

> 目录命名：本仓库统一使用 `frontend/`（前端）与 `pipeline/`（采集处理）；`docs/ARCHITECTURE_REVIEW_v2.md`
> 与 `docs/PROJECT_PLAN.md` 中的历史 `web/` / `collectors/` 命名已在阶段 0 第三轮同步为 `frontend/` / `pipeline/`。

## Roadmap

| 阶段 | 目标 | 状态 |
|---|---|---|
| 阶段 0 — 地基建设 | 工程骨架、开发规范、目录结构 | 🟡 进行中 |
| 阶段 1 — MVP 数据闭环 | 4 个合法源采集 → 标准化 → 校验 → 去重 → 产出 JSON | ⬜ 未开始 |
| 阶段 2 — 前端上线 | 三板块 UI + 深色/响应式 + 搜索 + 日期筛选 + /health | ⬜ 未开始 |
| 阶段 3 — 社交/监控 | B站/微博/酷安/小黑盒（带降级）+ 健康告警 | ⬜ 未开始 |
| 阶段 4 — 数据智能 | AI 摘要/分类/标签 + 事件聚合 + 进阶去重 | ⬜ 未开始 |
| 阶段 5 — 规模化 | 迁移 Supabase + 全文/语义搜索 | ⬜ 未开始 |
| 阶段 6 — 长期扩展 | 抖音（合规时）+ 更多源 + 日报/API | ⬜ 未开始 |

## 本地开发说明

> 前置要求：Node.js ≥ 18（推荐 22+）、Python ≥ 3.12。

**前端**：

```bash
cd frontend
npm install
npm run dev      # 本地开发 http://localhost:3000
npm run build    # 生产构建
npm run typecheck
```

**Pipeline（阶段 0 仅骨架，暂无业务命令）**：

```bash
cd pipeline
python -m venv .venv && source .venv/bin/activate   # 或使用托管 Python 环境
pip install -e ".[dev]"
pytest
```

> 当前 Pipeline 未实现真实采集；请勿在此阶段连接任何外部 API 或 RSS。

## License

本项目正式采用 **MIT License**（见 `LICENSE`）。
