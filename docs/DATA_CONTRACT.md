# Daily Trend Radar — 核心数据契约 (DATA_CONTRACT)

> 阶段 0 第三轮「核心数据契约设计」交付物。本文档定义
> `Python Pipeline → Published JSON → DataRepository → Next.js Frontend`
> 之间的**统一数据协议（单一事实来源）**。
>
> 权威关系：`PROJECT_RULES.md` > `ARCHITECTURE_REVIEW_v2.md` > `PROJECT_PLAN.md`。
> 本文件与 `schemas/*.schema.json` 互为补充：JSON Schema 是机器可校验的契约，本文是人工可读说明。
> 制定日期：2026-07-24。

---

## 0. 契约文件清单

| 文件 | 作用 |
|---|---|
| `schemas/trend.schema.json` | Trend 契约（生产数据的最小真实条目） |
| `schemas/event.schema.json` | Event 契约（聚合事件层） |
| `schemas/source.schema.json` | `config/sources.yaml` 解析后的 `SourcesConfig` 契约（含 `$defs/Source`） |
| `schemas/health.schema.json` | `data/health.json` 健康快照契约 |
| `schemas/published-data.schema.json` | `data/YYYY/MM/YYYY-MM-DD.json` 每日发布数据契约 |
| `schemas/index.schema.json` | `data/index.json` 历史索引契约 |
| `schemas/sources-state.schema.json` | `data/sources_state.json` 运行态契约 |
| `pipeline/src/pipeline/models.py` | Pydantic v2 模型（镜像 JSON Schema） |
| `pipeline/src/pipeline/validation.py` | 生产红线纯函数校验（`is_mock`/`original_url` 等） |
| `pipeline/src/pipeline/repository.py` | `DataRepository` Protocol（仅接口，无实现） |
| `frontend/lib/types.ts` | TypeScript 类型（镜像 JSON Schema） |
| `frontend/lib/repository.ts` | TS 侧 `DataRepository` 接口（仅接口，无实现） |

> **契约 ≠ 业务逻辑**：以上文件只描述"数据长什么样、如何校验、如何读取"，不含采集/网络/AI/存储实现。

---

## 1. Trend Schema（热点/资讯条目）

`id` 规则：`hash(source_id + canonical_url)`（归一化后哈希，稳定且可用于去重）。

| 字段 | 类型 | 必填 | 可空 | 含义 / 来源 | 示例 |
|---|---|---|---|---|---|
| `id` | string | ✅ | ❌ | 稳定哈希 | `"a1b2c3..."` |
| `event_id` | string\|null | ✅ | ✅ | 所属聚合事件；未聚合为 null | `"evt_2026_07_24_01"` |
| `source_id` | string | ✅ | ❌ | 数据源 id（关联配置） | `"arxiv"` |
| `source_name` | string | ✅ | ❌ | 采集时点来源名**快照**（去规范化） | `"arXiv"` |
| `category` | string | ✅ | ❌ | 分类 id（可配置，非固定枚举） | `"ai_research"` |
| `title` | string | ✅ | ❌ | 原始标题 | `"GPT-5 技术报告发布"` |
| `summary` | string\|null | ✅ | ✅ | 原摘要或 AI 摘要；无则 null | `"本文提出..."` |
| `summary_origin` | enum | ✅ | ❌ | `original`/`ai`/`none` | `"original"` |
| `original_url` | string(uri) | ✅ | ❌ | **生产必填**，真实来源且域名与 source 一致 | `"https://arxiv.org/abs/123"` |
| `canonical_url` | string(uri)\|null | ✅ | ✅ | 归一化 URL（去追踪参数），用于去重/id | `"https://arxiv.org/abs/123"` |
| `author` | string\|null | ✅ | ✅ | 作者 | `"OpenAI"` |
| `tags` | string[] | ✅ | ❌ | 标签（默认 `[]`） | `["llm","safety"]` |
| `tags_origin` | enum | ✅ | ❌ | `rule`/`ai`/`none` | `"rule"` |
| `published_at` | string\|null (ISO8601 UTC) | ✅ | ✅ | 原始发布时间；源未提供为 null | `"2026-07-24T08:00:00Z"` |
| `collected_at` | string (ISO8601 UTC) | ✅ | ❌ | 采集时间 | `"2026-07-24T09:00:00Z"` |
| `updated_at` | string (ISO8601 UTC) | ✅ | ❌ | 最近更新时间 | `"2026-07-24T09:00:00Z"` |
| `heat_raw` | object\|null | ✅ | ✅ | 平台原始热度快照（仅存不改） | `{"rank":1,"stars":120}` |
| `hot_score` | number 0–100 | ✅ | ❌ | HotScore 归一分 | `82.5` |
| `score_breakdown` | object | ✅ | ❌ | 五维分量（透明可解释） | `{authority,heat,freshness,multi_source,platform}` |
| `rank_in_source` | int\|null | ✅ | ✅ | 源内排名 | `1` |
| `status` | enum | ✅ | ❌ | `draft`/`verified`/`published`/`rejected` | `"published"` |
| `lang` | string | ✅ | ❌ | 语言代码（默认 `"en"`） | `"zh"` |
| `is_mock` | boolean | ✅ | ❌ | **生产必须为 `false`** | `false` |

**生产数据额外红线（由 `validation.py` 强制）**：`is_mock=false` 且 `original_url` 非空且 `status=published`。
**`additionalProperties: false`**：Trend 不接受任何未声明字段，防止脏数据混入。

---

## 2. Event Schema（聚合事件）

一个 Event = 多个 Trend 的聚合层；**原始 Trend 不删除**，追溯关系保留。

| 字段 | 类型 | 必填 | 可空 | 含义 |
|---|---|---|---|---|
| `event_id` | string | ✅ | ❌ | 事件 id |
| `title` | string | ✅ | ❌ | 事件名（取簇内最高热度标题，或 AI 基于真实标题命名） |
| `summary` | string\|null | ✅ | ✅ | 事件摘要（基于成员真实内容；无则 null） |
| `category` | string | ✅ | ❌ | 分类 id |
| `sources` | EventSourceRef[] | ✅ | ❌ | 每个来源的追溯引用（见下） |
| `source_count` | int | ✅ | ❌ | 跨源命中数，**必须等于 `len(sources)`** |
| `trend_ids` | string[] | ✅ | ❌ | 关联 Trend id，**必须等于 `sources[].trend_id` 集合** |
| `hot_score` | number 0–100 | ✅ | ❌ | 事件热度（成员聚合） |
| `score_breakdown` | object | ✅ | ❌ | 事件五维分量 |
| `published_at` | string (ISO8601 UTC) | ✅ | ❌ | 最早成员发布时间 |
| `updated_at` | string (ISO8601 UTC) | ✅ | ❌ | 最新成员更新时间 |

`EventSourceRef`：`{ source_id, source_name, trend_id, original_url, title, hot_score }`
—— **保存 `source_id` 引用 + 每条 `original_url`**，便于逐一追溯，但**不内嵌完整 Source 配置**（配置在 `sources.yaml`/`sources_state.json`）。

**关系图**：
```
Event (event_id)  ──1──┐
                       │  sources[] / trend_ids[]
                       ├──→ Trend A (source_id=arxiv,  original_url=...)
                       ├──→ Trend B (source_id=github, original_url=...)
                       └──→ Trend C (source_id=openai, original_url=...)
每个 Trend 通过 event_id 反向指向 Event。
```
UI 折叠为一个事件卡（标注"N 个来源在报道"），展开可见全部来源原文。

---

## 3. Source Schema（数据源）

**两分离原则**：静态配置（`config/sources.yaml`）与运行态（`data/sources_state.json`）严格分离。

### 3.1 静态配置（Source — `source.schema.json` 的 `$defs/Source`）
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string(`^[a-z0-9_]+$`) | ✅ | 唯一 id，注册表据此加载 Adapter |
| `name` | string | ✅ | 展示名 |
| `category` | string | ✅ | 分类 |
| `type` | enum `api`/`rss`/`page` | ✅ | 获取方式 |
| `enabled` | boolean | ✅ | 是否参与采集 |
| `priority` | int(≥1) | ✅ | 越小越权威，用于 AuthorityScore |
| `max_items` | int(1–20) | ✅ | 单源上限（=板块上限） |
| `timeout` | int(≥1) | ✅ | 超时秒 |
| `retry_count` | int(≥0) | ✅ | 重试次数 |
| `rate_limit` | string | ✅ | 频率限制，如 `"1/3s"` |
| `legal_status` | enum | ✅ | `official_api`/`official_rss`/`public_page`/`third_party_legal`/`manual` |
| `terms_url` | string\|null(uri) | ❌ | 条款链接 |
| `endpoint`/`query`/`fallback`/`notes` | — | ❌ | 可选扩展 |

整文件为 `SourcesConfig`：`{ version, defaults?, sources[] }`。

### 3.2 运行态（SourceRuntimeState — `sources-state.schema.json`）
| 字段 | 来源 | 类型 |
|---|---|---|
| `source_id` / `name` / `category` / `enabled` | **来自配置** | — |
| `status` | **运行态** | enum `healthy`/`degraded`/`failed`/`disabled` |
| `last_success` / `last_attempt` / `last_error` / `item_count` / `response_time_ms` / `consecutive_failures` / `success_rate_7d` | **运行态** | — |

> 新增/关闭数据源：只改 `config/sources.yaml`，核心逻辑与前端零改动。

---

## 4. Health Schema（`data/health.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 契约版本 |
| `generated_at` | string\|null (ISO8601 UTC) | 快照时间；未运行 null |
| `overall` | `healthy`/`degraded`/`failed`/**null** | **从未运行 = `null`（绝不用 `unknown`）** |
| `sources[]` | SourceHealth[] | 每源健康（见 3.2） |

状态判定：`healthy`(成功且>0) / `degraded`(成功但偏低或走 fallback) / `failed`(本次失败) / `disabled`(配置关闭)。
**隔离原则**：单源失败仅写自己的 `failed`，主流程尽力而为，整站不崩。

---

## 5. PublishedData Schema（`data/YYYY/MM/YYYY-MM-DD.json`）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `date` | string(`YYYY-MM-DD`) | ✅ | 数据日期 |
| `schema_version` | string | ✅ | — |
| `generated_at` | string (ISO8601 UTC) | ✅ | 生成时间 |
| `pipeline_version` | string | ✅ | 与 `pyproject` 版本一致，便于追溯 |
| `ai_enabled` | boolean | ✅ | 本次是否启用 AI |
| `categories` | `Record<catId, {count, items: Trend[]≤20}>` | ✅ | **按分类分组，每块 ≤20 且 `count == len(items)`** |
| `trends` | Trend[] | ✅ | 全板块扁平并集（=各 `categories[id].items` 之和） |
| `events` | Event[] | ✅ | 聚合事件（MVP 可为空 `[]`） |
| `metadata` | `{ run_summary: {sources_ok, sources_failed, total_dropped, generated_by?} }` | ✅ | 运行元信息 |

支持：每日独立保存 / 历史查询 / git 追溯 / 前端读取 / **每板块 ≤20 且不足不凑**。

---

## 6. Index Schema（`data/index.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | — |
| `updated_at` | string\|null | — |
| `latest_date` | string\|null(`YYYY-MM-DD`) | 指针，**非唯一数据源** |
| `available_dates` | string[] | 所有可用日期 |
| `categories` | string[] | 出现过分类 id 并集 |
| `date_index` | `Record<date, {path, total_items, categories}>` | `path` 形如 `2026/07/2026-07-24.json` |

前端据此查询历史日期；支持看今天/昨天/历史/按日期读。

---

## 7. SourcesState Schema（`data/sources_state.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | — |
| `updated_at` | string\|null | — |
| `sources[]` | SourceRuntimeState[] | 运行态（见 3.2），与 `sources.yaml` 分离 |

---

## 8. DataRepository 接口（仅定义，本轮不实现）

前端与任何消费者**只能**通过该接口读数据，**不得直接 import JSON 文件路径**。切换存储（Json→Supabase）仅改工厂一处，UI 零改动。

### TypeScript（`frontend/lib/repository.ts`）
```ts
export interface DataRepository {
  getLatest(): Promise<PublishedData | null>;
  getByDate(date: string): Promise<PublishedData | null>;
  getHistoryIndex(): Promise<DateIndex>;
  getHealth(): Promise<HealthSnapshot>;
  getSourcesState(): Promise<SourcesState>;
  getByCategory(category: string, date?: string): Promise<Trend[]>;
  getEvents(date?: string): Promise<Event[]>;
}
```

### Python（`pipeline/src/pipeline/repository.py`）
```python
@runtime_checkable
class DataRepository(Protocol):
    def get_latest(self) -> Optional[PublishedData]: ...
    def get_by_date(self, date: str) -> Optional[PublishedData]: ...
    def get_history_index(self) -> DateIndex: ...
    def get_health(self) -> HealthSnapshot: ...
    def get_sources_state(self) -> SourcesState: ...
    def get_by_category(self, category: str, date: Optional[str] = None) -> list[Trend]: ...
    def get_events(self, date: Optional[str] = None) -> list[Event]: ...
```

`JsonFileRepository` / `SupabaseRepository` 的实现**不在本轮范围**（见 PROJECT_RULES 第十六部分：实现属于架构落地，当前仅定义接口）。

---

## 9. Python / TypeScript Schema 同步方案（答复问题 9）

**单一事实来源 = `schemas/*.schema.json`**（跨语言、机器可校验）。

| 语言 | 落地方式 | 同步保证 |
|---|---|---|
| Python | `pipeline/src/pipeline/models.py`（Pydantic v2） | 测试 `test_pydantic_matches_json_schema_fields` 断言每个模型的字段名 == JSON Schema 的 `properties` 键；任一方漂移即 CI 红 |
| TypeScript | `frontend/lib/types.ts`（手写类型，与 JSON Schema 对齐） | 人工 review 清单 +（P1）可选 `json-schema-to-typescript` 代码生成，从 JSON Schema 生成 `types.ts` |
| 校验 | `jsonschema`（Python 端）+（P1）Zod（前端运行时） | 生产 JSON 双端校验：Pipeline 写出前校验 + 前端读取时校验 |

**防漂移红线**：任何修改 Trend/Event 字段，必须同步四处——`schemas/*.json`、`models.py`、`types.ts`、`DATA_CONTRACT.md`，并跑 `pytest`（含字段对拍测试）。

---

## 10. 关键设计问题的最终结论（答复用户 10 问）

| # | 问题 | 最终方案 |
|---|---|---|
| 1 | Trend 与 Event 是否都需要 summary？ | **都需要**。`Trend.summary` 单条摘要；`Event.summary` 事件级摘要（可基于成员真实内容，无则 null）。 |
| 2 | Event.sources 存 Source 对象还是 source_id？ | 存 **`source_id` 引用 + 每条 `original_url`/`title`/`hot_score`**，不内嵌完整 Source 配置，兼顾自包含追溯与零冗余。 |
| 3 | Trend 是否直接保存 source_name？ | **保存**（`source_name`，去规范化快照）。便于前端展示且不受配置变更影响；同时保留 `source_id` 用于校验/关联。 |
| 4 | HotScore 放哪？ | **Trend 与 Event 都有**。`Trend.hot_score` 单条分；`Event.hot_score` 成员聚合分；均含 `score_breakdown` 透明分量。 |
| 5 | categories 用字符串/枚举/对象？ | **字符串 id**（如 `ai_research`），非固定枚举；展示元数据（label/icon）由配置驱动，可扩展。当前已知集：`ai_research`/`opensource`/`ai_official`/`tech_news`，**非最终固定**。 |
| 6 | 日期时间格式？ | **ISO 8601 + UTC，后缀 `Z`**（如 `2026-07-24T09:00:00Z`）。`date` 字段为 `YYYY-MM-DD`。 |
| 7 | original_url 是否需要 canonical_url？ | **新增 `canonical_url`**（可空、派生）。用于去重与 `id=hash(source_id+canonical_url)` 稳定性；`original_url` 保持为用户可见真实链接。 |
| 8 | AI 摘要是否保存来源标记？ | **保存** `summary_origin`(`original`/`ai`/`none`) 与 `tags_origin`(`rule`/`ai`/`none`)，保证"哪些是原文、哪些是 AI 加工"完全透明可审计。 |
| 9 | 如何保证 Python/TS 不漂移？ | 见第 9 节：JSON Schema 为单一来源 + 字段对拍测试 + （P1）代码生成。 |
| 10 | 如何确保前端绝不读未验证 JSON？ | 前端只经 `DataRepository`；读取时（P1 Zod / 当前经 JSON Schema 约束的生产数据）先校验，失败则回退 `index.json` 最近可用/空态并告警，**绝不渲染原始未验证 JSON**。 |

---

## 11. 生产发布红线的契约层保证（摘要）

- **零虚构 / 可追溯**：`original_url` 必填且 `format: uri`；`is_mock` 生产必须为 `false`（`validation.py` 强校验）。
- **每板块 ≤20**：`CategoryBlock.items` `max_length=20` + `count == len(items)` 双约束。
- **Mock 不进生产**：`is_mock=false` 强制 + CI 后续将扫描 `data/**` 拒绝 `is_mock:true`。
- **AI 只加工不创作**：`summary_origin`/`tags_origin` 透明标注；AI 不参与 `status`/`original_url`/`hot_score` 事实字段。

---

## 12. 当前状态与下一步

- 阶段 0 与 阶段 1 第一轮已完成：7 个 JSON Schema + Pydantic 模型 + 纯函数校验 + 双语言 Repository 接口 + TS 类型 + 契约测试（Python 26 项 / 前端 11 项，全绿）+ `JsonFileRepository`（前端 `frontend/lib/repositories/`）。
- **测试夹具隔离规则**：`frontend/lib/repositories/__fixtures__/` 仅用于单元测试；它**不会被** Python Pipeline 读取、**不会**发布到 `data/`、**不会**被 GitHub Actions 当作生产数据。即使其中存在 `is_mock=false` 的「合法样本」，它也只是测试夹具，不代表任何真实热点数据。
- 未做（按 PROJECT_RULES 限制）：数据源 Adapter、真实采集、AI、GitHub Actions 定时/部署、Vercel 部署、Mock 生产数据。
- 下一步（待指令）：实现各数据源 Adapter（ArXiv / GitHub / AI 官方 / 科技 RSS）+ 完整 Pipeline（采集→标准化→校验→去重→聚合→评分→排序→截断→发布）。
