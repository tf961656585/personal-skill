# 测试↔spec 关联规则明细（linkage-spec）

本文件是 test-linkage skill 的规则唯一明细源。ID 与标注的**格式约定**不在本文件重复定义——以 spec-guide `references/consistency-checks.md` 为唯一规范源，本文件只消费其格式并定义全仓治理规则。

适用范围：已建立验收 ID 体系的项目。未建立的项目先走场景 A（见 SKILL.md）。

## §1 ID 契约（spec 侧）

- 格式：`<域缩写>-<序号>`，定义于 Active spec/contract 的 `#### 验收：<ID>` 标题（或行内 EARS 形态，同 consistency-checks.md §二）。
- 生命周期：ID 随产物 frontmatter `status`。产物迁入终态（Superseded / Deprecated / Archived 及项目自定义终态词表）时，其全部 ID 退出有效集合。
- **显式废弃形态**：语义翻转/裁断废弃的验收项，用 `#### 废弃：<ID> <说明>` 标题保留原文（比删除+编号空洞更可追溯——废弃原因与日期留在正文）。废弃 ID 不属于有效集合；测试标注命中它时点名「已废弃」。
- 编号稳定性（禁复用旧号、行为变更沿用原 ID）的完整纪律见 consistency-checks.md §二，本体系完全继承：**ID 一旦分配与那一条行为描述绑定**。语义级变更若换 ID，改号后 grep 全仓残留引用。

## §2 测试标注 schema（测试侧）

- 格式：`@spec: <ID>[, <ID>]`，独占一行注释（`// @spec: AG-CT-010`）。
- 位置不限：文件头（声明整文件保护面）或用例上方（细粒度）均可，校验器不区分位置。
- 书写陷阱（consistency-checks.md §三实测）：标注行只写 ID 列表，夹带英文散文词会被误解析成多余 ID；标题字符串里的 ID 不构成标注；多 ID 只用逗号分隔。

## §3 规则明细

分档说明：**error** = 阻断（进硬门禁时 exit 1）；**warning** = advisory 输出清单不阻断。升硬条件统一为「红过至少一次真问题、存量清零、处置纪律已立」。

### R1 引用闭包（error）

判据：测试 `@spec` 标注的每个 ID 必须属于某份 **Active** spec/contract 的验收 ID 集合。

违规分三类报告（文案必须区分，处置动作不同）：

| 类别 | 含义 | 裁定动作 |
|---|---|---|
| ID 属于终态 spec | 引用随 spec 退役失效——**旧行为测试的机械信号** | 删测试 / 改测新口径（查取代 spec 的新 ID） |
| ID 已显式废弃 | spec 用 `废弃：` 标题保留的 ID——**语义翻转的机械信号** | 按新口径改写断言 + 改标新 ID / 删测试 |
| ID 全仓不存在 | 拼写错误或验收项从未存在 | 修标注 / 补 spec 验收项（走 spec-guide 场景 C） |

### R2 ID 全局唯一（error + advisory）

- error：同一 ID 在两份 **Active** 产物中定义为验收项。
- advisory：终态产物中的 ID 与 Active 产物 ID 重号——编号复用嫌疑，提示核对是否违反编号稳定性纪律。

### R3 退役点名（流程钩子，非独立代码规则）

R1 的红灯清单就是退役点名清单：spec status 迁终态或验收项标废弃后，第一次校验的 R1 输出即「受波及测试清单」。变更批次的处置流程见 SKILL.md 场景 B。可选增强：解析变更记录表「影响范围」列中的 ID 引用，在语义变更（非终态跃迁）时也输出点名清单——依赖变更记录填写纪律，作为流程要求执行，不做机械判据。

### R4 运行入口覆盖（warning，可升硬）

判据：每个测试文件必须匹配配置 `entryGlobs` 中至少一个 glob（运行入口：vitest include、node --test 参数、CI job 清单等）。不匹配 = 孤儿测试文件（从不被批量执行）。

配置纪律：**运行入口变更（改 include、改 test glob、加新 runner）必须同步 entryGlobs**，否则 R4 基准失真。建议在入口配置文件的测试断言中锁这条同步。

裁定：纳入某入口 / 删除（已死测试）/ 改名为非测试文件（helper）。

### R5 skip 审计（warning）

判据：`describe.skip` / `it.skip` / `test.skip` / `*.todo` / `*.fails` 命中清单。沉睡测试（断言旧口径的长期 skip）是最隐蔽的过时形态——skip 本身合法（平台差异、待修 flaky），但每一条须能回答「为什么还睡着」。

### R6 覆盖读数（warning）

输出三项计数：Active 验收 ID 总数 / 有测试标注数 / 无标注测试文件数。**不设阈值**（consistency-checks.md §七：代理读数不是状态机，为数字造假标注比无读数更糟）。

### R7 测试命名规范（warning，规范已定义、实现可选）

判据：测试文件名后缀必须命中配置 `testSuffixes` 白名单（如 `.test.ts/.tsx/.mts/.mjs`）；语义组合后缀（`engineSeam`、`integration` 等）登记进 `semanticSuffixes` 白名单后放行，封杀未登记的自由组合。防止 161 种命名组合持续增殖。

### R8 头部说明（warning，规范已定义、实现可选）

判据：带 `@spec` 标注的测试文件须含一段「本测试保护什么」头部说明（块注释形式）。目的：让关联可读——ID 指向 spec，头部说明回答「这个文件里哪些断言在保护它」。

### R10 接缝保真底线（可配，默认 warning；红过真问题升硬）

背景：接缝测试的三连事故教训——测试桩（模块级 mock）会把接缝测试自己架空，三层全绿而主链断。机械可判的底线：

判据：文件名匹配 `seamPattern`（默认含 `seam` 不分大小写）的测试文件内，出现模块级 mock 调用（`vi.mock(` / `vi.doMock(` / `jest.mock(`），且同行或邻近无豁免标记 `seamExemptMarker`（默认 `guard-seam-mock-exempt`，须附原因与消除条件）→ 违规。

**豁免的合法形态**（逐个裁定后登记，不是批量放行）：

- 外部边界替身：mock HTTP facade / 宿主 API，被测链路两端真实（接缝范式「真实引擎 + 真实适配器 + 假 HTTP 上游」的实现形态之一）。
- 副作用隔离：mock 第三方 UI 库（toast 等）或非被测语义的旁路依赖，被测主链语义不受影响。
- 不可豁免：mock 被测链路内部模块（被测引擎、被测适配器、被测 store）——这不是豁免，是测试写错了。

语义边界（合法替身 vs 链路桩）机械不可完美判定，因此：红线由豁免标记承载人工裁定，标记本身可审计（grep 即全量清单）。

## §4 配置 schema

校验器接受 `--config <json>`（缺省用保守默认）。仓库侧自持守卫以 policy JSON 承载同构配置。

```json
{
  "docs": {
    "dirs": ["docs"],
    "excludeDirNames": ["archive", "temp"],
    "specTypes": ["spec", "contract"],
    "activeStatuses": ["Active"],
    "terminalStatuses": ["Superseded", "Deprecated", "Archived"]
  },
  "tests": {
    "suffixes": [".test.ts", ".test.tsx", ".test.mts", ".test.mjs", ".spec.ts", ".spec.tsx"],
    "excludeGlobs": ["**/node_modules/**", "**/dist/**", "**/dist-static/**", "**/.publish/**", "**/coverage/**"]
  },
  "entryGlobs": [],
  "seam": {
    "fileNamePattern": "seam",
    "detect": ["vi.mock(", "vi.doMock(", "jest.mock("],
    "exemptMarker": "guard-seam-mock-exempt",
    "level": "warning"
  },
  "annotationTag": "@spec:"
}
```

要点：

- `docs.dirs` 与 `excludeDirNames`：归档/临时目录整目录排除（归档 spec 不构成有效集，但扫描时仍计入全量 ID 映射用于 R2 advisory）。
- `activeStatuses` / `terminalStatuses` 按项目词表配置（spec-guide 词表为英文四态；design-doc 中文词表产物不承载验收 ID 体系，`specTypes` 不含即自动排除）。
- `entryGlobs` 为空时 R4 跳过并明示「未配置入口清单」。
- frontmatter 解析取首个 `---` 块内的 `type:` / `status:` 行（行级解析，不引 YAML 库——字段是扁平标量，足够）。

## §5 退役批次流程钩子（项目规范落点）

写进项目门禁口径文档的固定条款（措辞按项目裁剪）：

1. spec 变更记录表新增「退役/删除/废弃/语义翻转」类条目且波及验收 ID 时，同批必须跑关联守卫，R1 清单逐项处置（删测试 / 改测新口径 / 豁免登记）。
2. 运行入口变更必须同步 entryGlobs。
3. seam 文件新增模块级 mock 必须附豁免标记与原因，或重构掉。
4. 处置完成以守卫转绿为准，处置方式写进变更记录表影响范围列。

## §6 双实现对齐要求

skill 的 `check_test_linkage.py` 是跨项目参考实现；项目可按自身门禁惯例自持实现（如 Node 项目 mjs 守卫）。对齐要求：

- 规则语义以本文件为唯一事实源，两实现不得各自扩表。
- ID/标注正则与 spec-guide `trace_acceptance.py` 保持兼容（同一 token 语法），避免同一标注在两个工具下判定不一致。
- 实现差异（语言、配置载体、输出格式）不影响判据；新增规则先改本文件再动实现。

## §7 边界（本体系不做的事）

- 不做语义校验：标注对得上 ≠ 断言测对了（人工抽查归 spec-guide 回验）。
- 不做「缺失测试」阻断：验收项无测试标注是常态态，强制会让门禁红海化；该判定留在单 spec 回验场景。
- 不做覆盖率阈值、不进任何状态机。
- 不以 git 历史作为关联的长期记忆（历史塌缩/重写后失效；关联的可追溯性由 ID 体系自身承载）。
- 不自动改 spec 或测试：校验器只发现与点名，裁定与修改走 spec-guide 场景 C 与人工确认。
