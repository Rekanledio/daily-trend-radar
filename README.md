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

> ✅ **本地 Pipeline 基础闭环已完成（阶段 1 数据闭环：核心实现 + 真实验证）**。
>
> 当前已具备：Adapter Registry、arXiv / GitHub / RSS 三类真实 Adapter、`config/sources.yaml` 统一配置、`SourceConfig → Registry → Adapter → Pipeline` 链路、可运行 CLI、Local-first `data/` 本地数据写入与 `PublishedData` 校验。
> 其中 **arXiv 真实单源抓取已成功跑通**，真实数据已写入本机 `data/2026/07/2026-07-25.json`（20 条真实趋势 / 20 条真实事件），并通过 GitHub 提交与远程仓库（`origin/master`）同步。
>
> ⚠️ **当前仍不是完整的最终产品**：
> - AI 摘要 / 分类 / 标签**尚未接入**（本轮 `ai_enabled=False`，使用 `NullAIProcessor` 透传）。
> - 前端完整 UI（三板块展示 / 搜索 / 日期筛选 / `/health` 页）**尚未实现**（前端脚手架存在，但未对接真实数据）。
> - 更多数据源（社交平台等）**尚未接入**。
> - 生产级自动定时采集（GitHub Actions 定时任务）**尚未配置**。
> - `github` / `openai_blog` 两个 Adapter 已实现，但**默认关闭**，需人工审查后再启用。
>
> 请勿将规划中的能力误认为已完成功能。

## 已实现能力

以下能力已在当前 `HEAD`（commit `750ff7e`）中**真实落地并通过测试**，非规划描述：

- **Adapter Registry**：统一注册表，`build_registry` 仅实例化 `enabled: true` 的源。
- **arXiv Adapter**：官方 Atom API 采集，遵守 3s 间隔，按 `submittedDate` 倒序。
- **GitHub Adapter**：官方 Search Repositories API，单源失败隔离。
- **RSS Adapter**：通用 RSS/Atom 解析（用于 OpenAI Blog 等）。
- **`config/sources.yaml`**：统一静态数据源配置（开关 / 条数 / 频率 / 合规字段）。
- **`SourceConfig → Registry → Adapter → Pipeline` 链路**：端到端已连通。
- **Pipeline CLI**（`python -m pipeline`）：配置驱动的多源本地运行器。
- **CLI 参数**：`--source`、`--dry-run`（= `--no-write`）、`--config`、`--data-dir`、`--date`。
- **Local-first `data/` 本地数据写入**：按 `data/YYYY/MM/YYYY-MM-DD.json` 分片 + `index.json` / `health.json` / `sources_state.json`。
- **`PublishedData` 校验**：发布前本地契约校验，失败拒绝写入。
- **`data/` Git 忽略**：根 `.gitignore` 的 `/data/` 规则，本机数据不入仓。
- **测试**：`pytest` 共 237 项，覆盖 Adapter 集成链路、校验、去重、单源失败隔离等（离线 fixture，不调用真实 API）。
- **arXiv 真实单源抓取已成功**：已本地真实运行并产出数据。
- **真实数据已写入本机** `data/2026/07/2026-07-25.json`（20 真实趋势 / 20 真实事件）。
- **GitHub 与 RSS Adapter 已实现但默认关闭**：代码完成，待人工审查后启用。

## 当前默认数据源

| 数据源 | 状态 | 说明 |
|---|---|---|
| `arxiv`（arXiv 官方 Atom API） | ✅ 启用 | `config/sources.yaml` 中 `enabled: true`；已真实单源验证 |
| `github`（GitHub Search API） | ⛔ 默认关闭 | Adapter 已实现，但 `enabled: false`；待人工审查后开启 |
| `openai_blog`（OpenAI Blog RSS） | ⛔ 默认关闭 | 通用 RSS Adapter 已实现，但 `enabled: false`；待真实冒烟与人工审查后开启 |

> 说明：`github` / `openai_blog` 的 Adapter 代码**已经完成**，出于合规与稳定性审查考虑默认不启用。
> 如需启用，将 `config/sources.yaml` 中对应 `enabled` 改为 `true`（属配置修改与人工审查范畴，非默认行为）。

## 项目运行模型（Local-first / Self-hosted）

> **本项目为本地运行 / Self-hosted 应用。** 你下载并安装项目后，可在**自己的电脑上独立运行**完整 Pipeline 与前端，无需任何中心化后端、云数据库或用户登录。

- **默认运行方式**：本机运行 Python Pipeline（直接访问公开互联网数据源）→ 本机生成 `data/` → 本机运行 Next.js → 浏览器 `localhost` 访问。
- **不依赖云端后端**：无中心化服务器、无云数据库、无公共 API 服务的强制依赖。
- **不需要登录**：不引入用户系统、多用户账户或中心化用户服务。
- **数据在你自己手里**：产出数据保存在你本机的 `data/` 目录，不强制上传。
- **公网部署为可选**：Vercel 等公网部署仅作个人演示 / 高级用法，不是默认路径。

> 当前项目已完成本地 Pipeline 基础闭环（详见「当前项目状态」「已实现能力」两节），但**前端 UI 与 AI 加工仍属未实现 / 未启用**，请勿将规划中的能力误认为已完成。

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
├── pipeline/              # Python 采集与处理 Pipeline（已实现 Adapter Registry 与 arXiv/GitHub/RSS 适配器）
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

## 数据目录（Local-first 本地运行时数据）

`data/` 是**本机运行时**数据目录，**不纳入 Git 版本控制**（已被根目录 `.gitignore` 的 `/data/` 规则排除）。

典型内容：

- `data/2026/07/2026-07-25.json` —— 按日期分片的生产数据（每板块 ≤20 条真实数据，均含 `original_url`）。
- `data/index.json` —— 全局日期索引（`available_dates` 等）。
- `data/health.json` —— 各数据源最近运行的健康快照。
- `data/sources_state.json` —— 各数据源运行态（最后成功 / 错误 / 条数 / 耗时）。

> 这些数据仅存在于运行 Pipeline 的**本机**，用于 `localhost` 前端读取与历史回看；
> 它们**不会也不应**被提交到 GitHub 仓库（避免体积膨胀与第三方内容版权 / 条款风险，可追溯性由 `original_url` 保证）。

## Roadmap

### ✅ 已完成

| 阶段 | 目标 | 状态 |
|---|---|---|
| 阶段 0 — 地基建设 | 工程骨架、开发规范（PROJECT_RULES）、目录结构、CI 空跑、`.env.example` | ✅ 完成 |
| 阶段 1 — 本地数据闭环（核心实现） | Adapter Registry + arXiv/GitHub/RSS 三适配器 + `sources.yaml` + CLI + Local-first `data/` 写入 + `PublishedData` 校验 | ✅ 完成（arXiv 已真实单源验证） |

### 🟡 下一阶段（进行中 / 待开展）

| 阶段 | 目标 | 状态 |
|---|---|---|
| 启用更多数据源 | 人工审查后开启 `github` / `openai_blog`（Adapter 已实现，默认关闭） | 🟡 待人工审查 |
| 阶段 2 — 前端上线 | 三板块 UI + 深色 / 响应式 + 搜索 + 日期筛选 + `/health` | ⬜ 未开始 |
| 生产级自动定时采集 | GitHub Actions `schedule` 定时触发 Pipeline（可选） | ⬜ 未开始 |

### 🔮 未来规划（未开始，请勿误认为已完成）

| 阶段 | 目标 |
|---|---|
| 阶段 3 — 社交 / 监控 | B站 / 微博 / 酷安 / 小黑盒（带降级）+ 健康告警 |
| 阶段 4 — 数据智能 | AI 摘要 / 分类 / 标签 + 事件聚合 + 进阶去重 |
| 阶段 5 — 规模化 | （可选）本地 SQLite + 全文 / 语义搜索 |
| 阶段 6 — 长期扩展 | 抖音（合规时）+ 更多源 + 日报 / API |

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

**Pipeline（本地采集与处理，已实现并真实验证）**：

```bash
cd pipeline
python -m venv .venv && source .venv/bin/activate   # 或使用托管 Python 环境
pip install -e ".[dev]"
pytest                                          # 离线单测（含 Adapter 集成链路，零真实 API）

# 查看 CLI 全部参数
PYTHONPATH=src python -m pipeline --help

# 仅运行 arXiv 源（dry-run：不写入生产数据，仅打印摘要）
PYTHONPATH=src python -m pipeline --source arxiv --dry-run

# 正式写入本机数据（写 data/YYYY/MM/YYYY-MM-DD.json + index/health/sources_state）
PYTHONPATH=src python -m pipeline --source arxiv
```

> **默认仅 `arxiv` 源启用**（`config/sources.yaml` 中 `arxiv.enabled=true`）；`github` / `openai_blog` 已实现但默认关闭（`enabled=false`），需人工审查后开启。
> `--dry-run` 等价于 `--no-write`：只跑采集 / 标准化 / 校验 / 去重 / 产出，但**不写文件**；去掉 `--dry-run` 才会把数据写入 `data/` 对应日期目录。
> 运行全部已启用源（按 `enabled: true`）可省略 `--source`。

## 测试与质量状态

> ⚠️ 以下为最近一次本地验证的真实结果，**不代表**生产级质量保证；项目仍处于早期，前端 / AI / 多源等尚未完成。

- **pytest（Python 离线单测）**：`237 passed / 0 failed`（Adapter 集成链路、校验、去重、单源失败隔离等，均使用离线 fixture，不调用真实 API）。
- **ruff（Python lint）**：`All checks passed`。
- **npm run typecheck（前端 TypeScript 严格模式）**：`exit 0`（类型检查通过；前端 UI 功能本身仍待实现）。

## License

本项目正式采用 **MIT License**（见 `LICENSE`）。
