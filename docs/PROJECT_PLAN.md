# Daily Trend Radar / 每日热点雷达 — 项目规划书 (v1.1)

> 本文件为**纯规划文档**,不含任何生产代码。所有技术选型以"简单、稳定、可维护、低成本、适合个人开源"为最高优先级。
>
> 制定日期:2026-07-24 · 角色:首席软件架构师 + 产品经理 + 技术负责人
>
> ⚠️ **v2 定稿说明**:本项目已完成第二轮架构审查,定稿文档为 [`ARCHITECTURE_REVIEW_v2.md`](./ARCHITECTURE_REVIEW_v2.md)。
> 如下内容与 v2 冲突时,**以 v2 为准**。v2 的关键修订:
> 1. **Pipeline 顺序调整**:AI 加工移到"截断≤20 之后",只对最终发布候选调用(省成本、防幻觉),详见 v2 第 2 节 / 本文件第九部分末的修订注。
> 2. **新增**:数据生命周期(Raw/Processed/Published,MVP 不长期存 Raw)、日期分片目录结构、数据源配置中心(sources.yaml + sources_state.json)、热点真实性状态机(draft/verified/published/rejected)、health.json 完整结构、HotScore 五维透明公式、Event↔Trend 关系模型、/health 页。

---

## 项目运行模型:Local-first / Self-hosted(最高优先级定位)

> **本项目最终定位为本地运行 / Self-hosted / Local-first 应用。** 任何用户下载并安装项目后,都应能够在**自己的电脑上独立运行**完整 Pipeline,并在本机生成数据与运行前端 UI;**不依赖**中心化后端服务器、云数据库、公共 API 服务或用户登录系统。

**默认运行链路(用户本机):**
```
用户电脑
  → 本地运行 Python Pipeline(python -m pipeline)
  → 由本机直接访问公开互联网数据源(ArXiv / GitHub / 官方 RSS 等)
  → 本机处理(标准化/去重/评分/...)
  → 本机生成 data/YYYY-MM-DD/*.json + health.json
  → 本机运行 Next.js(npm run dev / npm run start)
  → 浏览器通过 localhost 访问本地 Web UI
```

**关键原则:**
1. 数据采集请求由**用户本机直接发起**,不经由任何中心化中转服务。
2. 数据保存在**用户自己的 `data/` 目录**,不强制上传云端或中心化数据库。
3. **不引入**用户登录、多用户账户、中心化用户系统作为运行必要条件。
4. 公网部署(Vercel 等)仅作为**可选**的个人演示 / 高级用法,**不是默认运行路径**,也不得成为普通用户体验项目的先决条件。
5. 若未来确实需要数据库(如搜索/历史规模),只允许规划为**可选的本地 SQLite**,不得引入云数据库(Supabase/PostgreSQL 等)作为强依赖。
6. 若未来实现"收藏"等个人偏好,仅考虑浏览器 `localStorage` 等**本地**方式,不落地服务端账户。

> 本文件其余章节中与上述定位冲突的表述(如将 Vercel 作为默认部署、将 Supabase/PostgreSQL 作为未来主数据层、将 GitHub Actions 作为普通用户运行必需),一律**以本节为准**进行收敛。

---

## 核心红线(贯穿全项目,不可妥协)

1. **真实性第一**:所有热点必须真实存在,严禁虚构标题、来源、热度、时间。
2. **来源可追溯**:每条数据必须携带原始 URL,可点击查看原文;无原始链接的数据视为不合格,不入库。
3. **数量宁缺毋滥**:每板块最多 20 条;不足 20 条时保持真实条数,禁止凑数。
4. **合法合规采集**:遵守 robots.txt、API 条款、频率限制与法律法规;禁止绕过登录/验证码/访问控制/技术保护措施。
5. **Mock 与生产严格隔离**:Mock 仅用于本地开发,必须打标 `is_mock=true` 且严禁进入生产数据流。
6. **AI 只做加工不做创作**:AI 仅在真实来源上做摘要/分类/打标/聚合,禁止凭空生成事实。

---

# 第一部分:项目需求分析

## 1.1 项目本质
一个**每日互联网热点与前沿资讯聚合平台**,把分散在 8+ 平台的热榜/资讯,标准化、去重、聚合、评分、AI 加工后,以现代化 Web UI 统一呈现,并保留完整来源追溯。

## 1.2 需求分类

**功能性需求**
- 数据聚合:综合热点 / AI 前沿 / 科技互联网 / 抖音 / B站 / 微博 / 小黑盒 / 酷安,可扩展。
- 展示:分板块、分类、排序、每板块≤20 条,卡片含标题/来源/热度/时间/原文链接。
- 检索与筛选:全文搜索、日期筛选、历史热点回看、分类过滤。
- 数据智能:去重、事件聚合、热度评分、AI 摘要、AI 分类、AI 标签。
- 数据治理:真实性校验、来源验证、数据审核、健康监控。
- 更新:自动更新(定时)+ 手动更新(触发)。
- 工程:CI/CD、GitHub Actions、部署、完整 README。

**非功能性需求**
- 现代化 + 响应式 UI,PC/移动端适配,深色模式。
- 低成本(尽量走免费额度)、易维护(个人可长期运维)、稳定(单源失败不拖垮全站)。
- 可观测(健康监控 + 采集日志)、可扩展(新增数据源成本低)、开源友好(结构清晰、文档完善)。

## 1.3 关键约束与风险
- **反爬与合规**:抖音/微博等平台反爬强、合规风险高 → 必须有降级方案。
- **数据源易变**:非官方接口随时可能失效 → Adapter 隔离 + 健康监控 + 快速替换。
- **成本约束**:个人项目 → 默认本机运行(零托管成本);可选 GitHub Actions(免费额度)做维护者 CI、可选 Vercel 免费层做公网演示;静态数据优先,数据存本地。
- **AI 成本与幻觉**:AI 调用要可控、可关闭、可降级,输出必须绑定真实来源。

---

# 第二部分:核心用户与使用场景

## 2.1 目标用户画像
1. **科技/AI 从业者与爱好者**:想在一个页面追踪 AI 前沿、科技、GitHub、论文动态。
2. **内容创作者 / 运营 / 自媒体**:需要快速抓取多平台热点选题。
3. **信息效率追求者**:不想在 8 个 App 间反复切换,想要"一屏看尽今日热点"。
4. **开发者/开源用户**:欣赏项目工程质量,可能 fork、自建、贡献数据源。

## 2.2 核心使用场景
- **晨读场景**:每天早上打开,浏览各板块 Top 榜,快速了解今日发生了什么。
- **选题场景**:创作者按分类/关键词搜索,点开原文深读。
- **回溯场景**:查"上周三的 AI 热点是什么",用日期筛选看历史。
- **深挖场景**:看到某事件在多平台同时上榜(事件聚合),点进去看聚合视图。
- **自建场景**:开发者 fork 项目,配置自己的数据源与部署。

## 2.3 用户核心价值主张
> **"一个页面,真实、可追溯、去重聚合后的今日全网热点。"**

---

# 第三部分:MVP 定义

## 3.1 MVP 目标
用**最小但完整闭环**验证核心价值:能自动采集真实数据 → 标准化/去重/评分 → 现代化 UI 展示 → 可追溯原文 → 可部署上线。

## 3.2 MVP 范围(做什么)
- **数据源(3–4 个,选最合法稳定的)**:ArXiv、GitHub Trending、AI 官方 RSS(OpenAI/Anthropic/Google AI 等)、科技媒体 RSS。
  - 理由:全部为官方 API / 公开 RSS,合法、稳定、零反爬风险,先跑通全链路。
- **数据链路**:Python 采集 → 标准化 → 真实性校验 → 去重 → 基础评分 → 输出结构化 JSON。
- **展示**:综合 / AI 前沿 / 科技三个板块,卡片式列表,每板块≤20 条,含原文链接、来源、时间。
- **能力**:关键词搜索、按日期查看、深色模式、响应式。
- **工程**:本机一键运行 Pipeline + 本地前端(README 说明);可选 GitHub Actions(维护者 CI)/ 可选 Vercel(公网演示)。

## 3.3 MVP 不做什么(明确排除)
- 不做抖音/微博/小黑盒/酷安(反爬强,放到 P1/P2 逐步攻坚)。
- 不做 AI 摘要/聚合(先用规则,AI 放 P1)。
- 不引入用户系统 / 登录 / 多用户账户 / 评论 / 订阅推送;收藏(如确有需求)仅限浏览器 localStorage。
- 不上 PostgreSQL(MVP 用 JSON/SQLite)。

## 3.4 MVP 成功标准
连续 7 天每天产出真实、可追溯、去重后的三板块数据(本机可访问,零虚构数据)。

---

# 第四部分:功能优先级(P0 / P1 / P2)

## P0 — 必须实现(MVP 核心闭环)
- [ ] 数据源 Adapter 框架(统一接口 + 注册表)
- [ ] 合法稳定数据源:ArXiv / GitHub Trending / AI 官方 RSS / 科技媒体 RSS
- [ ] 数据标准化(统一 Schema)
- [ ] **真实性 & 来源校验**(无原始 URL 拒绝入库)
- [ ] 基础去重(URL 规范化 + 标题归一)
- [ ] 基础热度评分(排名/时间衰减)
- [ ] 每板块≤20 条 + 不足不凑数
- [ ] 现代化响应式 UI + 深色模式 + PC/移动适配
- [ ] 板块:综合 / AI 前沿 / 科技互联网
- [ ] 原文跳转、来源标识、时间显示
- [ ] 关键词搜索 + 日期筛选
- [ ] 自动更新(可选:GitHub Actions 定时;非普通用户运行必需)
- [ ] 手动更新(手动触发采集)
- [ ] CI(lint/typecheck/build)+ 部署 + 完整 README

## P1 — 后续实现(增强)
- [ ] 社交平台数据源:B站、微博(优先合法/半官方接口 + 降级)
- [ ] 游戏板块:小黑盒、酷安
- [ ] AI 摘要 / AI 分类 / AI 标签(可开关、可降级)
- [ ] 热点事件聚合(跨平台同事件归并)
- [ ] 进阶去重(SimHash / 向量相似度)
- [ ] 历史热点归档 + 趋势回看
- [ ] 数据源健康监控面板 + README 状态徽章
- [ ] 数据审核流程(人工复核队列)
- [ ] 可选本地 SQLite(仅当用户确有搜索/历史规模需求时),不得引入云数据库

## P2 — 长期扩展
- [ ] 抖音等强反爬平台(仅在合法可持续前提下)
- [ ] 更多数据源(Product Hunt、Hacker News、知乎、掘金等)
- [ ] 个性化订阅 / RSS 输出 / 邮件日报
- [ ] 语义搜索(embedding 检索)
- [ ] 多语言 i18n
- [ ] 数据开放 API / 公共数据集
- [ ] 收藏(如确有需求,仅限浏览器 localStorage;不引入用户系统/登录/多用户账户)

---

# 第五部分:完整技术架构

## 5.1 架构总览(推荐:静态数据优先 + 逐步演进)

```
┌──────────────────────────────────────────────────────────────┐
│                     GitHub Actions (Cron 定时 / 手动触发)         │
│  ┌────────────┐   ┌─────────────────────────────────────────┐  │
│  │ Python     │→→│ Pipeline: 标准化→校验→去重→聚合→评分→AI加工 │  │
│  │ Collectors │   └─────────────────────────────────────────┘  │
│  └────────────┘                    │                            │
│         │ (Adapter 层, 每源一模块)   ▼                            │
│         │                    产出标准化数据                        │
└─────────┼──────────────────────────┬───────────────────────────┘
          │                          │
   数据源(RSS/API/官方)         写入数据层(JSON 文件 / 可选本地 SQLite)
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────┐
│      Next.js (App Router, TS, Tailwind) — 本机 localhost 运行(可选 Vercel)  │
│   读取数据层 → ISR/SSG 渲染 → 板块/搜索/日期/详情/健康页          │
│   前端展示 + 少量 API Routes(搜索/健康/手动触发代理)             │
└──────────────────────────────────────────────────────────────┘
```

> 注:上图展示的是"维护者可选的公网部署"形态之一。本项目**默认 Local-first**(用户本机运行 Pipeline + Next.js,数据存本地 `data/`,localhost 访问),不依赖 GitHub Actions 或 Vercel。下方"静态数据优先"优势在本地模式下同样成立。

## 5.2 为什么是"静态数据优先"
- **最低成本**:默认本机运行零托管成本;产出 JSON 存本地 `data/`。可选 GitHub Actions(免费额度)做维护者 CI、可选 Vercel 免费层做公网演示。
- **天然可追溯 + 版本化**:数据以 git 提交存档,历史热点 = git 历史,零额外成本。
- **单源失败不影响全站**:数据是预生成的快照,前端永远有可用数据。
- **演进路径清晰**:数据规模变大后,若确有需要,可把"JSON 文件"替换为"可选的本地 SQLite",前端读取层(Repository)做适配即可,UI 不改;**不引入云数据库**。

## 5.3 技术选型清单(克制,不堆技术)

| 层 | 选型 | 理由 |
|---|---|---|
| 前端框架 | **Next.js (App Router) + TypeScript** | 本机 `npm run dev`/`npm run start` 即可运行;SSG/ISR、生态成熟;Vercel 仅为可选公网部署 |
| 样式 | **Tailwind CSS + shadcn/ui** | 快速构建现代 UI、深色模式内建、可维护 |
| 采集语言 | **Python 3.12+** | 采集/解析生态最强(feedparser/httpx/lxml) |
| 数据层(MVP) | **JSON 文件(按日期分片)+ 可选 SQLite** | 零运维、可追溯、版本化 |
| 数据层(演进,可选) | **本地 SQLite** | 仅当用户确有搜索/历史规模需求;零运维、不依赖云端 |
| 定时/自动化 | **GitHub Actions** | 免费 cron + 手动触发,与仓库一体 |
| 部署(默认) | **本机运行(Next.js + localhost)** | 用户电脑直接跑,无需公网 |
| AI(P1) | **可插拔 LLM(OpenAI 兼容接口)** | 可开关、可降级到规则,成本可控 |

> **明确不引入**(避免过度工程):Kafka、Redis、Docker 编排、微服务、K8s、独立后端服务器(MVP 阶段)。个人项目用不上,徒增维护成本。

---

# 第六部分:前端架构设计

## 6.1 技术栈
Next.js(App Router)+ TypeScript + Tailwind + shadcn/ui + lucide 图标;状态用 URL query + React Server Components 为主,客户端交互用少量 hooks。

## 6.2 路由设计(App Router)
```
/                     首页:全部板块聚合视图(今日)
/category/[slug]      单板块详情(ai / tech / social / game / general)
/date/[date]          指定日期的热点(历史回看)
/search?q=            搜索结果页
/event/[id]           事件聚合详情(P1,同事件跨平台视图)
/health               数据源健康监控页
/about                项目说明
```

## 6.3 组件分层
- **布局层**:`RootLayout`(主题 Provider、Header、Footer、深色切换)。
- **板块层**:`CategorySection`(标题 + 数据源标 + 列表)。
- **卡片层**:`TrendCard`(标题、来源、热度徽章、相对时间、原文外链、事件标记)。
- **控件层**:`SearchBar`、`DatePicker`、`CategoryTabs`、`SortToggle`、`ThemeToggle`。
- **状态层**:`EmptyState`(不足/无数据时的诚实提示,而非填充假数据)、`HealthBadge`。

## 6.4 渲染策略
- 首页与板块页:**ISR**(增量静态再生成),按采集频率设定 revalidate。
- 搜索:走客户端过滤(数据量小)或本地 SQLite 全文检索(可选演进期);不依赖云端检索。
- 深色模式:`next-themes`,`prefers-color-scheme` + 手动切换,持久化到 localStorage。

## 6.5 UI/UX 原则
- 信息密度高但不拥挤,卡片清晰展示"来源 + 热度 + 时间"三要素。
- 移动端优先(mobile-first),断点适配 PC 多列布局。
- 明确的"数据来源"与"更新时间"标识,强化真实感与可信度。
- 加载态骨架屏;空数据诚实提示("今日该板块真实有效数据不足 20 条")。

---

# 第七部分:后端架构设计

## 7.1 后端形态(MVP:轻后端)
MVP **不部署独立后端服务器**。后端职责由两部分承担:
1. **离线管道(Python,默认跑在用户本机;可选 GitHub Actions)**:采集 + 处理 + 产出数据。这是"真正的后端"。
2. **Next.js API Routes(轻量在线接口)**:仅处理需要运行时的少量请求:
   - `GET /api/search` — 搜索(数据量大时走本地 SQLite 全文检索,可选)。
   - `GET /api/health` — 返回数据源健康快照。
   - `POST /api/refresh` — 手动触发(通过 `workflow_dispatch` 调 GitHub API,需鉴权)。

## 7.2 数据读取抽象层(关键设计)
定义 `DataRepository` 接口,前端只依赖接口,不关心底层是 JSON 还是可选本地 SQLite:
```
interface DataRepository {
  getTrends(category, date, limit): Trend[]
  search(query, filters): Trend[]
  getEvent(id): Event
  getHealth(): HealthSnapshot[]
  getAvailableDates(): string[]
}
```
- MVP 实现:`JsonFileRepository`(读 `/data/*.json`)。
- 演进实现(可选):本地 SQLite Repository;**不规划**云数据库实现。
- 切换只改工厂函数,UI 与业务逻辑零改动。

## 7.3 鉴权与安全
- 手动触发接口需 token(环境变量),防止被滥用触发采集。
- 所有密钥走环境变量 / GitHub Secrets,严禁进仓库。
- 数据写回仓库使用受限权限的 Actions token。

---

# 第八部分:数据采集架构

## 8.1 分层结构
```
pipeline/
├── core/
│   ├── base_adapter.py      # 抽象基类:fetch/parse/normalize/validate
│   ├── registry.py          # 数据源注册表(名称→Adapter)
│   ├── http_client.py       # 统一 httpx 客户端(超时/重试/UA/限速)
│   ├── rate_limiter.py      # 频率限制(尊重各平台规则)
│   └── models.py            # 标准化数据模型(RawItem→NormalizedItem)
├── adapters/
│   ├── arxiv.py
│   ├── github_trending.py
│   ├── rss_generic.py       # 通用 RSS(AI 官方/科技媒体复用)
│   ├── bilibili.py          # P1
│   ├── weibo.py             # P1
│   └── ...                  # 逐源扩展
├── stages/                 # 见第九部分 (normalize/validate/dedup/cluster/score/enrich)
└── run.py                   # 编排入口(用户本机或 Actions 调用)
```

## 8.2 采集通用原则
- **尊重规则**:检查 robots.txt,遵守 API 条款与速率限制,设置合理 UA 与请求间隔。
- **优先级**:官方 API > 官方 RSS > 半官方公开接口 > 页面解析(最后手段,且仅限公开无鉴权页面)。
- **绝不**:绕过登录、验证码、加密签名的付费/受保护接口,或任何访问控制。
- **容错**:每个源独立 try/except,单源失败记录并跳过,不中断整体。
- **可配置**:数据源开关、条数、频率、超时集中在 `config/sources.yaml`。

## 8.3 采集配置示例(结构,非代码)
```yaml
sources:
  arxiv:
    enabled: true
    category: ai
    max_items: 20
    query: "cs.AI OR cs.CL OR cs.LG"
  github_trending:
    enabled: true
    category: tech
    max_items: 20
    since: daily
```

---

# 第九部分:数据处理 Pipeline

## 9.1 处理流水线(有序阶段)
```
[1] Collect      各 Adapter 采集 → RawItem[]
        ↓
[2] Normalize    统一字段/时间/编码 → NormalizedItem[]
        ↓
[3] Validate     真实性&来源校验(无 URL/无来源 → 丢弃)
        ↓
[4] Deduplicate  URL 规范化 + 标题归一 + (P1)相似度去重
        ↓
[5] Cluster      事件聚合(P1:跨源同事件归并)
        ↓
[6] Score        热度评分(排名归一 + 时间衰减 + 跨源加权)
        ↓
[7] Enrich       AI 摘要/分类/标签(P1,可关闭,失败降级)
        ↓
[8] Cap & Rank   每板块按分排序,截断 ≤20,不足不补
        ↓
[9] Persist      写数据层(JSON/可选本地 SQLite)+ 健康快照
        ↓
[10] Publish     触发前端 ISR / 提交数据 / 部署
```

## 9.2 设计要点
- 每阶段**纯函数化、可单测、可独立重跑**。
- 阶段间传递标准化对象,任一阶段失败可局部降级(如 AI 失败仍产出无摘要版本)。
- 全流程产出**运行报告**(每源条数、丢弃数、去重数、耗时、失败原因)→ 供健康监控。

## 9.3 【v2 修订】AI 位置调整(以此为准)
v2 审查将 AI 阶段**后移到"截断 ≤20/板块"之后**,即先完成 校验→来源验证→去重→聚合→评分→排序→**截断≤20**,再对最终会发布的 ≤20 条/板块调用 AI 摘要/分类/标签,并追加 **AI 事实一致性检查**(不通过则丢弃 AI 结果、回退原文)。
收益:AI 调用量最小化(=板块数×20 上限)、绝不对低质量数据调 AI、AI 不参与事实生成。完整顺序见 `ARCHITECTURE_REVIEW_v2.md` 第 2 节。

---

# 第十部分:AI 能力设计

## 10.1 AI 的边界(红线)
AI **只加工不创作**:输入必须是已采集的真实条目,输出必须可回溯到原始来源。禁止让 AI"补充"或"推测"任何事实、热度、时间。

## 10.2 AI 功能(均可开关、可降级)
| 能力 | 输入 | 输出 | 降级方案 |
|---|---|---|---|
| 摘要 | 真实标题+正文摘录 | 1–2 句中文摘要 | 直接用原标题/原摘要 |
| 分类 | 标题+来源 | 归入固定分类枚举 | 基于关键词规则分类 |
| 标签 | 标题+摘要 | 3–5 个标签 | 基于关键词提取 |
| 事件聚合辅助 | 候选相似条目 | 是否同一事件+事件名 | 纯向量/文本相似度阈值 |

## 10.3 工程约束
- **可插拔**:抽象 `LLMProvider` 接口,支持 OpenAI 兼容/本地模型/关闭。
- **成本控制**:批处理、限长、缓存(相同内容不重复调用)、每日调用上限。
- **防幻觉**:强约束 prompt(仅基于给定文本;不确定则留空/标注"无法判断");输出做 schema 校验。
- **可审计**:记录每次 AI 输入输出与来源 ID,便于复核。

---

# 第十一部分:数据库模型设计

> MVP 用 JSON 表达同一模型;如需数据库,演进期映射为**可选的本地 SQLite** 表(非云)。以下为逻辑模型。

## 11.1 核心实体

**sources(数据源)**
| 字段 | 类型 | 说明 |
|---|---|---|
| id | string PK | 源标识(arxiv/github/...) |
| name | string | 展示名 |
| category | enum | ai/tech/social/game/general |
| type | enum | api/rss/page |
| homepage | string | 官网 |
| enabled | bool | 是否启用 |

**trends(热点条目)**
| 字段 | 类型 | 说明 |
|---|---|---|
| id | string PK | 稳定哈希(source+canonical_url) |
| source_id | FK | 来源 |
| category | enum | 分类 |
| title | string | 标题(原始) |
| summary | text? | 原摘要或 AI 摘要 |
| original_url | string | **原始链接(必填,可追溯)** |
| author | string? | 作者/UP主 |
| heat_raw | json? | 原始热度(点赞/播放/排名等) |
| heat_score | float | 归一化热度分 |
| rank_in_source | int? | 源内排名 |
| published_at | datetime? | 原发布时间 |
| collected_at | datetime | 采集时间 |
| tags | string[] | 标签 |
| event_id | FK? | 所属聚合事件 |
| is_mock | bool | **Mock 标记(生产必须 false)** |
| lang | string | 语言 |

**events(聚合事件)**
| 字段 | 类型 | 说明 |
|---|---|---|
| id | string PK | 事件 ID |
| title | string | 事件名 |
| category | enum | 分类 |
| trend_ids | string[] | 关联条目 |
| source_count | int | 跨源命中数 |
| max_heat | float | 最高热度 |
| first_seen / last_seen | datetime | 时间范围 |

**collection_runs(采集运行记录 / 健康)**
| 字段 | 类型 | 说明 |
|---|---|---|
| id | PK | 运行 ID |
| started_at / finished_at | datetime | 起止 |
| source_id | FK | 源 |
| status | enum | success/partial/failed |
| item_count | int | 产出条数 |
| dropped_count | int | 丢弃条数 |
| error | text? | 错误 |
| latency_ms | int | 耗时 |

## 11.2 索引与检索(可选本地 SQLite 演进期)
- `trends(category, published_at)`、`trends(collected_at)`、全文索引 `to_tsvector(title||summary)`。
- 唯一约束:`trends(id)`;去重依赖 canonical_url 哈希。

---

# 第十二部分:数据源 Adapter 架构

## 12.1 统一接口(契约)
每个 Adapter 必须实现:
```
class BaseAdapter:
    id: str
    category: str
    type: str  # api/rss/page
    def fetch(self) -> list[RawItem]      # 拉取原始数据
    def parse(self, raw) -> list[dict]    # 解析为字段
    def normalize(self, parsed) -> list[NormalizedItem]  # 标准化
    def validate(self, items) -> list[NormalizedItem]    # 真实性/来源校验
    def health() -> HealthInfo            # 自检信息
```

## 12.2 设计原则
- **隔离性**:一个源一个模块,内部实现变化不影响其他源与主流程。
- **注册制**:`registry.register(adapter)`,主流程按配置动态加载启用的源。
- **可测试**:每个 Adapter 配 fixture(真实响应样本,离线单测,不打真实 API)。
- **可降级**:Adapter 内部可定义 primary/fallback 策略(见第十六部分)。
- **合规内建**:Adapter 声明其 `robots_ok`、`rate_limit`、`terms_url`,不合规的实现拒绝合入。

## 12.3 标准化输出(NormalizedItem)
统一为第十一部分 `trends` 的字段子集,保证下游 Pipeline 只面对一种数据形态。

---

# 第十三部分:数据源可行性分析

> 评级维度:**获取难度**(易/中/难)、**合法性**(高/中/需谨慎)、**稳定性**(高/中/低)。
> 原则:官方渠道优先;非官方接口一律加降级 + 健康监控;强反爬平台谨慎评估合法可持续性。

| 数据源 | 获取难度 | 合法性 | 稳定性 | 推荐实现方式 | 优先级 |
|---|---|---|---|---|---|
| **AI 官方来源**(OpenAI/Anthropic/Google/Meta AI 博客) | 易 | 高 | 高 | 官方 **RSS/Atom**;无 RSS 则解析官方博客公开页 | **P0** |
| **科技媒体**(TechCrunch/The Verge/36氪/少数派等) | 易 | 高 | 高 | 官方 **RSS**(绝大多数提供) | **P0** |
| **RSS(通用)** | 易 | 高 | 高 | 标准库 `xml.etree` 通用 RSS/Atom 适配器,配置化订阅源(零新增依赖) | **P0** |
| **GitHub** | 易 | 高 | 高 | **官方 REST/GraphQL API**(带 token);Trending 无官方 API,用公开页解析或成熟第三方,做降级 | **P0** |
| **Hugging Face** | 易 | 高 | 高 | **官方 API**(models/datasets/papers 端点) | P0/P1 |
| **ArXiv** | 易 | 高 | 高 | **官方 API**(Atom),遵守 3s 间隔;最合规稳定的源之一 | **P0** |
| **B站** | 中 | 中(公开数据,遵守频率) | 中 | 优先官方开放/公开 API(热门/排行),尊重 WBI 签名与限频;失败降级 | **P1** |
| **微博** | 难 | 需谨慎(反爬强/条款严) | 低 | 优先合法公开接口/官方开放平台;避免绕过风控;不稳定时降级为 RSS 镜像/手动 | **P1** |
| **抖音** | 很难 | **需高度谨慎**(强反爬/签名/条款限制) | 低 | 仅在**合法可持续**前提下评估;优先官方开放平台;否则降级为第三方合规聚合或**手动录入白名单**,不绕过技术保护 | **P2** |
| **小黑盒**(游戏) | 中 | 需谨慎 | 中 | 优先公开接口;尊重限频;不稳定则降级/手动 | P1/P2 |
| **酷安**(游戏/数码) | 中 | 需谨慎(客户端签名) | 中 | 优先公开接口;避免逆向受保护签名;不稳定则降级/手动 | P1/P2 |

## 13.1 结论与策略
- **先易后难**:P0 全部用官方 API/RSS(ArXiv、GitHub、HF、AI 官方、科技媒体),零反爬风险,先把平台跑通。
- **社交平台谨慎推进**:B站/微博/小黑盒/酷安放 P1,逐个攻坚,每个都必须自带降级。
- **抖音单列 P2**:合规风险最高,只有在能找到合法、稳定、可持续方案时才做;否则以"官方开放平台 / 合规第三方 / 人工白名单录入"替代,绝不绕过技术保护。

---

# 第十四部分:自动更新机制

## 14.1 触发方式
- **GitHub Actions `schedule`(cron)**:分频率采集。
  - 高频源(社交热榜):建议每 1–3 小时(视平台限频与免费额度)。
  - 中频源(科技/AI RSS):每 3–6 小时。
  - 低频源(ArXiv/GitHub Trending):每日 1–2 次。
- 采用**多 workflow / 矩阵**按频率分组,避免每次全量拉取。

## 14.2 流程
```
cron 触发 → checkout → 装 Python 依赖 → run.py(采集+处理)
→ 产出 data/YYYY-MM-DD/*.json + health.json
→ 本机写入 `data/YYYY-MM-DD/`(默认);可选提交回仓库 / 可选 Vercel 公网演示重新部署
```

## 14.3 关键保障
- **并发锁**:`concurrency` 防止运行重叠。
- **失败可见**:失败发 GitHub Issue / 更新 health 状态,不静默。
- **幂等**:同日重复运行覆盖当日快照,不产生重复。
- **免费额度友好**:控制频率与运行时长,避免超额。

---

# 第十五部分:手动更新机制

## 15.1 两种入口
1. **仓库侧**:GitHub Actions `workflow_dispatch`,可选参数(指定源/指定分类),维护者一键手动跑。
2. **前端侧(可选,需鉴权)**:`/health` 或管理入口点"立即更新" → `POST /api/refresh` → 携带 token 调 GitHub API 触发 `workflow_dispatch`。

## 15.2 约束
- 手动触发必须鉴权(token),防滥用。
- 前端展示上次更新时间与"更新中"状态,避免重复触发(限频提示)。
- 手动与自动共用同一 Pipeline,保证行为一致。

---

# 第十六部分:数据源失败降级策略

## 16.1 多级降级(每个 Adapter 内建)
```
L0 Primary   官方 API / 官方 RSS
   ↓ 失败/超时/被限
L1 Fallback  备用公开接口 / 备用 RSS 镜像 / 缓存上次成功结果
   ↓ 仍失败
L2 Stale     使用最近一次成功的历史快照,并在 UI 标注"数据可能非最新"
   ↓ 长期失败
L3 Skip      跳过该源,前端展示"暂无数据/该源维护中",绝不用假数据填充
```

## 16.2 策略细则
- **超时与重试**:指数退避重试(有限次),尊重 429/Retry-After。
- **熔断**:连续 N 次失败自动标记该源 `degraded`,降低重试频率并告警。
- **陈旧标注**:降级到历史数据时,前端明确标注更新时间,诚实优先。
- **绝不凑数**:任何降级都不得引入虚构或低质量数据。

---

# 第十七部分:数据真实性与来源验证机制

## 17.1 入库前硬性校验(Validate 阶段)
一条数据必须**同时满足**才允许入库:
1. 有非空 `original_url`,且 URL 格式合法、可解析域名。
2. `source_id` 属于已登记的合法数据源。
3. 关键字段(title、collected_at)非空。
4. `is_mock == false`(生产流水线强制)。
5. 时间字段合理(不在未来、格式正确)。

## 17.2 来源可信度
- URL 域名与声明来源一致性检查(防止张冠李戴)。
- 热度字段来自采集原值,禁止流水线"生成"热度;归一化只做换算不造数。
- 保留 `heat_raw` 原始值,供审计对照。

## 17.3 审计与追溯
- 每条数据记录 `collected_at`、`source_id`、`run_id`,可回溯到具体采集运行。
- 采集原始响应样本(脱敏)可保留于日志/fixture,便于争议核对。
- Mock 隔离:开发环境数据一律 `is_mock=true`;CI 检查禁止 `is_mock=true` 进入生产数据目录。

---

# 第十八部分:热点去重机制

## 18.1 多层去重(由廉价到精细)
```
[1] URL 规范化去重(P0)
    去除 utm/追踪参数、统一协议/末尾斜杠/大小写 → 生成 canonical_url → 哈希比对
[2] 标题归一去重(P0)
    去空白/标点/emoji、全半角统一、繁简统一 → 精确匹配
[3] 近似标题去重(P1)
    SimHash / Jaccard(n-gram)相似度 > 阈值 判重
[4] 语义去重(P2)
    句向量 embedding 余弦相似度 > 阈值 判重
```

## 18.2 去重策略
- **同源去重**:同一源内完全去重。
- **跨源处理**:跨源相同 URL 视为重复(保留热度最高/最早);相似但非同 URL 的跨源条目→交给"事件聚合"而非直接删除(保留多来源价值)。
- **保留策略**:重复项保留信息最全、热度最高者作为主条目,其余作为该主条目的附加来源。

---

# 第十九部分:热点事件聚合机制

## 19.1 目标
把"同一件事"在不同平台/不同标题下的多条热点归并为一个 **Event**,呈现"某事件在 5 个平台上榜"的聚合视角。

## 19.2 聚合流程(P1)
```
候选生成 → 文本表示 → 相似度计算 → 聚类 → 事件命名 → 关联回写
```
- **文本表示**:标题(+摘要)清洗后 → TF-IDF 向量(廉价)或句向量(P2)。
- **相似度**:余弦相似度;设阈值 τ(可调)。
- **聚类**:阈值连通分量 / 简单层次聚类(数据量小,无需重型算法)。
- **约束**:同分类内聚合;时间窗口限制(如同一天 / 48 小时内)避免跨期误合。
- **事件命名**:取簇内热度最高条目标题,或 AI 生成简短事件名(基于真实标题,不创作)。
- **回写**:为每条 `trends` 写 `event_id`,生成 `events` 记录(source_count、max_heat 等)。

## 19.3 展示
- 卡片显示"🔥 N 个平台在讨论"标记,点进 `/event/[id]` 看聚合来源列表(每条仍可追溯原文)。

---

# 第二十部分:热点评分机制

## 20.1 设计目标
不同平台热度口径不同(播放/点赞/排名/评论),需归一到可比的 `heat_score`(0–100),兼顾热度、时效、跨源共识。

## 20.2 评分公式(可调权重)
```
heat_score = 100 * ( w1 * RankScore
                   + w2 * EngagementScore
                   + w3 * RecencyScore
                   + w4 * CrossSourceScore )
```
- **RankScore**:源内排名归一,`1 - (rank-1)/N`(排名越靠前越高)。解决无点赞数的源(如榜单)。
- **EngagementScore**:互动量在**该源内**做百分位/对数归一(`log1p`),避免大平台碾压小平台。
- **RecencyScore**:时间衰减,`exp(-Δt/τ)`,越新越高。
- **CrossSourceScore**:该事件跨源命中数越多分越高(共识度),`min(1, source_count/K)`。
- 权重 `w1..w4` 配置化,默认可设 0.35/0.30/0.20/0.15,后续按效果调。

## 20.3 原则
- **只归一,不创造**:所有输入来自真实采集值;缺失的分量降权或置 0,不臆造。
- **可解释**:保留各分量中间值,便于调参与排查。
- **分源可比**:归一化在源内进行,保证跨平台公平。

---

# 第二十一部分:数据源健康监控机制

## 21.1 采集指标(每次运行记录)
- 成功/部分/失败状态、产出条数、丢弃条数、去重数、耗时、错误信息、最后成功时间。

## 21.2 健康快照
- Pipeline 产出 `data/health.json`:每个源的 `status`、`last_success_at`、`item_count`、`error`、`success_rate_7d`。

## 21.3 呈现与告警
- **前端 `/health` 页**:表格展示各源状态(🟢 正常 / 🟡 降级 / 🔴 失败)、最近更新时间、7 日成功率。
- **README 徽章**:数据源健康状态徽章(基于 health.json 生成)。
- **告警**:源转为 `failed`/`degraded` 时自动开 GitHub Issue 或发通知,避免静默失效。
- **趋势**:保留历史 run 记录,可看某源稳定性趋势。

---

# 第二十二部分:GitHub Actions 与 CI/CD

## 22.1 Workflows 规划
```
.github/workflows/
├── ci.yml            # PR/push:前端 lint+typecheck+build;Python lint+test
├── collect.yml       # cron + workflow_dispatch:采集与处理,产出/提交数据
├── collect-social.yml# (P1) 社交源单独频率与降级
└── health-check.yml  # (可选) 定时健康检查与告警
```

## 22.2 CI(质量门禁)
- 前端:`eslint` + `tsc --noEmit` + `next build`。
- Python:`ruff`/`flake8` + `pytest`(Adapter 用 fixture 离线测,**不打真实 API**)。
- **数据合规检查**:CI 校验产出数据无 `is_mock=true`、每条含 `original_url`、每板块≤20 条。
- 分支保护:PR 必须过 CI 才能合并。

## 22.3 CD(部署)
> 本项目默认 **Local-first**,用户在本机运行,无需部署。以下公网部署仅作**可选**个人演示。
- 前端(可选公网):Vercel Git 集成,main 分支自动部署;PR 生成 Preview。**非默认路径**。
- 数据:默认本机写入 `data/`;若启用公网演示,collect.yml 提交数据后可触发 ISR revalidate / 重新部署。
- Secrets:所有密钥走 GitHub Secrets + Vercel 环境变量,零硬编码。

---

# 第二十三部分:完整项目目录设计

```
daily-trend-radar/
├── README.md                     # 完整项目说明(P0)
├── LICENSE                       # 开源协议(建议 MIT)
├── .github/
│   └── workflows/                # CI / collect / health(第22部分)
├── docs/                         # 规划/架构/数据源合规文档(本文件所在)
│   ├── PROJECT_PLAN.md
│   ├── ARCHITECTURE.md
│   └── DATA_SOURCES.md           # 各源合规说明与条款链接
├── frontend/                     # Next.js 前端(App Router + TS + Tailwind)
│   ├── app/                      # 路由(/、category、date、search、event、health、about)
│   ├── components/               # UI 组件(TrendCard/SearchBar/ThemeToggle...)
│   ├── lib/
│   │   ├── repository/           # DataRepository 抽象 + JSON/可选本地 SQLite 实现
│   │   └── types.ts              # 共享类型(与采集端 Schema 对齐)
│   ├── public/
│   └── package.json
├── pipeline/                     # Python 采集与处理
│   ├── core/                     # base_adapter/registry/http_client/models
│   ├── adapters/                 # 各数据源实现
│   ├── pipeline/                 # normalize/validate/dedup/cluster/score/enrich
│   ├── ai/                       # LLMProvider 抽象与实现(可关闭)
│   ├── run.py                    # 编排入口
│   ├── tests/                    # fixtures + 单测(离线)
│   └── requirements.txt
├── data/                         # 产出数据(JSON,按日期分片)+ health.json
│   └── YYYY-MM-DD/
├── config/
│   └── sources.yaml              # 数据源配置(开关/条数/频率)
├── scripts/                      # 辅助脚本(本地运行/校验)
└── .env.example                  # 环境变量样例(不含真实密钥)
```

---

# 第二十四部分:开发 Roadmap

## 阶段 0 — 立项与骨架(工程地基)
- 初始化仓库、目录、License、README 骨架、CI(空跑通过)、.env.example。
- 定义共享数据 Schema(前后端对齐)、DataRepository 接口。

## 阶段 1 — MVP 数据闭环(P0)
- 实现 core/base_adapter + registry + http_client。
- 实现 4 个合法源:ArXiv / GitHub / AI 官方 RSS / 科技媒体 RSS。
- Pipeline:normalize → validate → dedup(URL+标题)→ 基础评分 → 产出 JSON。
- collect.yml(cron + 手动)跑通,数据提交回仓库。

## 阶段 2 — MVP 前端与上线(P0)
- Next.js:首页三板块 + 卡片 + 深色模式 + 响应式。
- 搜索 + 日期筛选 + 原文跳转。
- 本机运行说明 + README 完整化(默认 Local-first,公网部署列为可选)。
- **里程碑:本机 localhost 可访问,连续 7 天真实数据。**

## 阶段 3 — 社交/游戏源与健康监控(P1)
- 新增 B站、微博(带降级);再评估小黑盒/酷安。
- 健康监控页 + README 徽章 + 失败告警。
- 手动更新前端入口(鉴权)。

## 阶段 4 — 数据智能(P1)
- AI 摘要/分类/标签(可开关可降级)。
- 事件聚合(TF-IDF 相似度)+ 事件详情页。
- 进阶去重(SimHash)。

## 阶段 5 — 数据规模化(P1→P2)
- 可选本地 SQLite + 全文/语义搜索(仅当用户确有规模需求;不引入云数据库)。
- 历史归档与趋势回看。
- 数据审核流程。

## 阶段 6 — 长期扩展(P2)
- 抖音等强反爬源(仅合法可持续时)、更多数据源。
- 邮件日报 / RSS 输出 / 开放 API / i18n。

---

# 第二十五部分:各阶段验收标准

| 阶段 | 验收标准(必须全部满足) |
|---|---|
| **阶段 0** | 仓库结构完整;CI 绿灯;README 骨架与 .env.example 存在;Schema 与 Repository 接口评审通过 |
| **阶段 1** | 4 个源可离线单测通过;运行 run.py 产出真实 JSON;每条含 original_url;每板块≤20 且不足不凑;无 is_mock 数据;去重生效 |
| **阶段 2** | 本机 localhost 可访问;三板块正确渲染;深色/响应式/PC+移动正常;搜索与日期筛选可用;原文可跳转;**连续 7 天产出真实数据零虚构** |
| **阶段 3** | 至少新增 2 个社交/游戏源且均有降级;单源失败不影响全站;健康页与徽章反映真实状态;失败自动告警;手动更新可用且鉴权 |
| **阶段 4** | AI 摘要/分类/标签可用且可一键关闭并正确降级;AI 输出全部绑定真实来源、无幻觉抽检通过;事件聚合准确率人工抽检达标;近似去重生效 |
| **阶段 5** | (可选)本地 SQLite 迁移无丢失;搜索/历史在规模数据下性能达标;审核流程可运转 |
| **阶段 6** | 新增源均合法合规且稳定;扩展功能(日报/API 等)按需交付且不破坏核心红线 |

## 全局验收红线(任何阶段都不得违反)
- 零虚构数据;每条可追溯原文;每板块≤20 且不凑数;采集全程合法合规;Mock 不入生产;AI 不创作事实。

---

## 附:关键决策摘要(给未来的自己)
1. **架构基调**:Local-first / Self-hosted(用户本机运行 Pipeline + Next.js,数据存本地 `data/`,localhost 访问);用 Repository 抽象预留**可选本地 SQLite** 演进,避免过度工程与云依赖。
2. **数据源节奏**:官方 API/RSS 先行(P0),社交平台谨慎跟进(P1),抖音等强反爬单列(P2)。
3. **真实性是产品灵魂**:校验、去重、评分、聚合、AI 全部围绕"真实可追溯"设计,宁缺毋滥。
4. **可观测与降级**:每源自带多级降级 + 健康监控,单源失效不拖垮全站,永不用假数据填充。

_下一步等待你的指令后再进入实现阶段。_
