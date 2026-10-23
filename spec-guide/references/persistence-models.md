# Spec 持久化层级与变更模型

本文件是 SKILL.md「持久化层级与变更模型」的展开。每份 spec 在进入 A/B/C 场景前，必须先明确它处于哪个生命周期层级、采用哪种变更模型——两者的组合决定了后续保鲜纪律的轻重。

## 一、为什么必须先选

同一份 spec，"用完即弃"和"作为长期契约"的维护成本差一个数量级。不显式选择会导致两种失败：

- **过维护**：把一次性脚手架当长期契约保鲜，每次实现改动都回写，拖慢迭代。
- **欠维护**：把长期契约当脚手架对待，实现跑在前面不回写，spec 腐化为死文档。

前置选择的本质是：**先承认 spec 的寿命，再决定投入多少保鲜成本**。

## 二、生命周期层级（三选一）

按 spec 在项目中的寿命与角色分三层。层级一经选定，写进 spec 首部元信息，不轻易变更；若变更（如从 spec-first 升级到 spec-anchored），本身就是一次场景 C 变更。

| 层级 | 寿命 | 定位 | 典型产物 |
|------|------|------|----------|
| **spec-first** | 单次任务内 | 写 spec 是为了想清楚，任务完成即弃 | 起草稿、设计草图、单次实现前的对齐文档 |
| **spec-anchored** | 长期 | spec 是实现完成后的长期锚点，与代码同步演进 | 系统设计文档、模块 spec、接口契约、术语表 |
| **spec-as-source** | 永久 | spec 是唯一人工编辑源，代码由 spec 派生生成 | 生成代码带 `// GENERATED FROM spec` 标记的场景 |

### 各层保鲜纪律

**spec-first**
- 不强制长期保鲜。任务完成后可归档或删除。
- 不要求场景 C 全流程；实现中偏差可在 spec 上直接划改，不必走变更记录。
- 不进入 `docs/spec/` 主目录；放草稿区或任务工作区。
- ⚠️ 若实现过程中发现决策实际不可逆（架构骨架、核心契约），立即升级为 spec-anchored 并补走场景 A 收口，禁止"用完即弃"丢弃不可逆决策。

**spec-anchored**（默认推荐层，多数 spec 落此）
- 必须长期保鲜。实现与原型验收中的架构决策、契约变更、边界裁定必须回写（SKILL.md「spec 的身份与纪律」）。
- 实现完成后必须回验（场景 C 触发 + 一致性校验脚本）。
- 走完整场景 C 流程（含变更记录）。
- 进入 `docs/spec/` 主目录，纳入生命周期状态机管理。

**spec-as-source**
- spec 是唯一编辑源。改代码前先改 spec，再重生代码；直接改生成代码视为违规。
- 要求最强的双向一致性：每次 spec 变更后，生成代码必须重新编译，diff 必须可审查。
- 验收标准与测试用例应能从 spec 自动派生或强追溯。

## 三、变更模型（三选一）

选定生命周期层级后，再选 spec 与下游产物（plan / tasks / 代码 / 测试）之间的变更流向。三模型互斥，必选其一。

| 模型 | 流向 | 适用 | 风险 |
|------|------|------|------|
| **Flow-Back（回流式）** | spec / 产物可互相启发改动，改完手工对齐 | 早期探索、方向未定 | 静默分歧——改了下游没回写 spec，后人不知信谁 |
| **Flow-Forward（前推式/不可变）** | 每个 spec 目录是历史记录，需求变更时新建目录而非改旧的 | 审计严格、需完整追溯 | 重复与碎片化，需命名/链接/评审维持谱系 |
| **Living Spec（活规格）** | spec 是契约，产物是派生物，先改 spec 再重生 | spec-anchored / spec-as-source 的默认 | 派生物被丢弃时丢失实现 rationale |

### 选择决策树

1. spec 寿命是单次任务？→ **spec-first**，变更模型无所谓（用完即弃）。
2. spec 是长期锚点？
   - 需要审计级追溯（每版可回放）？→ **spec-anchored + Flow-Forward**
   - 默认？→ **spec-anchored + Living Spec**
3. spec 是唯一编辑源、代码由它生成？→ **spec-as-source + Living Spec**（强制）

### 各模型纪律

**Flow-Back**
- 每次下游改动后，必须显式检查是否需要回写 spec（场景 C C1 的"实现发现"来源）。
- 风险缓解：约定"任何实现偏差超过 N 处或触及契约层，必须当轮回写，不留到下一轮"。

**Flow-Forward**
- spec 目录带版本或日期（`bill-prediction-v1/`、`bill-prediction-2026-07/`），新需求开新目录。
- 旧目录标 `superseded-by:`（frontmatter），新目录标 `supersedes:`，形成演进链。
- 禁止修改已合入的旧目录内容（除状态标记与链接）。

**Living Spec**（最常见）
- spec 文件是单一编辑点。产物（plan/tasks）从 spec 派生，spec 变更后产物重新生成或同步。
- 变更走场景 C 完整流程，变更记录表是追溯手段。
- 纪律：派生物（plan/tasks/草稿）不得反向覆盖 spec；若派生物中产生了不可逆决策，必须回写 spec 后再继续。

## 四、spec 首部「持久化策略」字段写法

选定层级与模型后，写进 spec 首部 frontmatter（扁平键值；完整字段口径以 `frontmatter.md` 为唯一源）：

```markdown
---
type: spec
status: Active
layer: spec-anchored        # spec-first | spec-anchored | spec-as-source
change-model: living-spec   # flow-back | flow-forward | living-spec
review-trigger: 关联契约 OpenAPI 大改；上游结算系统换型；每 6 个月定期复审
---
```

行内注释（`#` 起）lint 会忽略。条件字段的配套规则（定稿历史化加 `supersedes`、被取代配 `superseded-by`、废弃配 `deprecated-on` 等）见 `frontmatter.md` 与 `lifecycle.md`。

若 spec 工具链不支持 frontmatter，等价信息写在首节「持久化策略」列表里——但该写法 lint 无法校验，仅作过渡。

## 五、常见误用

- **把 spec-first 当 spec-anchored 维护**：对一次性草稿强行走变更记录、回验脚本，过度仪式化。判断信号：这份 spec 一个月后还有人读吗？没有 → spec-first。
- **把 spec-anchored 当 spec-first 维护**：长期契约却不回写、不回验，任其腐化。判断信号：实现已经和 spec 对不上了吗？对不上 → 要么补走场景 C，要么承认这份 spec 该退役。
- **Flow-Back 不设回写纪律**：选了 Flow-Back 却不约定"何时必须回写"，最终演化成静默分歧。Flow-Back 不是"不回写"，是"显式约定回写时机"。
- **层级不声明**：不写首部持久化策略，后续维护者只能猜，猜错就过维护或欠维护。
