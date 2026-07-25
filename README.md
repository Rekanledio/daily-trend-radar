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

## 项目运行模型（Local-first / Self-hosted）

> **本项目为本地运行 / Self-hosted 应用。** 你下载并安装项目后，可在**自己的电脑上独立运行**完整 Pipeline 与前端，无需任何中心化后端、云数据库或用户登录。

- **默认运行方式**：本机运行 Python Pipeline（直接访问公开互联网数据源）→ 本机生成 `data/` → 本机运行 Next.js → 浏览器 `localhost` 访问。
- **不依赖云端后端**：无中心化服务器、无云数据库、无公共 API 服务的强制依赖。
- **不需要登录**：不引入用户系统、多用户账户或中心化用户服务。
- **数据在你自己手里**：产出数据保存在你本机的 `data/` 目录，不强制上传。
- **公网部署为可选**：Vercel 等公网部署仅作个人演示 / 高级用法，不是默认路径。

> 当前项目仍处于开发阶段（阶段 0 骨架），完整 Pipeline 运行属后续阶段实现，请勿将未实现的能力误认为已完成。

## 核心目标

- 聚合真实互联网热点、AI 前沿资讯、科技资讯、开源动态。
- 提供现代化 Web UI、响应式设计、深色模式、搜索、日期筛选、历史回看。
- 数据来源可追溯、采集合规、单源失败不拖垮全站。
- 形成可运行、可部署、可长期维护并开源的完整项目。

## 技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | Next.js (App Router) + TypeScript + Tailwind CSS | 本机 `npm run dev` / `npm run start` 即可运行；Vercel 仅为可选公网部署 |
| 采集 / 处理 | Python (≥3.12) | 本机直接运行（可选 GitHub Actions），产出按日期分片的 JSON |
| 数据层 (MVP) | JSON 文件（按日期分片） | 零运维、git 版本化、可追溯、存于本机 |
| 定时 / 自动化（可选） | GitHub Actions | 维护者可选 CI；非普通用户运行必需 |
| 部署（默认本机） | 本机运行（Next.js + localhost） | 用户电脑直接跑，无需公网 |

**MVP 阶段明确不引入**：独立后端服务器、PostgreSQL、Redis、Kafka、Docker、Kubernetes、云数据库、用户登录系统。

## 当前架构

> **默认运行模型为 Local-first**：用户在本机运行 Pipeline 与 Next.js，数据存本地 `data/`，通过 `localhost` 访问（见上方「项目运行模型」一节）。下图为公网部署形态之一（可选，非默认）。

```
用户电脑（本机）
    ↓ 本地运行 Python Pipeline，直接访问公开数据源（arXiv / GitHub / 官方 RSS 等）
生成按日期分片的 JSON 数据（+ index.json + health.json，存于本机 data/）
    ↓
本机运行 Next.js（npm run dev / npm run start）
    ↓
浏览器通过 localhost 访问本地 Web UI
```

（可选公网演示形态：GitHub Actions 定时采集 + commit 数据 + Vercel 部署。）

所有数据读取经过 `DataRepository` 抽象接口，默认读本机 JSON；未来若确有需要，可平滑切换至**可选的本地 SQLite**，UI 零改动。不规划云数据库（Supabase / PostgreSQL）实现。

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
| 阶段 5 — 规模化 | （可选）本地 SQLite + 全文/语义搜索 | ⬜ 未开始 |
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
