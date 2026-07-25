# Daily Trend Radar

每日 AI 与开源热点雷达

> 基于 Python Pipeline + Next.js 的真实数据热点聚合平台。

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=fff)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=next.js&logoColor=fff)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=fff)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=fff)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=fff)
![arXiv API](https://img.shields.io/badge/arXiv-API-B31B1B?logo=arxiv&logoColor=fff)
![GitHub API](https://img.shields.io/badge/GitHub-API-181717?logo=github&logoColor=fff)

---

## Technical Highlights

- **Adapter Registry** — 统一的源注册机制，`build_registry` 仅实例化已启用的数据源。
- **多数据源 Pipeline** — 配置驱动，支持 arXiv / GitHub / RSS 格式的数据采集、标准化、校验、发布。
- **Local-first 数据架构** — 所有数据存储于本机 `data/` 目录，按日期分片，不入 Git 仓库，无需云端后端。
- **数据契约校验** — Python 端 JSON Schema 校验 + TypeScript 端运行时守卫，双端数据完整性保障。
- **Health Monitoring** — 每次 Pipeline 运行写入 `health.json` / `sources_state.json`，前端实时展示各源健康状态。
- **Next.js Dashboard** — 支持搜索、数据源筛选、分类筛选、热度/最新排序、历史日期浏览、健康面板。

## Screenshot

> 截图待补充。运行以下命令可在本地查看完整 UI：
>
> ```bash
> cd frontend && npm run dev
> ```
>
> 然后浏览器访问 `http://localhost:3000`。

---

## 项目简介

Daily Trend Radar（每日热点雷达）致力于每天聚合并展示真实存在的互联网热点与前沿资讯，覆盖 AI 前沿、科技与开源动态。

**核心原则（产品灵魂）**：

- 所有热点必须 **真实存在**，严禁虚构新闻、热点、标题、来源或热度。
- 每条信息必须提供 **原始来源**（`original_url`），可点击查看原文。
- 每个板块最多展示 **20 条**；若真实有效数据不足，宁可少展示，绝不凑数。
- 数据采集全程 **合法合规**，遵守 `robots.txt`、API 条款、频率限制与法律法规。

## 当前项目状态

> ✅ **Pipeline + Dashboard 全链路已闭环。**

当前已具备：Adapter Registry、arXiv / GitHub / RSS 三类 Adapter、`config/sources.yaml` 统一配置、可运行 CLI、Local-first 数据写入与校验、Next.js 完整前端（搜索 / 筛选 / 排序 / 日期浏览 / 健康面板）。

**注意**：
- AI 摘要 / 分类 / 标签**尚未接入**（`ai_enabled=False`）。
- 更多数据源（社交平台等）**尚未接入**。
- 生产级自动定时采集**尚未配置**。

## 已实现能力

- **Adapter Registry**：统一注册表，`build_registry` 仅实例化 `enabled: true` 的源。
- **arXiv Adapter**：官方 Atom API 采集，遵守 3s 间隔，按 `submittedDate` 倒序。
- **GitHub Adapter**（已启用）：官方 Search Repositories API，metadata 含 stars/forks/language/pushed_at 等。
- **RSS Adapter**：通用 RSS/Atom 解析（用于 OpenAI Blog 等）。
- **Next.js Dashboard**：搜索（标题 / 摘要 / GitHub 仓库名）、数据源筛选（全部 / arXiv / GitHub）、分类筛选（全部 / AI 研究 / 开源项目）、排序（最热 / 最新）、日期浏览、健康状态面板。
- **Local-first `data/`**：按 `data/YYYY/MM/YYYY-MM-DD.json` 分片 + `index.json` / `health.json` / `sources_state.json`。
- **Pipeline CLI**：`--source`、`--dry-run`、`--config`、`--data-dir`、`--date` 等参数。
- **248 项 pytest** 离线测试覆盖。

## 当前默认数据源

| 数据源 | 状态 | 说明 |
|---|---|---|
| `arxiv`（arXiv Atom API） | ✅ 已启用 | 每日 20 条 AI 研究论文 |
| `github`（GitHub Search API） | ✅ 已启用 | 每日 20 个热门开源仓库 |
| `openai_blog`（OpenAI Blog RSS） | ⛔ 默认关闭 | Adapter 已实现，待启用 |

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Next.js 15 (App Router) + React 19 + TypeScript 5.7 + Tailwind CSS 4 |
| 采集 / 处理 | Python ≥3.12 |
| 数据层 | 本地 JSON 文件（按日期分片） |
| 部署 | 本机运行（`npm run dev` / `npm run start`），Vercel 可选 |

## 项目目录

```
daily-trend-radar/
├── frontend/          # Next.js 前端
├── pipeline/          # Python 采集 Pipeline
├── config/            # 数据源配置 (sources.yaml)
├── data/              # 产出数据（仅本机，不入仓）
├── schemas/           # JSON Schema 契约
├── docs/              # 架构 / 设计文档
└── README.md
```

## 本地开发

**前端**：

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
npm run build
npm run typecheck
npm test           # 11 项前端测试
```

**Pipeline**：

```bash
cd pipeline
pip install -e ".[dev]"
pytest             # 248 项离线测试
PYTHONPATH=src python -m pipeline --help
PYTHONPATH=src python -m pipeline --source arxiv --dry-run
PYTHONPATH=src python -m pipeline   # 运行全部已启用的源
```

## Roadmap

### ✅ 已完成

- Pipeline 核心（Adapter Registry / CLI / 数据契约）
- arXiv 数据接入（20 条 / 日）
- GitHub 数据接入（20 条 / 日），含 metadata（stars/forks/language）
- RSS Adapter（OpenAI Blog）
- Next.js Dashboard（搜索 / 筛选 / 排序 / 日期浏览 / 健康面板）
- Health Monitoring（`health.json` + 前端展示）
- 248 项 Python 测试 + 11 项前端测试

### 🔮 未来规划

- 更多数据源接入（社交平台等）
- AI 摘要 / 分类 / 标签
- 生产级自动定时采集（GitHub Actions）
- 本地 SQLite + 全文搜索

## License

本项目采用 **MIT License**（见 `LICENSE`）。
