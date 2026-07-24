# Daily Trend Radar — Pipeline 架构与接口设计 (Stage 1-2)

> 阶段 1-2 · **架构与接口设计阶段**（仅设计，不实现真实数据源、不连网络、不采真实数据、不造 Mock 生产数据）。
> 制定日期：2026-07-24。权威关系：`PROJECT_RULES.md` > `ARCHITECTURE_REVIEW_v2.md` > `PROJECT_PLAN.md`。
> 本文件与 `ARCHITECTURE_REVIEW_v2.md` 第 2/3/5/6/8/10 节及 `DATA_CONTRACT.md` 完全对齐；凡有澄清均以 v2 为准。

---

## 0. 本轮交付与边界

**新增代码（仅接口 / 内部模型 / 纯函数，无 IO、无网络、无 AI）**：

| 文件 | 内容 | 性质 |
|---|---|---|
| `pipeline/src/pipeline/raw.py` | `RawItem` + `NormalizedItem` 模型 | 新增内部模型 |
| `pipeline/src/pipeline/adapters/__init__.py` | adapter 子包 | 包标记 |
| `pipeline/src/pipeline/adapters/base.py` | `SourceAdapter` Protocol + `AdapterResult` + `safe_fetch`/`run_sources` | 新增接口 + 错误隔离纯函数 |
| `pipeline/src/pipeline/stages.py` | 各 Stage Protocol + 纯边界函数（`canonicalize_url`/`validate_pipeline_item`/`combine_hot_score`/`canonical_id`/`cap_items`/`build_trend`/`build_event`） | 新增接口 + 纯函数 |
| `pipeline/src/pipeline/ai.py` | `AIProcessor` Protocol + `NullAIProcessor` | 新增接口（纯透传，无 AI 调用） |
| `pipeline/tests/test_pipeline_design.py` | 接口 / 契约测试（33 项，全绿） | 新增测试 |

**未修改（严格遵守「四」禁止清单）**：
- `schemas/*.schema.json`（JSON Schema 单一事实来源）—— **未动**。
- `pipeline/src/pipeline/models.py`（Pydantic 生产模型）—— **未动**，仍是 Published 数据唯一真相。
- `pipeline/src/pipeline/repository.py`（`DataRepository` 接口）—— **未动**。
- `validation.py`（生产红线纯函数）—— 未动，本设计新增的 `validate_pipeline_item` 是其**上游**（Pipeline 内部红线性检查），二者互补不冲突。

**未做（按用户与 PROJECT_RULES 红线）**：不实现 ArXiv/GitHub/RSS 等真实 Adapter；不调用网络 / API / RSS；不启用 AI；不创建 Mock 生产数据。

---

## 1. Pipeline 总览

数据闭环（与 v2 第 2.2 节逐字对齐）：

```
[Adapter]   fetch()  ──►  RawItem[]            # 单一源原始条目
    │
[Normalize]         ──►  NormalizedItem[]     # 字段统一/URL 归一/时间统一/文本清理
    │
[Validate]          ──►  kept / dropped       # 生产红线性：original_url/title/source_id/category/is_mock
    │
[SourceVerify]      ──►  kept / dropped       # original_url 域名必须与声明源一致
    │
[Deduplicate]       ──►  NormalizedItem[]     # 同一 source + 同一 canonical_url 去重
    │
[Cluster/Event]     ──►  Event[]              # 跨源同事件归并（一对多，不删原 Trend）
    │
[HotScore]         ──►  score + breakdown    # 5 维透明公式，纯规则，无 AI
    │
[Rank]             ──►  按 hot_score 排序
    │
[Cap ≤20/板块]    ──►  Top 候选             # ★先截断，只留最终会发布的条目
    │
[AI Enrich]        ──►  Trend（可关闭）    # ★只对 ≤20 调用：摘要/标签/标题
    │
[AI FactCheck]     ──►  通过/回退原文        # AI 输出必须可回溯，否则丢弃
    │
[Publish]          ──►  PublishedData        # 组装 + 写 JSON + 更新 index/health
```

**关键顺序铁律**：AI 在 **截断 ≤20 之后**；HotScore 在 **Event 聚合之后**（MultiSourceScore 需要 `Event.source_count`）。

---

## 2. Adapter Interface（`adapters/base.py`）

统一 `SourceAdapter` 契约（`@runtime_checkable` Protocol）。未来每个数据源实现一份：

`ArXivAdapter` · `GitHubAdapter` · `OfficialRSSAdapter` · `TechRSSAdapter` · `BilibiliAdapter` · `WeiboAdapter` · `CoolapkAdapter` · `XiaoheiheAdapter` · `DouyinAdapter`

**必须考虑的字段（来自 `SourceConfig`，构造时注入）**：
- `source_id: str` —— 注册表加载键，== `config.id`
- `category: str` —— 目标板块，== `config.category`
- `config: SourceConfig` —— 携带 `timeout` / `retry_count` / `rate_limit` / `enabled` / `legal_status` / `priority` / `max_items` / `endpoint` / `query` / `fallback` / `terms_url`
- `fetch() -> list[RawItem]` —— **唯一职责方法**

**Adapter 只负责**：从**单一**数据源拉取原始数据并做源特定的 `parse` → 产出 `RawItem[]`。

**Adapter 不负责（绝不可实现）**：
- HotScore / 评分
- Event 聚合 / 聚类
- AI 处理（摘要/标签/分类）
- Top 20 截断
- PublishedData 组装
- 任何 UI

**错误隔离**：`fetch()` 内部自包 try/except，失败应**抛异常或返回 `[]`**，绝不可吐出假数据；异常由 `safe_fetch` 捕获（见 §13）。

> **澄清（非冲突）**：`PROJECT_RULES` 第 5 节 / `PROJECT_PLAN` 第 12 节曾把 `BaseAdapter` 写成含 `fetch/parse/normalize/validate/health`。本设计将其**澄清**为：源特定的 `parse` 内置于 `fetch()` 产出 `RawItem`；而**通用的** `normalize`/`validate` 属于下方共享 Pipeline Stage，不属 Adapter 方法。这与 v2 第 2.2 节步骤 [1]「各 Adapter 拉原始数据 → RawItem[]」完全一致，属措辞对齐，非架构冲突，故**不改动** v2 / PROJECT_PLAN。

---

## 3. RawItem（`raw.py`）

`RawItem` = 某 Adapter `fetch()` 的产出，**采集到的最原始条目**。

**必含字段**：
- `source_id: str`
- `source_name: str` —— 采集时点来源名快照（去规范化）
- `original_url: str` —— **必填，真实性核心**（见 §6）
- `source_item_id: str` —— 源内稳定 id（去重辅助）
- `fetched_at: datetime`
- `lang: str = "en"`
- `metadata: dict` —— 源特定原始字段（rank/stars/浏览量…），原样携带，**绝不作为事实重新解释**

**可选字段**：`title?` · `published_at?` · `summary?`（源提供的**原始**文本，非 AI）

**硬性禁止（由设计保证，非代码强制但契约如此）**：
- ❌ 不得携带 HotScore / `event_id` / `status` / `is_mock`
- ❌ 不得含 AI 生成文本（`summary` 仅允许源原始文本）
- ❌ 不得在 Raw 阶段计算热度或生成 Event

`RawItem.as_normalized(category)` 是 Normalize 阶段的桥梁：把原始字段映射为 `NormalizedItem`，`status=DRAFT`、`is_mock=False`，**不发明任何事实**。

---

## 4. Normalize（`stages.py: NormalizeStage` + `canonicalize_url`）

**只做**：
- 字段统一（命名/类型对齐到 `NormalizedItem`）
- **URL canonicalization**（`canonicalize_url`）：scheme/host 转小写、剥离追踪与引流参数（`utm*`、`fbclid`、`gclid`、`ref`、`feature`…）、去 fragment、去路径尾斜杠
- 时间格式统一（统一为带时区的 `datetime`）
- 文本清理（去多余空白等）
- 来源字段映射（`category` 取自源配置）

**不能做**：❌ 生成不存在的事实 · ❌ 编造摘要 · ❌ 制造热度。

> `canonical_url` 由 `canonicalize_url(original_url)` 得出，用于去重与 `id = hash(source_id + canonical_url)` 的稳定性。

---

## 5. Validation（`stages.py: ValidationStage` + `validate_pipeline_item`）

Pipeline 内部红线性检查（上游于 `validation.py` 的生产契约）。`validate_pipeline_item(item, valid_categories) -> list[str]` 返回违规信息列表，空即放行。

**至少覆盖**：
1. `original_url` 必填且非空
2. `original_url` 格式合法（http/https + 有 host）
3. `source_id` 必填
4. `title` 必填（normalize 后非空）
5. `category` 属于已配置集合
6. `published_at`（若有）不在未来
7. 生产 `is_mock` 必须为 `False`（原始数据绝不 mock）
8. `summary_origin` 在 pipeline 阶段只能是 `original`/`none`（AI 尚未介入）
9. 单条失败 → **丢弃该条**，不修复、不阻断整批

> 责任划分：**Adapter** 保证取出的条目结构基本可用；**Normalize** 做字段/URL/时间统一；**Pipeline Validation** 做上述红线性裁决；**PublishedData 最终校验**（`validation.py`）在组装后再次兜底（§12）。

---

## 6. Source Verification（`stages.py: SourceVerifyStage`）

`original_url` 是**真实性核心**。

- Adapter 获取的每条数据**必须带 `original_url`**。
- `original_url` **不得由 AI 生成**，也**不得使用虚构 URL**。
- 校验：URL 主机必须落在**该来源的「允许官方域名集合」`allowed_domains`** 之内；不在集合内 → 丢弃。
  - **为什么用「集合」而非单个 `declared_domain`（Stage 1-2.1 Q2）**：真实来源常从多个官方主机出稿（如 GitHub 同时有 `github.com` / `gist.github.com` / `api.github.com`），若强制「域名必须 == 单一声明域」会**误杀**合法条目；过严等于制造漏报。因此改为「允许域名集合」，匹配规则安全：`host == 允许域` 或 `host.endswith("." + 允许域)`（可抗 `github.com.evil.net`、`notgithub.com` 这类后缀伪造）。
  - 纯函数 `verify_original_url(url, allowed_domains, require_https=True) -> bool` 已实现并契约测试；`SourceVerifyStage.verify(item, allowed_domains)` 同步改为接收**集合**。
  - **Schema 改动（已落地 · Stage 1-3A）**：首个真实源 ArXiv 接入时，已为 `SourceConfig` 新增 `allowed_domains: list[str] | null`（同步 `source.schema.json` / `models.py` / `types.ts` / `DATA_CONTRACT.md` §3.1）。`verify_original_url` 的防御逻辑（抗 `arxiv.org.evil.com` 后缀伪造）现在能被真实源配置驱动；ArXiv 配置填 `["arxiv.org"]`。详见 §17 Q2 与最终汇报。
- 无法验证来源的条目**不得进入 published**。
- 异常处理（属 §13 错误隔离范畴）：
  - 来源访问失败 / HTTP 状态码异常 / 超时 → 该次采集标记失败，不抛到主流程
  - **单条**解析失败 → 丢弃该条
  - **单源**失败 → 记 `health=failed`，其他源继续
- 绝不为了「凑数」把未验证数据塞进发布集。

---

## 7. Deduplication vs Event Aggregation（`DeduplicationStage` vs `EventAggregationStage`）

**去重（Dedup）**：同一 `source_id` + 同一 `canonical_url` 视为同一条。键由 `canonical_id(source_id, canonical_url) = sha256(f"{source_id}|{canonical_url}")[:16]` 计算；相同键碰撞即去重（保留信息最全/热度最高者）。

**事件聚合（Event）**：把**不同 URL 但同一真实事件**的多条 Trend 归并为一个 `Event`（一对多）。原始 Trend **不删除**，仅通过 `event_id` 反向关联；UI 折叠展示、展开可见全部来源原文。

**绝不混淆**：
| 情况 | 归属 |
|---|---|
| 同源 + 同 URL | **Dedup**（同键碰撞） |
| 同源转载（同事件不同链接） | **Event 聚合**（不同 URL） |
| 跨平台同一事件（不同 URL） | **Event 聚合** |
| 标题相似但 URL 不同 | **Event 聚合**（不删，保留多来源价值） |
| 标题相同但 URL 不同 | **Event 聚合**（非 Dedup） |

> Stage 1-2 **只用规则/相似度/URL/关键词**判断同事件（TF-IDF 余弦 / URL 同源 / 关键词重叠），**不用 AI 判断**归属（AI 仅未来 P1/P2 作辅助，且核心去重/聚合不可完全依赖 AI，见 PROJECT_RULES 第 4 节）。

---

## 8. Event Aggregation（`EventAggregationStage` + `build_event`）

- **一对多**：一个 `Event` 关联多个 `Trend`；每个 `Trend.event_id` 反向指向它。
- **不删原 Trend**：`Event.sources[]` 用 `EventSourceRef` 保留每个来源的 `source_id` + `original_url` + `title` + `hot_score`，逐条可追溯。
- `published_at` = 最早成员时间；`updated_at` = 最新成员时间。
- `hot_score` / `score_breakdown` **不在 `build_event` 时计算**：`build_event` 仅产出占位（0），真正的回填由 **`finalize_event(event, members)`** 在 **HotScore 阶段之后**执行——取 `max(member.hot_score)` 作为 `Event.hot_score`、各维 `max` 作为 `Event.score_breakdown`（见 §9 / §17 Q3）。`sources` / `source_count` / `trend_ids` 在集群阶段已由 `build_event` 设定，`finalize_event` 不改动。
- **`source_count` 语义（Stage 1-2.2 已落地 ✅）**：正式定义 **`source_count = len({s.source_id for s in sources})`**，即 **`sources[]` 中 distinct `source_id` 的数量**，**不等于 `len(sources)`**。配套：`sources[]` 保留每一条来源证据（`{source_id, original_url}`），**绝不因 `source_id` 相同而删除来源证据**（同一媒体发多篇转载/更新：每条 `original_url` 仍逐一保留，但 `source_count` 只计一次，避免人为抬高 MultiSourceScore）。已同步：`DATA_CONTRACT` §2 正式契约 + §2.1（PENDING → 已落地）、`validation.py:validate_event`（`source_count != len(去重 source_id)` 报错）、`stages.py:build_event`（`source_count` 用去重计数）、`event.schema.json` 描述、`types.ts` 注释、`ARCHITECTURE_REVIEW_v2.md` 对应行。详见 §17 Q4。

**MVP 方案**：同 `category` 内、时间窗（如 48h）内、文本相似度 > 阈值 τ 的 Trend 归为一簇；事件名取簇内最高热度标题（或未来 AI 基于真实标题命名，不创作）。**保守 MVP 聚合规则（宁少勿错）详见 §17 Q5**，本轮**不使用 AI 做聚合**。

---

## 9. HotScore（`stages.py: HotScoreStage` + `combine_hot_score`）

**不依赖 AI**，透明、可解释，与 v2 第 10 节逐字一致。

```
hot_score = 100 * clamp01(
    W_auth * AuthorityScore     # 来源权威性（config.priority 映射，越小越高）
  + W_heat * HeatScore          # 源内互动量对数归一 log1p(x)/log1p(max)
  + W_fresh * FreshnessScore    # 时间衰减 exp(-Δt/τ)
  + W_multi * MultiSourceScore  # min(1, source_count / K)
  + W_plat * PlatformWeight     # 平台权重（config）
)
```

**默认权重（可配置）**：`W_auth=0.25  W_heat=0.30  W_fresh=0.20  W_multi=0.15  W_plat=0.10`（`HotScoreWeights`）。

**计算时机（明确，Stage 1-2.1 Q3 锁定）**：
1. **`Trend.hot_score` 在 Event 聚合「之后」算**（步骤 [7]）：因为 `MultiSourceScore` 维度依赖该 Trend 所属 `Event.source_count`（同一事件跨了多少来源）。先聚合、再评分，顺序铁律。
2. **`Event.hot_score` 在 HotScore 阶段「之后」回填**：由纯函数 `finalize_event(event, members)` 取 `max(member.hot_score)`；`Event.score_breakdown` 取各维 `max`（代表性最热分量）。`finalize_event` 不触 AI、不重算，仅把已算好的 Trend 分聚合到事件层。
3. **`MultiSourceScore` 是「Trend 维度」**：作用在单条 Trend 上，其值 = `min(1, 所属 Event.source_count / K)`；事件层不单独再算一遍 MultiSource。
4. **`Event.hot_score` 不可绕过 Trend 直接编造**：只能 = 成员 Trend 分的最大值（一致性由 `finalize_event` 保证）。
5. **`Event.hot_score` 是否「重算」**：否——它不做独立评分，仅聚合已算好的成员分；`score_breakdown` 同理做元素级 `max`（保留透明分量）。

**Trend score 与 Event score 关系**：每个 `Trend.hot_score` 由 5 维算得；`Event.hot_score` = 其成员 `Trend.hot_score` 的聚合（取 `max`，最能代表事件热度）。两者均带 `score_breakdown` 透明分量。`source_count` 的精确定义：**`len({s.source_id for s in sources})` = distinct `source_id` 数量，不等于 `len(sources)`**（已于 Stage 1-2.2 落地，见 §8 / §17 Q4）。
**只归一不造数**：缺失分量降权或置 0，绝不臆造热度；`heat_raw` 原样保留供审计。

---

## 10. Top 20（`stages.py: TopStage` + `cap_items`）

- **每 `category` 最多 20 条**（`cap_items(items, max_per_category=20)` 取前 N）。
- **不是必须 20**：真实合格只有 5 条就只发 5 条（`cap_items` 永不补位）。
- **位置铁律**：Top 20 在 **AI 之前**（先 `Rank` → 再 `Cap ≤20` → 才 `AI Enrich`）。AI 只对最终 ≤20 条/板块调用，成本最小化、不对低质量数据调 AI。

---

## 11. AI（`ai.py: AIProcessor` + `NullAIProcessor`）

**可配置 / 可关闭**：`ai.enabled=false` 时选用 `NullAIProcessor`（纯透传，不触网、不调 LLM）。

**AI 可以**：① 改写摘要（基于真实来源文本）② 生成标签 ③ 优化标题（忠实原文）。

**AI 不可以**：① 生成事实 ② 生成 URL ③ 添加不存在的来源 ④ 修改 `published_at` ⑤ 修改 `heat_raw` ⑥ 提高 `HotScore` ⑦ 创建不存在的 Trend。

**失败回退**：`AIProcessor.enrich(trend)` 失败时**必须返回输入 `trend` 原样**（回退原文，绝不返回替代事实）；`fact_check(trend, original) -> bool` 判定 AI 输出是否可回溯到输入文本，不通过则丢弃 AI 结果、回退 `original`。

**透明**：`summary_origin` / `tags_origin` 标注 `original`/`ai`/`none`，全程可审计。

---

## 12. Publish（`stages.py: PublishStage`）

组装 `PublishedData`（结构见 `DATA_CONTRACT.md` 第 5 节）：`date` / `schema_version` / `generated_at` / `pipeline_version` / `ai_enabled` / `categories`（每板块 `count == len(items)` 且 ≤20）/ `trends`（扁平并集）/ `events` / `metadata.run_summary`。

**最终校验（兜底）**：组装后必须用 `validation.py` 的 `validate_production_trend` + `validate_published_data` 复核——
- 每条 `is_mock == false`
- 每条 `original_url` 非空
- 每板块 `count == len(items)` 且 `len ≤ 20`
- 任一不满足 → **不得发布**，整批回退记录，绝不带病上线。

---

## 13. Error Isolation（错误隔离）

| 层级 | 策略 |
|---|---|
| 单条失败 | 解析/校验失败 → 跳过该条（`validate_pipeline_item` 返回违规、丢弃） |
| 单源失败 | `safe_fetch(adapter)` 捕获异常 → `AdapterResult(items=[], health=SourceHealth(status=failed))`，**异常绝不外泄** |
| 多源编排 | `run_sources(adapters)` 逐源 `safe_fetch`，**失败源隔离、其他源继续**产出 |
| AI 失败 | `enrich` 回退原文；单条失败不影响其他条目与整体发布 |
| 最终校验失败 | `validate_published_data` 不通过 → 不发布 |

> 主流程「尽力而为」：任一源失败 → 跳过 → 其他源正常产出 → 该板块前端诚实展示「数据源维护中 / 暂无数据」。**单源失败绝不拖垮全站**（v2 第 6.3 节）。

---

## 14. Data Lifecycle（数据生命周期）

三态（v2 第 3 节）：`Raw` → `Processed` → `Published`。

- **Raw**：仅 Adapter 运行内存 / 临时目录，运行结束即弃；MVP **不长期保存**完整原始 HTML/正文（合规与体积考量，可追溯性由 `original_url` 保证）。
- **Processed**：`NormalizedItem` → `Trend` 候选等中间结构，仅 Actions 运行内临时产物，不提交仓库。
- **Published**：最终 `data/YYYY/MM/YYYY-MM-DD.json`（+ `index.json` / `health.json` / `sources_state.json`），长期保存并 git 版本化。

允许留存（不膨胀生产数据）：脱敏 fixtures（`pipeline/tests/...`，仅供离线单测）、运行日志摘要（每源条数/丢弃数/错误/耗时 → `health.json` 与 Actions 日志）。

---

## 15. MVP 处理流程图

```
                       config/sources.yaml (静态, 两分离)
                                │
            ┌───────────────────┴───────────────────┐
            │  run_sources(adapters)  ← 错误隔离编排      │
            │   for each enabled source:                    │
            │     safe_fetch(adapter)                      │
            │       ├─ OK  → AdapterResult(items, healthy) │
            │       └─ ERR → AdapterResult([], failed)    │
            └───────────────────┬───────────────────┘
                                    │  RawItem[] (per source, isolated)
                                    ▼
            Normalize ─► NormalizedItem[] ─► Validate ─► SourceVerify
                                    │  (drop 违规/不可验证)
                                    ▼
                            Deduplicate (canonical_id)
                                    ▼
                            Cluster → Event[]  (一对多, 不删原 Trend)
                                    ▼
                            HotScore (5 维, 用 Event.source_count)
                                    ▼
                            Rank → Cap ≤20/板块  ← ★AI 之前
                                    ▼
                    ai_enabled? ── no ─► NullAIProcessor (透传)
                                │ yes
                                ├─ AI Enrich (摘要/标签/标题)
                                └─ AI FactCheck ─ 失败 ─► 回退原文
                                    ▼
                    Publish: assemble PublishedData
                    + validate_production (兜底) ─ 失败 ─► 不发布
                                    ▼
            data/YYYY/MM/YYYY-MM-DD.json + index.json + health.json
```

---

## 16. 未来 Adapter 扩展方式

1. **评估先行**（PROJECT_RULES 第 17 节）：数据来源、合法性 `legal_status`、API/RSS 可用性、`robots.txt`、服务条款、频率限制、稳定性、降级方案、`original_url` 可靠性。**只有合法且通过评估的源才开发 Adapter**；任何需绕过登录/验证码/访问控制/破解签名/反爬技术保护的实现一律禁止合入。
2. **在 `adapters/` 新增一个模块**，实现 `SourceAdapter` 契约（`source_id` / `category` / `config` / `fetch()`），内部完成源特定 `parse → RawItem[]`。
3. **在 `config/sources.yaml` 加一段**（id/name/category/type/enabled/priority/max_items/timeout/retry_count/rate_limit/legal_status/terms_url/endpoint…），`registry` 据此自动加载；**关闭只需 `enabled: false`**，核心逻辑与前端零改动。
4. **配 fixture**（脱敏真实响应样本）做离线单测，不打真实 API（PROJECT_RULES 第 13 节）。
5. **内建多级降级**（v2 第 16 节）：L0 Primary → L1 Fallback → L2 Stale（标注「数据可能非最新」）→ L3 Skip（前端诚实展示，绝不用假数据填充）。
6. **健康记录**：`fetch` 结果经 `safe_fetch` 产出 `SourceHealth`，汇入 `health.json` 与 `sources_state.json`。

> 本轮**不实现**任何具体 Adapter（ArXiv/GitHub/RSS/社交/游戏等），仅固化上述接口与扩展契约，供阶段 1 后续落地。

---

## 17. 架构审查澄清（Stage 1-2.1 · 五问结论）

> 本轮仅审查并澄清 5 个架构问题，**不扩大范围**、不接真实 API/RSS/ArXiv/GitHub/AI/网络、不造 Mock 生产数据、不提交 Git。结论如下。

### Q1 · `NormalizedItem` 中间态语义（Doc-only，已加契约测试）
- `NormalizedItem` 是**纯内部中间态**，**既不等于 `Trend`，也不等于 `PublishedData`**。它不含 `hot_score` / `score_break_down`（由 HotScore 阶段后填），也不含 `event_id`（由 Event 聚合阶段后填）。
- `is_mock=False` 的准确含义是「**这不是测试桩 mock**」，**绝不**等同于「这是已信任的生产数据」。要成为生产数据，还需经 SourceVerify → HotScore → `build_trend(status=PUBLISHED)` 且通过 `validate_production_trend`（`status=published` + `original_url` + `is_mock=false`）。
- `status=DRAFT` 的准确含义是「**已进入 pipeline**」，**绝不**等同于「已通过生产校验」。契约测试 `test_normalized_draft_is_not_production_ready` 已锁定：一个 `DRAFT` 的 Trend 会被 `validate_production_trend` 判红。
- **未改** `Trend` / `PublishedData` / 任何 Schema。

### Q2 · Source Verification 与 `allowed_domains`（已改代码 + 延期 Schema）
- 旧约「URL 域名必须 == 声明 source 的单一域」**过严**：真实源（如 GitHub）会从多个官方主机出稿，强制单域会误杀合法条目。
- 改为 **`allowed_domains: set[str]`（允许官方域名集合）**，纯函数 `verify_original_url(url, allowed_domains, require_https=True) -> bool` 已实现：匹配 `host == 域` 或 `host.endswith("." + 域)`（抗 `github.com.evil.net`、`notgithub.com` 后缀伪造）；`require_https` 默认开启。
- `SourceVerifyStage.verify(item, allowed_domains)` 签名同步改为接收**集合**。
- **Schema 改动（已落地 · Stage 1-3A）**：首个真实源 ArXiv 接入时，已为 `SourceConfig` 新增 `allowed_domains: list[str] | null`，并同步四处（`source.schema.json` / `models.py` / `types.ts` / `DATA_CONTRACT.md` §3.1）+ 字段对拍测试。此 Schema 改动在 1-2.1 按红线「不悄悄改 Schema」**延期到接入真实源时再补**，现于 Stage 1-3A 补上。

### Q3 · `Trend.hot_score` 与 `Event.hot_score` 时机一致性（已改代码 + Doc）
- 逻辑自洽，结论：
  1. `Trend.hot_score` 在 **Event 聚合之后**算（步骤 [7]），因 `MultiSourceScore` 依赖所属 `Event.source_count`。
  2. `Event.hot_score` 在 **HotScore 阶段之后**由 `finalize_event(event, members)` 回填 = `max(member.hot_score)`；`score_break_down` = 各维 `max`。
  3. `MultiSourceScore` 是 **Trend 维度**（作用在单条 Trend），事件层不单独重算。
  4. `Event.hot_score` 不可绕过 Trend 编造，只能取成员最大值。
  5. `Event.hot_score` 不做独立评分，仅聚合已算好的成员分（保持透明 `score_break_down`）。
- 新增纯函数 `finalize_event`（post-HotScore 回填）与契约测试 `test_finalize_event_takes_max_member_score`。**未改** v2 / PROJECT_PLAN / Schema。

### Q4 · `Event.source_count` 语义（✅ 已落地 · Stage 1-2.2）
- **最终定义（用户确认采用）**：**`source_count = len({s.source_id for s in sources})`** = `sources[]` 中 **distinct `source_id` 的数量**。
- **`Event.sources[]` 最终定义**：**来源证据集合**——保留每一条来源证据 `{ source_id, original_url }`，**绝不因 `source_id` 相同而删除来源证据**。例：`sources = [tc/A, tc/B, openai/C]` → `len(sources)=3` 但 `source_count=2`（distinct = {tc, openai}）。
- **关键约束**：`source_count` 不等于 `len(sources)`；同一媒体发多篇转载/更新，每条 `original_url` 仍逐一保留为来源证据，但 `source_count` 只计一次，避免人为抬高 `MultiSourceScore`。
- **已落地改动（Stage 1-2.2）**：① `DATA_CONTRACT` §2 正式契约改写（`source_count` = distinct source_id 数量，≠ `len(sources)`）+ §2.1 由 PENDING 转为「已落地」；② `validation.py:validate_event` 改断言 `source_count != len(去重 source_id)`（`trend_ids` 仍 = 全成员 trend_id 集合，保持成立）；③ `stages.py:build_event` 的 `source_count` 改为去重计数；④ `event.schema.json` 的 `source_count` 描述同步；⑤ `types.ts` 注释同步；⑥ `ARCHITECTURE_REVIEW_v2.md` 对应行同步。**未改** `models.py` / `repository.py`（`Event`/`EventSourceRef`/`Trend` 字段已够用，无需加字段）。
- **新增契约测试**（见 `test_pipeline_design.py` §15）：单源单 URL=1、双异源双 URL=2、双同源双 URL=1、A+A+B=2、错误 source_count 校验失败、sources[] 不因同 source_id 被错误去重；HotScore 回归：A+A+B → source_count=2，`MultiSourceScore` 按 2（非 3）计算。

### Q5 · Event Aggregation MVP 规则（Doc-only 保守方案，本轮不用 AI）
- **MVP 铁律：宁可少聚合，也不要错误聚合。**
- 纯函数 `decide_event_merge(a, b, keyword_overlap_min=2, window_hours=48) -> bool` 已落地，合并**仅**在以下任一成立时：
  1. **canonical URL 完全一致** → 同一真实条目，合并；
  2. **核心实体匹配 且 时间窗内 且 核心关键词重叠 ≥ 阈值** → 合并。
- **标题相似度绝不作为单独触发条件**：即便标题完全相同，只要实体/关键词不匹配、URL 不同，就**不合并**（保守）。标题相似度可作为 P1 辅助信号，但 MVP 决定性逻辑中排除，以防误聚。
- **不确定 → 保持为独立 Event**。本轮**不使用 AI 做聚合**（规则/相似度/URL/关键词/时间窗即可）。
- 契约测试覆盖：同 canonical URL 合并、仅标题相似不合并、实体+窗+关键词合并、关键词重叠不足不合并、超时间窗不合并。

---

## 附：与现有文档/代码的关系

- **未改动** `ARCHITECTURE_REVIEW_v2.md` / `PROJECT_PLAN.md` / `PROJECT_RULES.md`：本设计与三者一致，仅对 `BaseAdapter` 职责做了**澄清**（§2），无需改文档。
- **未改动** `schemas/*.json` / `models.py` / `repository.py` / `validation.py`：契约单一事实来源保持不变；本设计新增的 `RawItem`/`NormalizedItem`/`SourceAdapter`/各 Stage 为**上游处理边界**，与 `Trend`/`Event` 生产模型通过 `build_trend`/`build_event` 显式衔接。
- **新增契约测试** `tests/test_pipeline_design.py`（54 项，全绿）锁定上述边界：Adapter 契约、错误隔离、RawItem 结构、Normalize、Validation 红线、HotScore 组合、Dedup 键、Top20、AI 边界、组装器；**Stage 1-2.1 新增** Q1（Normalized 中间态语义）、Q2（`verify_original_url` / `host_of` 允许域名集合）、Q3（`finalize_event` 事件分回填）、Q5（`decide_event_merge` 保守聚合）；**Stage 1-2.2 新增** Q4 §15（`source_count` = distinct `source_id` 计数：单源=1 / 双异源=2 / 双同源=1 / A+A+B=2 / 错误值校验失败 / `sources[]` 不因同 `source_id` 被错误去重 / HotScore 回归按 distinct 计数）。运行：`pytest tests/test_pipeline_design.py`（全绿）。**全仓测试 80 项全绿**（设计 54 + 既有契约 26）。
