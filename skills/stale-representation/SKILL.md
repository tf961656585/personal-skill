---
name: stale-representation
description: |
  变更继承面协议：找出改动会让哪些「第二事实源」变成假话，并逐项处置——文档、代码注释、prompt/skill、配置示例、错误消息、测试名、mock/seed、索引/map、缓存/看板、硬编码外部假设等。
  当改动会改变行为、默认值、命名、契约、降级路径、入口、数据形状或对外部世界的假设时使用；方案阶段列出清单，执行中随改随清，交付前逐项核验。纯格式/措辞改动不触发。
  不适用：spec 文本内部变更（走 spec-guide 场景 C）；测试旧行为固化（走 test-linkage）；UI 文案可懂性（走 ui-copy-check）；memory 条目失效（走 reflect）；跨任务存量巡检（走 repo-hygiene）。
---

# 失效表示（stale-representation）

## 定位

对应 AGENTS.md 基本判断链「归属与继承面」。要解决的共同根因只有一句：**同一事实存在第二处表示，而它与主事实源之间没有机械联动**。主事实一变，第二处不会跟着变；它过期时，也没有消费方报错。

本 skill 只做三件事：判触发、产出继承面清单、按清单核验。spec 质量、测试取舍、文案风格、记忆格式各有 owner，不在本 skill 重复。

## 首条规则：先判触发

**触发**（任一成立）：行为、默认值 / 常量 / 阈值、命名 / 术语、契约 / 字段 / 错误码、降级路径 / 分支 / flag、入口 / 文件 / 路由、数据形状、第三方依赖、UI 行为 / 流程、外部规则 / 容量 / 时区 / 法规。

**不触发**：纯格式、纯措辞、纯内部重构且无对外表示、只改生成物而生成器未变。

- 未触发：输出一行 `继承面：未触发（判据：…）`，结束。不要在纯格式任务上制造清单。
- 触发但扫描后 0 命中：输出 `继承面：触发，扫描后 0 命中（探针：…）`，不能静默。
- 判不准是否触发时按触发处理，但只跑到矩阵给出的探针为止，不扩大为全仓库搜索。

## 记录格式（五槽）

```text
继承面（C1 默认超时 30s→10s；C2 删除 legacy fallback）
S1 | copy    | src/client.ts:42 "默认 30s"            | edit→done   | G: grep 30s → 3/3 已改
S2 | copy    | README.md:88 "timeout=30"              | edit→done   | G: grep 30s → 已改 10
S3 | promise | docs/runbook.md#回退 "打开 flag_legacy" | delete→done | C: grep flag_legacy → 0
```

| 槽 | 取值 |
|---|---|
| `form` | `copy` / `derive` / `promise` / `assume` / `standin` / `pointer` / `memory` |
| `location` | `path:line` / `path#anchor` / `symbol` / `config-key` |
| `claim` | 旧值或旧说法的原文，必须可核对 |
| `action` | `edit` / `delete` / `regen` / `verify` / `delegate` / `na` |
| `state` | `open` / `done` / `delegated` / `na` |
| `evidence` | `<探针前缀>: <结果>`；`done` 必有结果，`na` 必有探针，`delegate` 必有 owner 与交接物 |

硬规则：

- ID 稳定，不重排；同 `location + claim` 合并，不重复列。
- 不设 severity / priority / confidence——开放项本身阻断，优先级不在这里争。
- 清单只活在对话里。禁止落盘成仓库文件、spec 附录或 README 新节——那是在制造它要防的过程产物。
- 单个变更（`C1`/`C2`…）≤ 8 条；整份清单按变更分组，不合并成无限表。单个变更超出、同一表示反复出现、或修一条要动五个以上文件 → 判定变更范围或架构有问题，转 problem-triage。治理机制自身的建设不受此限，但要在返回里标明。转 problem-triage 时，未处置的文档同步项不得静默丢弃：保持 `open` 并写明交接 owner（spec-guide 场景 C 或用户裁决），在交付返回中单列。
- 语义探针必须同时引用原文和变化后的行为 / 值；只写「看过了没问题」视为未验证。

## 发现矩阵

从 diff / 方案里读变更信号，只读命中的行，不逐行执行。

| 变更信号 | 会失效的表示 | form | 探针 |
|---|---|---|---|
| 默认值 / 常量 / 阈值改了 | 注释、README 配置表、示例配置、文档数值 | copy | `G` grep 旧值 |
| 函数签名 / 参数 / 返回改了 | docstring、调用示例、类型声明、SDK 文档 | copy | `G` grep 旧符号 + `S` |
| 概念 / 术语改名 | 术语表、注释、UI 文案、i18n、agent-map | copy / pointer | `G` grep 旧词及同义词 |
| 契约 / 字段 / 错误码改了 | OpenAPI、schema、数据字典、错误码表、mock | copy / standin | `S` 契约比对 |
| 删分支 / flag / 降级路径 | runbook、回退说明、flag 文档、告警处置 | promise | `C` grep 名称 + 确认路径不存在 |
| 删文件 / 入口 / 路由 | 链接、`§` 引用、注册表、导航 map | pointer | `R` 引用完整性 |
| 换 / 升级第三方依赖 | mock、stub、adapter、假设注释、示例 | standin | `C` 契约测试 / replay |
| 数据形状 / schema 改了 | seed、fixture、迁移说明、报表、看板、缓存 | derive | `B` 重建 + `S` |
| UI 行为 / 流程改了 | 截图、帮助文案、空态、错误提示、演示数据 | copy | `E` 语义比对 |
| 外部规则 / 容量 / 法规 / 时区 | 硬编码注释、运维文档、告警阈值 | assume | `X` 来源 + 到期日 + 探针 |
| 工具能力 / 注册名 / skill 描述改了 | AGENTS、skill frontmatter、tool schema、memory 钩子 | copy / promise / pointer | `C` 触发干跑 + `R` |
| 改动落在某模块 / 文件（含内部重构、职责调整） | 该模块的设计文档章节（职责 / 边界 / 流程描述）、理由型与警告型注释 | copy | `E` 重读原文 + 引用变化后的行为 |

矩阵里出现两个形态时，按不同表示拆成两条 record，不合并成一个含糊条目。最后一行按改动区域有界执行：只重读改动文件 / 模块邻近的设计文档章节与注释，不扩为全仓库搜索；它是唯一覆盖「没有旧字面值可 grep」的语义型失真的入口，核不了就标 `open`，不猜。

## 四阶段

**发现**：输入是变更集，不是仓库。从 diff / 方案里抽出旧值、旧符号、被删的 flag 或路径、改名术语，匹配矩阵生成候选探针。变更集同时给出改动落在哪些文件与模块，据此定位该区域邻近的设计文档章节与注释（有界重读，见矩阵最后一行）。输出候选清单。禁止全仓库开放式搜索，禁止先分类再找证据。

**搜集**：批量跑探针，抓命中。逐个判断是「当前口径」「历史注记」还是「生成物」；历史注记和生成物不算腐化。输出带定位与原文的 record，状态 `open`。语义型判断拿不准时保持 `open` 并留证据，不猜。

**记录**：一份规范清单，追加或原地更新，ID 稳定。多个变更用 `C1/C2` 分组，整份只写一次变更集。不新建文件。

**返回**：按场景给视图，不重复倾倒全量清单。

```text
# 规划
继承面（C1 …；C2 …）
S1 | … | edit→open | G: grep …

# 执行（只报增量）
S1 done | S3 open

# 交付
继承面：3 条（C1×2, C2×1）→ done 3 / delegated 0 / open 0 / na 0

# 未触发
继承面：未触发（判据：纯措辞改写）
```

## 探针类型

| 前缀 | 探针 | 用于 |
|---|---|---|
| `G` | grep 旧符号 / 旧值 / 旧词 / 旧路径 | 字面拷贝：注释、配置示例、错误消息、i18n、测试名 |
| `S` | schema / 类型 / 契约校验 | 结构契约：OpenAPI、JSON Schema、tool schema、类型声明、fixture |
| `R` | 链接 / `§` / 注册表 / import / tool name 完整性 + 目标语义 | 指针：导航、索引、map、路由、入口 |
| `B` | 重建后 diff | 派生：codegen、快照、lockfile、缓存、索引、看板 |
| `C` | 契约测试 / 样本调用 / 触发干跑 / 路径存在性 | 替身与承诺：mock、stub、测试、flag、deprecated、回退说明、prompt/skill/tool 描述 |
| `E` | 重读源、核对证据、检查到期与钩子 | 记忆：AGENTS、skill、prompt、memory、理由型注释、会话摘要 |
| `X` | 来源 + 到期日 + 外部探针 | 外部假设：阈值、时区、法规、第三方语义、证书 |

代码注释不是一种面，至少分五类：字面值（`G`）、理由型（`E`）、导航型（`R`）、警告型（`E`/`C`）、TODO / 归属（`C`/`R`）。理由型注释 grep 不到，不能假装机械检查覆盖了它。

模型可读面（AGENTS、skill、tool description、memory、会话摘要、RAG）腐化后不会有人类兜底，必须用行为探针：触发干跑、样本调用、证据回源，不能只做文本比对。

## 载体目录

具体载体清单在 `references/surfaces.md`，按需查。核心纪律只有一条：**任何新出现的模型可读面，都必须登记「载体 + 联动 + 探针 + 消费者」；登记不了就标 `unknown` 并在返回里列为盲区，不默认安全。** 种类增长放在目录里，不放进五槽记录。

## 边界

- spec 文本内部变更 → spec-guide 场景 C；本 skill 只处理 spec 变更对外部表示的波及。
- 测试旧行为固化 → test-linkage。
- UI 文案可懂性 → ui-copy-check；本 skill 只管「是否还真实」。
- memory 条目失效 → reflect；本 skill 的 `memory` 形态指 AGENTS / skill / prompt / 会话摘要等指令型表示。
- 多份设计产物对照 → design-review。
- 跨任务存量巡检 → repo-hygiene。
- 任务级临时文件、调试产物 → sweep。
- 视觉验收 → visual-handoff。

`delegate` 必须指名 owner 和交接物，不能只写「交给别的 skill」。涉及代码、spec、测试的删除或改写，按各自 owner 的规则执行；本 skill 负责点名和核验。

## Do NOT

- 把发现矩阵当全量 checklist 跑——它是查表，不是待办。
- 写「可能有过时文档」而不给定位与原文。
- 无证据标 `done`，无探针标 `na`。
- 把清单写进仓库文档或 spec 附录。
- 重复 test-linkage / spec-guide / ui-copy-check / reflect 的活。
- 用 confidence / priority 字段逃避判断。
- 对历史注记、生成物、已正确的副本误报。
- 在纯格式任务上制造继承面。
- 把「看过了没问题」当语义探针证据。

## 快速参考

- 先 Gate，后矩阵；未触发只写一行。
- 五槽记录，ID 稳定，不落盘。
- 单个变更八条封顶；治理机制建设可超出但需标明。
- 改动区域邻近的设计文档与理由型注释，按 `E` 有界重读。
- 探针前缀 `G/S/R/B/C/E/X`。
- 能委派就委派，不重做 owner 的活。
- 语义判断必须同时有原文和变化后的值 / 行为。
