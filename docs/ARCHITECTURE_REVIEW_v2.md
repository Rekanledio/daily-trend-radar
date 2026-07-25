# Daily Trend Radar — 架构审查与方案定稿 (v2.0)

> 第二轮审查定稿文档。基于 `docs/PROJECT_PLAN.md (v1.0)`,对架构进行审查、修正与补全。
> 本文件为**纯规划文档,不含业务代码**。日期:2026-07-24 · 角色:首席架构师 + 产品 + 技术负责人。
>
> 本文档是 v2 阶段的**权威来源**;`PROJECT_PLAN.md` 已同步更新关键决策并指向本文件。

---

## 审查结论速览(先给结论)

| 审查项 | 结论 | 关键动作 |
|---|---|---|
| 一、总体架构基调 | ✅ **保留,确认无误** | 静态数据优先 + DataRepository 抽象,MVP 不引入重组件 |
| 二、Pipeline 顺序 | ⚠️ **不完全合理,已优化** | 关键:**AI 放到"截断≤20"之后**,只对最终候选调用,省成本、防幻觉 |
| 三、数据生命周期 | ➕ **新增** Raw/Processed/Published 三态;**MVP 不长期保存 Raw** |
| 四、日期数据结构 | ➕ **新增** `data/YYYY/MM/YYYY-MM-DD.json` + `index.json` + `health.json`,弃用单一 latest |
| 五、数据源配置中心 | ➕ **新增** `config/sources.yaml`(静态)+ `data/sources_state.json`(运行态) |
| 六、MVP 数据源拆分 | ➕ **细化** 为 4 大类 + 每类获取方式 |
| 七、平台扩展路线 | ➕ **新增** 每平台三级降级(自动/半自动/人工) |
| 八、健康监控 | ➕ **新增** `health.json` 完整结构 + 隔离原则 |
| 九、热点真实性状态 | ➕ **新增** draft/verified/published/rejected 的极简实现 |
| 十、事件聚合 | ➕ **细化** Event ↔ Trend 关系模型 |
| 十一、HotScore | ➕ **重构** 5 维度透明公式,不依赖 AI |
| 十二、首页健康状态 | ➕ **纳入** `/health` 页 + 首页状态条 |

---

# 1. 最终架构(确认 + 强化)

## 1.1 确认保留的基调

> **运行模型（v2.1 收敛）**：本项目定位为 **Local-first / Self-hosted**。默认运行模型是用户在本机完成一切（见下方「默认运行链路」）；GitHub Actions / Vercel 仅为**可选**的公网部署形态，不是默认路径，也不构成普通用户运行项目的先决条件。

**默认运行链路（用户本机）**：
```
用户电脑
  → 本地运行 Python Pipeline（本机直接访问公开数据源：arXiv / GitHub / 官方 RSS 等）
  → 本机生成 data/YYYY/MM/*.json（+ index.json + health.json）
  → 本机运行 Next.js（npm run dev / npm run start）
  → 浏览器通过 localhost 访问本地 Web UI
```

**可选公网部署形态（非默认）**：
```
Python 采集与处理（可选 GitHub Actions 定时/手动）
    ↓
生成按日期分片的 JSON 数据（+ index.json + health.json）
    ↓
（可选）GitHub Repository 保存与版本化
    ↓
Next.js App Router + TypeScript + Tailwind
    ↓
（可选）Vercel 部署展示（ISR 增量再生成）
```

## 1.2 MVP 明确不引入
独立后端服务器 · PostgreSQL · Redis · Kafka · Docker · Kubernetes。
> 理由:个人开源项目,静态数据 + 免费额度即可满足;引入这些只会抬高运维成本与门槛。

## 1.3 演进能力保留(核心)
所有数据读取经过 **`DataRepository` 抽象接口**,前端/API 只依赖接口,不感知底层存储:
```
DataRepository (interface)
├── JsonFileRepository   ← 默认(读本机 data/**/*.json)
└── (可选) 本地 SQLite Repository   ← 仅当用户确有搜索/历史规模需求时,不引入云数据库
```
切换仅改工厂函数一处,UI 与业务逻辑零改动。**这是为(可选)本地演进预留的唯一、且足够的扩展点;不规划云数据库（Supabase / PostgreSQL）实现。**

## 1.4 分层职责(强化)
| 层 | 默认运行位置 | 职责 | 失败影响 |
|---|---|---|---|
| 采集+处理(Python) | **用户本机**(可选 GitHub Actions) | 生产真实数据快照 | 仅影响当次快照,前端仍有历史数据 |
| 数据层(JSON/本地) | **用户本机 data/** | 存储+版本化+追溯 | 本地文件,几乎不失败 |
| 读取抽象(TS) | 本机 Next.js(构建/运行时) | 屏蔽存储差异 | 接口稳定 |
| 展示(Next.js) | **本机 localhost**(可选 Vercel) | UI/搜索/筛选/健康页 | 本地优先,永远有可用页面 |

---

# 2. 最终 Pipeline(重新审查后的优化顺序)

## 2.1 对原顺序的审查
原提议顺序:采集 → 标准化 → 字段校验 → 来源验证 → 去重 → 事件聚合 → 评分 → 候选筛选 → **AI 摘要/分类/标签 → AI 一致性检查** → 最终排序 → 截断≤20 → 发布。

**审查判定:方向正确,但 AI 位置偏早,需要调整。** 问题在于:
- 原顺序中"候选筛选"在"截断≤20"之前,若候选集大于 20×板块数,AI 仍会对**最终不会展示**的数据做调用 → 浪费成本。
- 应做到:**AI 只对"确定会发布的 ≤20 条/板块"调用**,把 AI 成本压到理论最小。

## 2.2 优化后的最终顺序
```
[1]  采集 Collect            各 Adapter 拉原始数据 → RawItem[]
[2]  标准化 Normalize         统一字段/时间/编码 → NormalizedItem[]
[3]  基础字段校验 Validate      title/collected_at 等必填非空,格式合法
[4]  来源验证 SourceVerify     original_url 存在且域名与来源一致;非法则丢弃
[5]  去重 Deduplicate         URL 规范化 + 标题归一(P1 加相似度)
[6]  事件聚合 Cluster          跨源同事件归并为 Event
[7]  评分 HotScore            5 维度透明打分(纯规则,不依赖 AI)
[8]  候选排序 Rank             按分排序
[9]  截断 Cap ≤20/板块         ★先截断,只保留最终会发布的条目
[10] AI 加工 Enrich(可开关)   ★只对 ≤20 条/板块调用:摘要/分类/标签
[11] AI 事实一致性检查 FactCheck AI 输出必须可回溯输入文本,否则丢弃 AI 结果、回退原文
[12] 组装发布 Assemble         写 Published JSON + 更新 index.json + health.json
```

## 2.3 关键改动与收益(对应你的 5 点要求)
| 要求 | 落地做法 |
|---|---|
| ①降低 AI 成本 | **先截断≤20 再调 AI**(步骤 9→10),AI 调用量 = 板块数×20 上限,可预测、最小化;叠加内容哈希缓存,相同内容不重复调 |
| ②不对低质量数据调 AI | 校验/去重/评分/截断全部在 AI 之前,进入 AI 的都是已通过质检的高分候选 |
| ③避免 AI 改/造事实 | AI 输出经步骤 11 **一致性检查**:摘要必须是输入文本的压缩(可回溯);分类必须落在固定枚举;不满足则**丢弃 AI 结果,回退原始标题/摘要** |
| ④最终内容真实 | 真实性校验(3、4)在最前置;AI 不参与"事实生成",只做加工;发布前所有条目均已验证 |
| ⑤来源可追溯 | `original_url` 在步骤 4 强制存在;贯穿到发布数据;AI 加工不改动来源字段 |

## 2.4 降级点
- AI 全链路可**一键关闭**(config `ai.enabled=false`):跳过 10/11,直接用原始标题/摘要发布。
- AI 单条失败:仅该条回退原文,不影响其他条目与整体发布。

---

# 3. 数据生命周期设计

## 3.1 三态定义
| 状态 | 含义 | 是否长期保存 | 位置 |
|---|---|---|---|
| **Raw** | 采集到的原始响应(HTML/JSON/XML 片段) | ❌ **MVP 不长期保存** | 仅 Actions 运行内存/临时目录,运行结束即弃 |
| **Processed** | 标准化+校验+去重+评分后的中间结构 | ❌ 不提交仓库(临时产物) | Actions 运行内临时目录 |
| **Published** | 最终发布数据(≤20/板块 + AI 加工) | ✅ **长期保存并版本化** | `data/YYYY/MM/*.json` 提交仓库 |

## 3.2 MVP 是否需要保存 Raw?——**结论:不需要长期保存**
理由:
1. **合规与体积**:长期把原始 HTML/网页内容提交 GitHub 体积膨胀、且可能触及第三方内容版权/条款问题。
2. **可追溯已由 original_url 保证**:每条 Published 数据都带原文链接,争议时点开原文即可核对,无需自存原始网页。
3. **审计需求可用轻量替代**:保留"采集运行报告"(每源条数/丢弃数/错误/耗时,进 health.json 与 Actions 日志)已足够复盘。

## 3.3 有限的 Raw 留存(仅调试用,不入生产)
- **Actions 运行日志**:保留原始响应的**摘要/状态码/条数**(非全文),随 Actions 日志自然留存,到期自动清理。
- **测试 fixtures**:少量**脱敏的真实响应样本**放 `pipeline/tests/fixtures/`,仅供离线单测,不随每日数据增长。
- 明确禁止:把每日抓取的完整 HTML/正文批量 commit 到仓库。

---

# 4. 最终数据目录结构

```
data/
├── index.json                 # 全局索引:可用日期列表、各板块最新统计、schema 版本
├── health.json                # 数据源健康快照(见第 6 节)
├── sources_state.json         # 数据源运行态(last_success/last_error 等,与配置分离)
├── 2026/
│   └── 07/
│       ├── 2026-07-22.json     # 当日发布数据(全板块)
│       ├── 2026-07-23.json
│       └── 2026-07-24.json
└── events/                    # (P1)事件聚合数据,按需
    └── 2026-07-24-events.json
```

## 4.1 单日文件结构(`2026-07-24.json`)
```
{
  "date": "2026-07-24",
  "schema_version": "1.0",
  "generated_at": "2026-07-24T09:00:00Z",
  "ai_enabled": true,
  "categories": {
    "ai_research": { "count": 18, "items": [ /* Trend[] ≤20 */ ] },
    "opensource":  { "count": 20, "items": [ ... ] },
    "ai_official": { "count": 12, "items": [ ... ] },
    "tech_news":   { "count": 20, "items": [ ... ] }
  },
  "run_summary": { "sources_ok": 4, "sources_failed": 0, "total_dropped": 7 }
}
```

## 4.2 index.json 结构
```
{
  "schema_version": "1.0",
  "updated_at": "2026-07-24T09:00:00Z",
  "latest_date": "2026-07-24",
  "available_dates": ["2026-07-22","2026-07-23","2026-07-24"],
  "categories": ["ai_research","opensource","ai_official","tech_news"],
  "date_index": {
    "2026-07-24": { "path": "2026/07/2026-07-24.json", "total_items": 70 }
  }
}
```

## 4.3 满足的 5 项要求
1. **看昨天**:读 `available_dates` 倒数第二天 → 对应 path。
2. **看历史**:遍历 `available_dates` / 按 `date_index` 定位。
3. **按日期读取**:路径规则确定 `data/YYYY/MM/YYYY-MM-DD.json`,可直接构造。
4. **git 追溯**:每日文件独立 commit,历史版本天然可追溯。
5. **不依赖单一 latest**:以 `index.json` + 日期分片为准;`latest_date` 只是指针,不是唯一数据源。

---

# 5. 数据源配置结构

## 5.1 两分离原则(关键设计)
- **静态配置**(人写、进仓库、版本化):`config/sources.yaml` — 描述"这个源是什么、怎么采、合不合规"。
- **运行态**(机器写、每次运行更新):`data/sources_state.json` — 描述"这个源最近跑得怎么样"。
> 分离的意义:配置稳定可评审;运行态频繁变化不污染配置,也便于健康监控独立生成。

## 5.2 config/sources.yaml(静态配置)
```yaml
version: 1
defaults:
  timeout: 15            # 秒
  retry_count: 2
  rate_limit: "1/5s"     # 每 5 秒 1 次
  max_items: 20
sources:
  - id: arxiv
    name: "arXiv"
    category: ai_research
    type: api             # api | rss | page
    enabled: true
    priority: 1           # 数字越小越优先/权威
    max_items: 20
    timeout: 20
    retry_count: 2
    rate_limit: "1/3s"    # 遵守 arXiv 3 秒间隔
    legal_status: official_api
    terms_url: "https://arxiv.org/help/api/tou"
    endpoint: "http://export.arxiv.org/api/query"
    query: "cat:cs.AI OR cat:cs.CL OR cat:cs.LG"
  - id: github_trending
    name: "GitHub Trending"
    category: opensource
    type: page            # 无官方 API,公开页面
    enabled: true
    priority: 2
    legal_status: public_page
    fallback: github_api_search   # 降级:用官方 API 近似
  - id: openai_blog
    name: "OpenAI Blog"
    category: ai_official
    type: rss
    enabled: true
    priority: 1
    legal_status: official_rss
    endpoint: "https://openai.com/blog/rss.xml"
```

## 5.3 legal_status 枚举(合规内建)
`official_api` | `official_rss` | `public_page`(公开无鉴权页面)| `third_party_legal` | `manual`(人工录入)。
> 只有以上状态可启用;任何需要绕过登录/验证码/风控/破解签名的实现一律 **禁止合入**。

## 5.4 新增/关闭源不改核心逻辑
- 新增:在 yaml 加一段 + 实现对应 Adapter(遵守 BaseAdapter 契约)→ registry 自动加载。
- 关闭:`enabled: false` 即可,核心 Pipeline/前端无需改动。

---

# 6. 数据源健康监控结构(health.json)

## 6.1 结构
```
{
  "schema_version": "1.0",
  "generated_at": "2026-07-24T09:00:00Z",
  "overall": "healthy",           // healthy | degraded | failed
  "sources": [
    {
      "source_id": "arxiv",
      "name": "arXiv",
      "category": "ai_research",
      "status": "healthy",         // healthy | degraded | failed | disabled
      "last_success": "2026-07-24T09:00:00Z",
      "last_attempt": "2026-07-24T09:00:00Z",
      "last_error": null,
      "item_count": 18,
      "response_time_ms": 820,
      "success_rate_7d": 1.0,
      "consecutive_failures": 0
    },
    {
      "source_id": "weibo",
      "name": "微博",
      "status": "disabled",
      "last_success": null,
      "last_error": null,
      "item_count": 0,
      "response_time_ms": null
    }
  ]
}
```

## 6.2 状态判定规则
| 状态 | 触发条件 |
|---|---|
| 🟢 healthy | 本次采集成功且条数 > 0 |
| 🟡 degraded | 采集成功但条数异常偏低 / 走了 fallback / 响应超时阈值 |
| 🔴 failed | 本次采集失败(连续失败累计,触发告警) |
| ⚪ disabled | 配置 `enabled: false`,不参与采集 |

## 6.3 隔离原则(硬性)
- 每个 Adapter 独立 try/except,**单源失败只写自己的 failed 状态**,不抛到主流程。
- 主流程"尽力而为":任一源失败 → 跳过 → 继续其他源 → 正常发布可用板块。
- **单源失败绝不导致整站失败**;前端读到某源 failed 时,该板块显示"数据源维护中",其余正常。
- 连续失败达阈值 → 自动开 GitHub Issue / 通知,不静默。

---

# 7. 热点数据模型(Trend)

```
Trend {
  id: string              // 稳定哈希 = hash(source_id + canonical_url)
  source_id: string       // 来源(关联 sources 配置)
  category: enum          // ai_research | opensource | ai_official | tech_news | social | game
  status: enum            // draft | verified | published | rejected(见第 9 节)
  title: string           // 原始标题
  summary: string | null  // 原摘要 或 AI 摘要
  summary_origin: enum    // original | ai | none   ← 标明摘要来源,保证透明
  original_url: string    // ★原始链接(必填,可追溯)
  author: string | null
  heat_raw: object | null // 原始热度快照(播放/点赞/排名),仅存不改
  hot_score: number       // 0–100 归一分(见第 8 节)
  score_breakdown: object // 各维度分量(透明可解释)
  rank_in_source: int | null
  published_at: datetime | null   // 原发布时间
  collected_at: datetime          // 采集时间
  tags: string[]          // 标签(原生或 AI)
  tags_origin: enum       // rule | ai | none
  event_id: string | null // 所属聚合事件
  lang: string
  is_mock: boolean        // 生产强制 false
}
```
> 设计要点:`summary_origin` / `tags_origin` 显式标注 AI 参与程度,保证"哪些是原文、哪些是 AI 加工"完全透明可审计。

---

# 8. 事件数据模型(Event)与关系

## 8.1 Event 模型
```
Event {
  event_id: string
  title: string          // 事件名(取簇内最高热度标题,或 AI 基于真实标题命名)
  summary: string | null // 事件摘要(基于成员真实内容,可回退)
  category: enum
  sources: [              // ★保留每个来源,可逐一追溯原文
    { source_id, trend_id, original_url, title, hot_score }
  ]
  source_count: int       // 跨源命中数 = distinct source_id 数量(≠ sources 长度；同来源多条转载保留每条 original_url,但只计一次)
  hot_score: number       // 事件热度 = 成员聚合(见第 8 节评分)
  published_at: datetime  // 最早成员时间
  updated_at: datetime    // 最新成员时间
}
```

## 8.2 Event ↔ Trend 关系
- **一对多**:一个 Event 关联多个 Trend;每个 Trend 通过 `event_id` 反向指向 Event。
- **不删除原始条目**:聚合不丢数据。相同事件的多条 Trend 仍保留,只是在 UI **折叠为一个事件卡**,展开可见全部来源。
- **单源事件**:未命中聚合的 Trend 视为"单来源事件"(source_count=1),UI 正常展示,无需强行聚合。
- **展示规则**:同事件在列表中只占 1 个卡位(避免重复刷屏),卡上标注"🔥 N 个来源在报道",点击进 `/event/[id]` 看全部来源。

---

# 9. 热点真实性状态(极简实现)

## 9.1 状态机
```
draft ──(通过字段校验+来源验证)──> verified ──(进入发布集≤20)──> published
  │                                    │
  └──(校验失败/来源非法/AI一致性不过)──┴──> rejected(不发布,仅记录原因)
```
| 状态 | 含义 |
|---|---|
| draft | 刚采集标准化,尚未校验 |
| verified | 已通过真实性/来源校验,进入去重/评分/候选 |
| published | 进入当日 ≤20 发布集,前端可见 |
| rejected | 未通过校验或被 AI 一致性检查拒绝,附 `reject_reason`,不展示 |

## 9.2 MVP 极简实现(不建后台)
- 状态只是 Trend 上的一个字段,由 **Pipeline 自动流转**,无需人工后台。
- **发布数据只写 `published` 条目**;`rejected` 仅记录在 Actions 运行日志/可选 `data/rejected/日期.json`(轻量,供复盘),不进前端。
- 未来若需人工复核(P1),只需增加一个"人工把 verified→published/rejected"的可选环节,模型无需改动。
> 用一个字段 + Pipeline 自动流转,实现"审核状态"语义,而零后台开发成本。

---

# 10. HotScore 设计(透明、不依赖 AI)

## 10.1 五维度公式
```
hot_score = 100 * clamp01(
    W_auth * AuthorityScore     // 来源权威性
  + W_heat * HeatScore          // 平台内热度(归一)
  + W_fresh * FreshnessScore    // 时间新鲜度
  + W_multi * MultiSourceScore  // 多来源数量(跨源共识)
  + W_plat * PlatformWeight     // 数据源平台权重
)
```

## 10.2 各维度定义(全部可解释,纯规则)
| 维度 | 定义 | 数据来源 |
|---|---|---|
| AuthorityScore | 来源权威性,由配置 `priority` 映射(priority 越小越高) | sources.yaml |
| HeatScore | 平台内互动量对数归一 `log1p(x)/log1p(max)`;无互动数的源用源内排名 `1-(rank-1)/N` | heat_raw |
| FreshnessScore | 时间衰减 `exp(-Δt/τ)`,τ 可配(如 24h) | published_at |
| MultiSourceScore | `min(1, source_count / K)`,K 可配(如 5) | Event.source_count |
| PlatformWeight | 平台整体权重(如官方源>聚合站),配置化 | sources.yaml |

## 10.3 默认权重(可配置,后续调参)
```
W_auth=0.25  W_heat=0.30  W_fresh=0.20  W_multi=0.15  W_plat=0.10
```

## 10.4 原则
- **透明**:`score_breakdown` 存每个分量原值,前端可展示"为什么这条排前面"。
- **不依赖 AI**:全部来自采集真实值 + 配置权重,AI 不参与打分。
- **只归一不造数**:缺失分量降权或置 0,绝不臆造热度。
- **源内归一**:HeatScore 在同源内归一,避免大平台碾压小平台。

---

# 11. 首页 / 健康状态页(纳入架构)

## 11.1 `/health` 独立页
读 `health.json`,表格展示所有源(含未启用):
```
数据源          状态        最近成功            条数   响应
AI Official     🟢 Healthy  2026-07-24 09:00   12     0.8s
ArXiv           🟢 Healthy  2026-07-24 09:00   18     0.9s
GitHub          🟢 Healthy  2026-07-24 09:00   20     1.2s
Tech RSS        🟡 Degraded 2026-07-24 06:00   4      3.1s
B站             ⚪ Disabled  —                  —      —
微博            ⚪ Disabled  —                  —      —
抖音            ⚪ Disabled  —                  —      —
酷安            ⚪ Disabled  —                  —      —
小黑盒          ⚪ Disabled  —                  —      —
```
状态图例:🟢 healthy / 🟡 degraded / 🔴 failed / ⚪ disabled。

## 11.2 首页状态条
首页顶部/底部放一个精简状态条:显示"数据更新于 X,N/M 数据源正常",点击进 `/health`。强化"数据真实、可观测"的信任感。

## 11.3 README 徽章
基于 `health.json` 生成数据源健康徽章,展示项目"活着且数据新鲜"。

---

# 12. MVP 数据源(细化拆分)

MVP 保留 4 大类,全部走**官方 API / 官方 RSS / 官方公开页 / 合法公开数据**,禁止任何绕过行为。

| 类别 | 数据源 | 获取方式 | legal_status |
|---|---|---|---|
| **AI / 科研** | arXiv | 官方 API(Atom),遵守 3s 间隔 | official_api |
| | (P1)Hugging Face Papers/Models | 官方 API | official_api |
| **开源 / 开发者** | GitHub Trending | 公开页面解析;降级用官方 Search API 近似 | public_page / official_api |
| | GitHub Releases/热门(可选) | 官方 REST/GraphQL API(带 token) | official_api |
| **AI 官方** | OpenAI / Anthropic / Google AI / Meta AI 博客 | 官方 RSS/Atom;无 RSS 则解析官方公开博客页 | official_rss / public_page |
| **科技资讯** | TechCrunch / The Verge / 36氪 / 少数派 等 | 官方 RSS(绝大多数提供) | official_rss |

获取方式优先级(硬性):**官方 API > 官方 RSS > 官方公开页面 > 合法公开数据**。
禁止:绕过验证码 / 绕过登录 / 绕过访问控制 / 破解接口 / 非法抓取。

---

# 13. 未来平台扩展路线(每平台三级降级)

优先级:**P1 = B站 / 微博 / 酷安 / 小黑盒;P2 = 抖音**。
每个平台设计三级降级:**自动采集 → 半自动采集 → 人工录入**。

| 平台 | 优先级 | ①自动采集(首选) | ②半自动采集(降级) | ③人工录入(兜底) |
|---|---|---|---|---|
| **B站** | P1 | 官方/公开热门·排行接口,遵守限频与 WBI 签名规则 | 官方 RSS 镜像 / 定期手动导出榜单 JSON | 维护者手动录入白名单条目(带原文链接) |
| **微博** | P1 | 官方开放平台合法接口 / 公开热搜接口(尊重风控) | 合规第三方聚合 RSS / 手动导出热搜 | 人工录入热搜词+原文链接 |
| **酷安** | P1 | 公开接口(尊重限频,不破解客户端签名) | 官方公开页面解析(公开无鉴权部分) | 人工录入热门条目 |
| **小黑盒** | P1 | 公开接口(尊重限频) | 公开页面解析 | 人工录入游戏热点 |
| **抖音** | P2 | **仅在合法可持续时**:官方开放平台接口 | 合规第三方数据 / 官方公开榜单页 | 人工录入热点(带抖音原文链接) |

## 13.1 通用降级原则
- 三级共用同一 `BaseAdapter` 契约与数据模型,切换级别不改下游。
- 人工录入也是"合法 Adapter"(`legal_status: manual`),数据同样需 `original_url` 可追溯、`is_mock=false`。
- 任一平台长期无法合法稳定获取 → 保持 `disabled`,前端诚实展示"该源维护中",绝不用假数据填充。
- **抖音红线**:绝不绕过其签名/风控/登录等技术保护措施;做不到合法稳定就停留在人工录入或不上线。

---

# 14. 最终范围与 Roadmap

## 14.1 MVP 范围(P0)
- 架构:静态数据优先 + DataRepository 抽象 + JSON 数据层。
- 数据源:arXiv / GitHub / AI 官方 RSS / 科技媒体 RSS(4 大类)。
- Pipeline:采集→标准化→校验→来源验证→去重→(基础)评分→截断≤20→(可选)AI→一致性检查→发布。
- 数据结构:`data/YYYY/MM/*.json` + `index.json` + `health.json` + `sources_state.json`。
- 配置中心:`config/sources.yaml`。
- 状态:Trend draft/verified/published/rejected(字段+自动流转)。
- 前端:综合/AI/科技板块 + 卡片 + 深色 + 响应式 + 搜索 + 日期筛选 + `/health` 页。
- 工程:本机一键运行 Pipeline + 本地前端(README 说明);可选 GitHub Actions(维护者 CI)/ 可选 Vercel(公网演示)。

## 14.2 P1 范围
- 社交/游戏源:B站、微博、酷安、小黑盒(各带三级降级)。
- AI 加工:摘要/分类/标签(可开关可降级)+ 一致性检查完善。
- 事件聚合:TF-IDF 相似度 + 事件详情页 + 折叠展示。
- 进阶去重:SimHash/向量。
- 健康监控完善:告警、7 日成功率、README 徽章。
- HotScore 全维度(含 MultiSource/PlatformWeight)调参。
- 数据审核:可选人工 verified→published 环节。

## 14.3 P2 范围
- 抖音(仅合法可持续时)。
- (可选)本地 SQLite + 全文/语义搜索(仅当用户确有规模需求;不引入云数据库)。
- 更多源(Hacker News、Product Hunt、知乎、掘金等)。
- 邮件日报 / RSS 输出 / 开放 API / i18n / 语义检索。

## 14.4 最终开发 Roadmap
| 阶段 | 目标 | 关键交付 |
|---|---|---|
| **阶段 0 地基** | 工程骨架 | 目录/License/README 骨架/CI 空跑绿灯;定义 Trend/Event Schema + DataRepository 接口 + sources.yaml 结构 |
| **阶段 1 数据闭环** | 采集→发布跑通 | 4 源 Adapter(离线 fixture 单测)+ 完整 Pipeline(至截断≤20)+ 产出 data/**/*.json + index/health |
| **阶段 2 前端上线** | 本机 localhost 可访问 | 三板块 UI + 深色/响应式 + 搜索 + 日期筛选 + /health + (可选 Vercel 部署) + README 完整(默认 Local-first) |
| **阶段 3 社交/监控** | 扩源+可观测 | B站/微博/酷安/小黑盒(带降级)+ 健康告警 + 手动更新入口(鉴权) |
| **阶段 4 数据智能** | AI+聚合 | AI 摘要/分类/标签(可开关+一致性检查)+ 事件聚合 + 事件页 + 进阶去重 |
| **阶段 5 规模化** | (可选)演进存储 | (可选)本地 SQLite + 全文/语义搜索 + 历史归档 + 审核流程 |
| **阶段 6 长期扩展** | 更多能力 | 抖音(合规时)+ 更多源 + 日报/API/i18n |

---

# 15. 每阶段验收标准

| 阶段 | 验收标准(须全部满足) |
|---|---|
| **阶段 0** | 目录/CI 就绪且 CI 绿灯;Trend/Event Schema、DataRepository 接口、sources.yaml 结构评审通过;README 骨架 + .env.example 存在 |
| **阶段 1** | 4 源可离线单测通过(用 fixture,不打真实 API);run 产出真实 `data/YYYY/MM/*.json` + index/health;每条含 original_url;每板块≤20 且不足不凑;无 is_mock;去重生效;单源失败不中断整体 |
| **阶段 2** | 本机 localhost 可访问;三板块正确渲染;深色/响应式/PC+移动正常;搜索+日期筛选可用;/health 正确反映状态;原文可跳转;**连续 7 天产出真实数据零虚构** |
| **阶段 3** | ≥2 个社交/游戏源接入且各有三级降级;单源 failed 时该板块降级、整站正常;健康告警可触发;手动更新可用且鉴权 |
| **阶段 4** | AI 可一键关闭并正确降级;AI 一致性检查生效(幻觉抽检通过、summary_origin 标注正确);事件聚合准确率人工抽检达标;进阶去重生效 |
| **阶段 5** | (可选)切换本地 SQLite Repository 后 UI 零改动;数据迁移无丢失;规模数据下搜索/历史性能达标 |
| **阶段 6** | 新增源均合法合规稳定;抖音仅在满足合法可持续前提下上线;扩展功能不破坏任何核心红线 |

## 全局验收红线(任何阶段不可违反)
零虚构 · 每条可追溯 original_url · 每板块≤20 且不凑数 · 采集全程合法合规(不绕过任何技术保护)· Mock 不进生产 · AI 只加工不创作事实。

---

_v2 定稿完成。等待你的确认后再进入实现阶段。本轮未写任何业务代码。_
