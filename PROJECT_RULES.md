# PROJECT_RULES.md — Daily Trend Radar 最高级开发规范

> 本文件是 **整个项目的最高级开发规范（最高优先级）**。
> 任何开发、修改、重构、数据采集、AI 处理、部署操作，都必须遵守本文件。
>
> **权威关系（冲突裁决）**：
> - 本文件的「原则与红线」高于一切实现代码与临时决策。
> - 架构细节以 `docs/ARCHITECTURE_REVIEW_v2.md` 为权威依据；若本文件与 v2 在「如何落地」上存在冲突，**以 v2 为准**。
> - `docs/PROJECT_PLAN.md` 为 v1.1 规划书，与 v2 冲突时以 v2 为准。
>
> 制定日期：2026-07-24 · 阶段：阶段 0（地基建设 · 规则固化）
> 维护要求：任何对本文的修改，必须经过「架构变更规则（第十六部分）」评审并明确记录变更原因。

---

## 零、运行架构红线（Local-first / Self-hosted）

> 本项目采用 **Local-first / Self-hosted（本地运行 / 自托管）** 架构。

**红线（不可妥协）**：

1. **不得引入中心化后端**作为项目正常运行的强制依赖；Pipeline 与前端均可在用户本机独立运行。
2. **不得引入云数据库**（Supabase / PostgreSQL 等）作为项目正常运行的强制依赖；数据默认存于用户本机 `data/`。
3. **不得引入用户登录、多用户账户或中心化用户系统**作为项目正常运行的强制依赖。
4. 用户应能够在**自己的电脑上独立运行 Pipeline 和前端**：本机发起采集请求、本机处理、本机生成 `data/YYYY/...`、本机通过 `localhost` 访问前端。
5. 公网部署（如 Vercel）**仅可作为可选的个人演示 / 高级用法**，不得作为默认运行路径，也不得成为普通用户体验项目的先决条件。
6. 若未来确实需要数据库（如搜索 / 历史规模），只允许规划为**可选的本地 SQLite**，不得引入云数据库。
7. 若未来实现「收藏」等个人偏好，仅考虑浏览器 `localStorage` 等**本地**方式，不落地服务端账户。

> 本红线优先级等同「真实性红线」；与本文其他章节冲突时，以本节为准进行收敛。

---

## 一、项目基本信息

- **项目名称**：Daily Trend Radar
- **中文名称**：每日热点雷达
- **项目定位**：真实、可追溯、合法合规的每日互联网热点与前沿资讯聚合平台。
- **核心目标**：聚合真实互联网热点、AI 前沿资讯、科技资讯、开源动态，以及未来扩展的主流平台热点。

**架构基调（确认保留，详见 v2 第 1 节；运行模型以「零、Local-first 红线」为准）**：

> **默认运行模型为 Local-first**：用户在本机运行 Python Pipeline（本机直接访问公开数据源）→ 本机生成 `data/YYYY/...` → 本机运行 Next.js → 浏览器 `localhost` 访问。下图中的 GitHub Actions / Vercel 仅作**可选**的公网部署形态，不是默认路径。

```
用户电脑（本机）
    ↓ 本地运行 Python Pipeline，直接访问公开数据源（arXiv / GitHub / 官方 RSS 等）
生成按日期分片的 JSON 数据（+ index.json + health.json，存于本机 data/）
    ↓
本机运行 Next.js（npm run dev / npm run start）
    ↓
浏览器通过 localhost 访问本地 Web UI
```
> （可选公网演示形态：GitHub Actions 定时采集 + commit 数据 + Vercel 部署；非默认，详见 v2。）

**MVP 阶段明确不引入**：独立后端服务器、PostgreSQL、Redis、Kafka、Docker、Kubernetes。

**演进能力保留**：所有数据读取必须经过 `DataRepository` 抽象接口，前端/API 只依赖接口，不感知底层存储。MVP 默认 `JsonFileRepository`（读本机 `data/**/*.json`）；未来若确有需要，可切换为**可选的本地 SQLite Repository**，切换仅改工厂函数一处，UI 与业务逻辑零改动。**不规划云数据库（Supabase / PostgreSQL）实现**（见「零、运行架构红线」）。

---

## 二、真实性红线

真实性是产品的灵魂。以下任一条被违反，即视为严重事故。

1. 严禁虚构任何新闻、热点、标题、来源、时间、热度。
2. 每条生产数据必须有 `original_url`。
3. `original_url` 必须指向真实来源（URL 格式合法、域名与声明来源一致）。
4. 无法验证来源的数据不得进入生产数据。
5. 不允许为了达到 20 条而凑数。
6. 每个板块最多 20 条。
7. 如果只有 5 条真实有效数据，只展示 5 条。
8. 禁止使用 AI 生成不存在的新闻。
9. 禁止 AI 修改事实。
10. AI 只能对真实来源进行摘要、分类、标签和辅助聚合。
11. AI 输出必须经过一致性检查（可回溯到输入文本，否则丢弃）。
12. AI 失败时必须回退到原始真实信息，不得生成替代事实。

**兜底原则**：宁可少展示真实数据，也不能展示虚假数据。

---

## 三、数据采集合规

采集全程必须遵守目标平台的规则与法律法规。

**获取方式优先级（硬性）**：

1. 优先使用官方 API。
2. 其次使用官方 RSS。
3. 其次使用合法公开数据。
4. 最后才考虑公开无鉴权页面解析。

**必须守规矩**：

5. 遵守 `robots.txt`。
6. 遵守网站服务条款。
7. 遵守 API 使用条款。
8. 遵守访问频率限制（尊重 429 / `Retry-After`）。

**绝对禁止（红线）**：

9. 禁止绕过登录。
10. 禁止绕过验证码。
11. 禁止绕过访问控制。
12. 禁止破解签名。
13. 禁止绕过反爬技术保护。
14. 禁止使用非法或来源不明的数据接口。

**降级链路（不得为自动化而违规）**：

```
自动采集 → 半自动采集 → 人工录入 → 暂不上线
```

若某数据源无法合法稳定获取，必须使用上述降级方案。绝不允许为了"自动化"而违反合规要求。

---

## 四、数据 Pipeline 原则

标准 Pipeline 顺序（与 v2 第 2 节一致；此处「Validate」已内建来源验证）：

```
Collect（采集）
    ↓
Normalize（标准化）
    ↓
Validate（字段校验 + 来源验证：original_url 存在且域名与来源一致，非法则丢弃）
    ↓
Deduplicate（去重）
    ↓
Cluster（事件聚合）
    ↓
Score（HotScore 评分）
    ↓
Rank（排序）
    ↓
Cap ≤20（每板块截断，先截断再调 AI）
    ↓
AI Enrich（AI 摘要/分类/标签，可开关）
    ↓
AI Consistency Check（AI 事实一致性检查，不通过则回退原文）
    ↓
Publish（组装发布：写 JSON + 更新 index.json + health.json）
```

**AI 不负责（绝不参与）**：

1. 创造事实。
2. 验证新闻是否真实。
3. 决定原始来源是否存在。
4. 伪造来源。
5. 伪造热度。
6. 伪造发布时间。

**AI 只负责（辅助加工）**：

1. 摘要。
2. 分类。
3. 标签。
4. 对已经确定发布的数据进行辅助信息处理（如基于真实标题生成事件名）。

**降级约束**：

- AI 应在「截断 ≤20」之后调用，只对最终会发布的条目调用，以最小化成本、避免对低质量数据调用 AI。
- 若未来 AI 参与语义去重或事件聚合，必须明确其属于**辅助能力**；核心去重（URL/标题归一）和核心评分（HotScore）不能完全依赖 AI。

---

## 五、数据源原则

**数据源必须 Adapter 化**：每个数据源为独立模块，实现统一 `BaseAdapter` 契约（`fetch` / `parse` / `normalize` / `validate` / `health`）。

**单源失败隔离**：

- 一个数据源失败，不得导致整个 Pipeline 失败。
- 必须：记录错误、记录 health 状态、跳过该源、继续处理其他源。
- 主流程「尽力而为」：任一源失败 → 跳过 → 其他源正常产出 → 该板块在前端诚实展示「数据源维护中」或「暂无数据」。

**统一配置管理（两分离原则，详见 v2 第 5 节）**：

- 静态配置：`config/sources.yaml`（人写、进仓库、版本化）——描述源的 id / name / category / type / enabled / priority / max_items / timeout / retry_count / rate_limit / legal_status / terms_url 等。
- 运行状态：`data/sources_state.json`（机器写、每次运行更新）——记录 last_success / last_error / item_count / response_time 等。
- 两者必须分离；新增或关闭数据源时尽量只改配置，不修改核心业务逻辑。

---

## 六、数据模型原则

**Trend（热点条目）**：代表一个真实的热点 / 资讯条目。

**Event（事件）**：代表一个真实事件。多个 Trend 可以关联同一个 Event。

**关系约束**：

- 一个 Event 关联多个 Trend；每个 Trend 通过 `event_id` 反向指向 Event。
- 不得删除原始 Trend（聚合不丢数据）。
- UI 可以折叠聚合展示（同事件只占 1 个卡位，展开可见全部来源），但底层必须保留来源追溯关系。

**Trend 核心字段（最小集，详见 v2 第 7 节）**：
`id` / `source_id` / `category` / `status`(draft|verified|published|rejected) / `title` / `summary` / `summary_origin`(original|ai|none) / `original_url` / `heat_raw` / `hot_score` / `score_breakdown` / `published_at` / `collected_at` / `tags` / `tags_origin` / `event_id` / `lang` / `is_mock`。

**Event 核心字段（详见 v2 第 8 节）**：
`event_id` / `title` / `summary` / `category` / `sources[]`(保留每个来源 original_url) / `source_count` / `hot_score` / `published_at` / `updated_at`。

---

## 七、历史数据原则

生产数据必须按日期保存，支持历史回看与追溯。

**保存格式**：

```
data/YYYY/MM/YYYY-MM-DD.json
```

**必须支持**：

1. 查看今天。
2. 查看昨天（`index.json` 的 `available_dates` 倒数第二天）。
3. 查看历史（遍历 `available_dates` 或按 `date_index` 定位）。
4. 按日期查询（路径规则可构造）。
5. Git 历史追溯（每日文件独立 commit）。

**禁止**：仅使用 `latest.json` 作为唯一生产数据源。以 `index.json` + 日期分片为准；`latest_date` 仅作指针。

伴随文件（详见 v2 第 4 节）：`data/index.json`（全局索引）、`data/health.json`（健康快照）、`data/sources_state.json`（运行态）。

---

## 八、数据生命周期

三态定义（详见 v2 第 3 节）：

```
Raw（原始响应） → Processed（标准化中间产物） → Published（最终发布数据）
```

**MVP 阶段不长期保存完整 Raw**：

- Raw：仅存在于 Actions 运行内存 / 临时目录，运行结束即弃。
- Processed：不提交仓库，仅 Actions 运行内临时产物。
- Published：长期保存并版本化，提交到 `data/YYYY/MM/*.json`。

**可以保存（不入生产数据增长）**：

- 脱敏 fixtures（少量真实响应样本，仅供离线单测）：`collectors/tests/fixtures/`。
- 必要的测试样本。
- 运行日志摘要（每源条数 / 丢弃数 / 错误 / 耗时，进 health.json 与 Actions 日志）。

**禁止**：把大量网页 HTML / 完整正文长期提交到 GitHub 仓库（体积膨胀 + 第三方内容版权 / 条款风险）。可追溯性由 `original_url` 保证。

---

## 九、Mock 数据规则

Mock 数据只能用于本地开发、单元测试、UI 开发。

Mock 数据必须：

- 显式标记 `is_mock = true`。
- 任何测试数据必须明确标记。

Mock 数据不得进入：

- 生产 JSON。
- 生产页面。
- 正式部署。
- GitHub Actions 生产数据流。

**CI 强制检查**：生产数据流中若存在 `is_mock = true`，CI 必须失败并阻止合并 / 发布。

---

## 十、AI 使用规则

**可配置 / 可关闭**：

- AI 默认关闭或可配置（`config ai.enabled=false` 时跳过 AI 阶段）。
- AI 一键关闭后，直接使用原始标题 / 原摘要 / 规则分类发布。

**密钥管理**：

- AI API Key 禁止写入代码。
- AI API Key 禁止提交 Git。
- 必须通过环境变量读取（如 `OPENAI_API_KEY` 或其他 provider API Key）。

**故障隔离**：

- AI 失败，不得导致整个网站失败。
- 单条 AI 失败：仅该条回退原文，不影响其他条目与整体发布。
- 必须支持「无 AI 摘要模式」：原始标题 + 来源展示。

**输出约束**：

- AI 摘要必须尽量基于原始来源，禁止凭空扩写。
- AI 输出必须可回溯到输入文本（一致性检查）；不满足则丢弃 AI 结果，回退原文。
- 必须标注加工来源：`summary_origin` / `tags_origin` 取 `original` / `ai` / `none`，保证透明可审计。

---

## 十一、Secret 安全

**禁止提交**：API Key、Token、Password、Secret、Cookie、Session、私有凭证。

**必须使用**：

- `.env`
- `.env.local`
- GitHub Actions Secrets / Vercel 环境变量

**配置要求**：

- `.gitignore` 必须正确配置，覆盖 `.env` / `.env.local` / 密钥文件。
- 必须提供 `.env.example`（不含真实 Secret），作为环境变量样例与文档。

---

## 十二、代码质量

必须：

1. TypeScript 开启严格模式（`strict: true`）。
2. Python 使用类型提示（type hints）。
3. 函数职责单一。
4. 模块职责清晰。
5. 避免重复代码（DRY，但不过度抽象）。
6. 不为了简单而把所有代码写进一个文件。
7. 不为了架构而过度工程化。
8. 优先简单、稳定、可维护。

**权衡原则**：架构复杂度必须与项目阶段匹配；MVP 阶段克制引入依赖与抽象，演进期按实际规模再升级。

---

## 十三、测试原则

所有核心逻辑必须可测试。

至少覆盖：

1. Schema 验证。
2. URL 标准化（canonical_url 生成）。
3. 去重（URL 归一 + 标题归一）。
4. HotScore 计算（各维度分量）。
5. 数据源失败（单源失败不中断整体）。
6. Pipeline 局部失败（某阶段异常时的降级）。
7. ≤20 条限制（不足不凑、超出截断）。
8. Mock 与生产隔离（`is_mock` 不进入生产）。
9. AI 失败降级（回退原文）。

**测试数据要求**：

- 优先使用离线 Fixture（脱敏真实响应样本）。
- 默认不在单元测试中调用真实外部 API。
- Fixture 不得随每日数据增长而膨胀。

---

## 十四、Git 原则

**Commit 规范**：

- 小步提交、单一目的、清晰命名。
- 建议类型前缀：`feat:` / `fix:` / `refactor:` / `test:` / `docs:` / `chore:`。
- 示例：`feat: add arxiv adapter`、`fix: normalize canonical url parser`。

**禁止**：

- 一次提交大量无关修改。
- 把密钥 / Mock 生产数据混入提交。

---

## 十五、修改代码前规则

任何修改必须按顺序执行：

1. 阅读 `PROJECT_RULES.md`（本文件）。
2. 阅读相关架构文档（v2 / PROJECT_PLAN）。
3. 明确修改范围（影响哪些模块 / 数据流 / 配置）。
4. 修改代码。
5. 运行相关测试。
6. 检查是否违反项目红线（真实性 / 合规 / ≤20 / Mock 隔离 / AI 边界）。
7. 汇报修改内容（变更了什么、为何变更、是否影响数据或部署）。

**禁止**：

- 未说明原因就重写整个项目。
- 随意删除已有功能。
- 修改核心架构而不更新文档。

---

## 十六、架构变更规则

以下变化必须先更新文档并获得确认（评审通过后才可落地）：

1. 更换核心技术栈。
2. 引入独立后端。
3. 引入数据库（如 PostgreSQL / Supabase）。
4. 改变数据存储方式。
5. 改变数据 Pipeline（顺序或阶段职责）。
6. 引入新的 AI Provider。
7. 修改核心 Schema（Trend / Event 字段）。
8. 修改生产部署架构。

**文档更新要求**：变更须同步到 v2（`ARCHITECTURE_REVIEW_v2.md`），并在 `PROJECT_RULES.md` 或对应文档记录变更原因与日期。

---

## 十七、数据源新增规则

新增数据源必须先评估（形成评估记录，再开发 Adapter）：

1. 数据来源（官方 / 半官方 / 公开页 / 第三方）。
2. 合法性（`legal_status` 归入：`official_api` / `official_rss` / `public_page` / `third_party_legal` / `manual`）。
3. API / RSS 可用性。
4. `robots.txt` 是否允许。
5. 服务条款 / API 使用条款。
6. 访问频率限制。
7. 稳定性（可用性、易变程度）。
8. 失败降级方案（自动 / 半自动 / 人工 / 暂不上线）。
9. 数据字段完整性（能否产出完整 Trend 字段）。
10. `original_url` 是否可靠（可追溯）。

**准入红线**：只有通过评估、且 `legal_status` 合法的数据源才能开发 Adapter；任何需要绕过登录 / 验证码 / 访问控制 / 破解签名 / 绕过反爬技术保护的实现，一律禁止合入。

---

## 十八、生产发布红线

生产发布前必须确认（任一项不满足不得发布）：

1. 无 Mock 数据（`is_mock` 全为 false）。
2. 无虚假数据。
3. 所有条目有 `original_url`。
4. 每个板块 ≤20 条，且不足不凑数。
5. 数据源失败不会导致页面崩溃（降级展示正常）。
6. API Key 未提交（密钥检查通过）。
7. 测试通过。
8. GitHub Actions 成功。
9. `health.json` 正常生成、状态可解释。
10. 数据可以追溯（git 历史 / original_url）。

**全局验收红线（任何阶段不可违反）**：零虚构 · 每条可追溯 `original_url` · 每板块 ≤20 且不凑数 · 采集全程合法合规（不绕过任何技术保护）· Mock 不进生产 · AI 只加工不创作事实。

---

## 十九、核心原则优先级

当不同要求发生冲突时，按以下优先级裁决（高优先级压倒低优先级）：

```
真实性
  > 合法合规
    > 数据可追溯
      > 安全
        > 稳定性
          > 可维护性
            > 用户体验
              > 功能数量
```

**最高准则**：宁可少展示真实数据，也不能展示虚假数据。

---

## 二十、当前项目状态

- **当前阶段**：阶段 0 — 地基建设
- **状态**：规划完成、架构审查（v2）完成、尚未开始正式编码
- **当前权威架构文档**：`docs/ARCHITECTURE_REVIEW_v2.md`
- **项目规划**：`docs/PROJECT_PLAN.md`（v1.1，冲突以 v2 为准）
- **项目规则**：`PROJECT_RULES.md`（本文件，最高优先级开发规范）

**阶段 0 范围说明（本轮仅做规则固化）**：

- 本轮仅创建 `PROJECT_RULES.md`，固化最高级开发规范。
- 本轮不创建代码、不创建 Schema、不创建接口、不初始化项目、不安装依赖、不创建 Mock、不连接 API、不创建 GitHub Actions、不修改其他项目文件。
- 下一步（待指令）方可进入阶段 0 的工程骨架工作（目录 / License / README 骨架 / CI 空跑 / Schema 与 Repository 接口定义）。

---

_本文件为项目最高级开发规范，任何开发行为均须首先遵守。_
