# Spec 生命周期管理

本文件是 SKILL.md「Spec 生命周期管理」的展开。spec-guide 原本只覆盖"写—审—改"，缺少 spec 走到生命周期末段的处理。本文件补齐：状态机、定稿历史化、退役归档、复审触发。

> 字段口径声明：本文讲状态转移的**语义与时机**；frontmatter 字段拼写、取值与条件配套以 `frontmatter.md` 为唯一源。

适用范围：仅 **spec-anchored** 与 **spec-as-source** 层级的 spec（见 `persistence-models.md`）。spec-first 层级用完即弃，不进入状态机。

## 一、Spec 状态机

每份 spec 首部声明当前状态。状态流转是单向的，不可随意回退；回退（如从 Deprecated 回到 Active）本身就是一次显式变更，走场景 C。

| 状态 | 含义 | 何时进入 |
|------|------|----------|
| **Active** | 当前在用，是主口径 | spec 编写完成并通过场景 B 审查 |
| **Superseded** | 已被新 spec 取代，不再是主口径 | 新 spec 走定稿历史化流程取代本 spec |
| **Deprecated** | 废弃但保留，读者应迁移到替代口径 | spec 不再用，但暂不归档（如需过渡期、引用未清理完） |
| **Archived** | 归档为历史，仅作系统意图入口 | Deprecated spec 的引用清理完成，移入归档目录 |

### 合法转移

```
Active ──(定稿历史化：大改新开)──→ Superseded ──(引用清理完)──→ Archived
Active ──(不再用，需过渡)──→ Deprecated ──(引用清理完)──→ Archived
```

不合法：Archived → Active（归档后复活应新开 spec，不复活旧文档，见下文「复活」）。

## 二、定稿历史化纪律

### 核心原则

**定稿即历史文档，大改开新 spec，小改走变更记录。**

借鉴 PEP/Rust RFC 的纪律：一份 spec 一旦定稿（进入 Active），它的核心决策就固定了。后续若发生**不可逆决策翻转或主口径变更**，不应无限改写这份活文档，而应新开一份 spec 取代它，形成演进链。这样读者能从演进链理解"为什么从 A 变成 B"，而不是面对一份被反复打补丁、看不出原初意图的文档。

### 大改 vs 小改判定

| 维度 | 小改（走场景 C 变更记录） | 大改（定稿历史化，新开 spec） |
|------|--------------------------|-------------------------------|
| 决策性质 | 澄清、补边界、修笔误、补遗漏的极端场景 | 不可逆决策翻转、主口径变更 |
| 影响面 | 单节或少数节，不触及核心契约/状态所有权 | 多节联动，核心契约/状态机/主实体重构 |
| 修订次数 | 同一节零星修订 | 同一节 3 次以上补丁式修订（信号：该上浮为骨架级重构） |
| 读者理解 | 改完读者还能理解原意图 | 改完原意图已被颠覆，读者会困惑 |

**判定信号**：当一份 spec 同一节出现 3 次以上补丁式修订，或修订开始触及核心契约与状态所有权，判定为大改，触发定稿历史化。

### 定稿历史化流程（大改）

1. **新建 successor spec**，走场景 A 完整流程编写。
2. **旧 spec 标状态转移**：
   - 旧 spec frontmatter 标 `status: Superseded` + `superseded-by: <新 spec 相对路径>`。
   - 新 spec frontmatter 标 `supersedes: <旧 spec 相对路径>`，并写一节「与前任 spec 的关键差异」说明翻转了什么决策、为什么。
3. **引用清理**：全仓库搜索引用旧 spec 的地方（其他 spec、AGENTS.md、agent-map.yaml、文档），逐个判断是改指向新 spec 还是已失效；agent-map.yaml 的 pointers 同步登记旧 spec（relation: superseded）。
4. **清理完成后**，旧 spec 可转入 Archived（见下文）。

### 小改流程

走场景 C 完整流程，在 spec 变更记录表追加一行。不标 Superseded，不动首部状态。

## 三、退役与归档

### Deprecated（废弃但保留）

spec 不再是主口径，但因过渡期或引用未清完暂不归档时用此状态。

操作：
1. spec frontmatter 状态改 `Deprecated`，加 `deprecated-on: <YYYY-MM-DD>`；有替代口径时加 `replaced-by: <替代口径相对路径>`（spec、ADR 或 AGENTS.md 条目）。
2. 在 spec 顶部加醒目废弃提示块：
   ```markdown
   > ⚠️ 本 spec 已于 YYYY-MM-DD 废弃。当前主口径见 <替代口径>。
   > 保留仅为过渡参考，请勿据此实现。
   ```
3. **清理引用责任**：在上方废弃提示块中注明谁负责清理对本 spec 的引用（其他 spec 的交叉引用、代码注释、agent-map.yaml 导航）——责任方是正文内容，不进 frontmatter。清理未完成前不归档；agent-map.yaml 的 pointers 同步登记本 spec（relation: deprecated）。

### Archived（归档）

引用清理完成后，spec 移入归档目录，保留为系统意图入口（过期文档仍有价值——它记录了系统当初为什么这么设计）。

操作：
1. 移动文件：`docs/spec/<name>.md` → `docs/spec/archive/<name>.md`。
2. frontmatter 状态改 `Archived`，加 `archived-on: <YYYY-MM-DD>`。
3. 归档目录的 spec 不再维护，不接受场景 C 变更；如需恢复口径，新开 spec（见「复活」）。
4. 在 `agent-map.yaml` 的 pointers 登记其归档状态（relation: archived），避免读者误用。

**归档目录约定**：`docs/spec/archive/`。归档 spec 保留原始内容不删改，只加归档标记。

## 四、复活

归档或被取代的 spec，若其口径需要重新生效，**不复活旧文档**，而是：

1. 新开一份 spec（可命名 `<name>-revival.md` 或新名称）。
2. 新 spec frontmatter `supersedes:` 列出被复活的归档 spec。
3. 走场景 A 完整流程——因为旧 spec 当初被废弃/取代有原因，复活时必须重新审视这些原因是否仍成立。

理由：直接复活旧文档会让读者忽略"它为什么曾被废弃"，新开 spec 强制重新论证。

## 五、复审触发

spec-anchored / spec-as-source 层级的 spec，首部必须声明复审条件。命中任一条件即走场景 B 审查，审查结论可能是"维持""小改""触发定稿历史化"或"退役"。

### 复审条件写法（写入 spec 首部 `review-trigger`）

frontmatter 禁嵌套，`review-trigger` 是单行自由文本，多条件用分号分隔：

```
review-trigger: 关联 OpenAPI/AsyncAPI 契约破坏性变更；上下游系统接口语义变更；核心组件换型或下线；主数据模型重构；每 6 个月定期复审；同一节累计 3 次补丁式修订
```

条件分四类，按适用组合：

- **契约联动型**：关联的 OpenAPI/AsyncAPI 契约发生破坏性变更；上下游系统接口语义变更
- **架构联动型**：依赖的核心组件换型或下线；主数据模型重构
- **时效型**：每 6 个月定期复审（高关键性 spec） / 每 12 个月（一般 spec）
- **信号型**：同一节累计 3 次以上补丁式修订（触发定稿历史化判定）

### 复审的产出

复审不是走过场，必须给出明确结论之一：
- **维持**：spec 仍准确，更新 frontmatter `last-reviewed` 为本次复审日期。
- **小改**：走场景 C。
- **定稿历史化**：走大改流程新开 spec。
- **退役**：走 Deprecated → Archived。

无结论的复审等于没复审。

## 六、常见误用

- **无限改写活文档**：把所有变更都当小改塞进同一份 spec，导致 150KB+ 单文件、原初意图被层层补丁淹没。信号：同一节 3 次以上补丁 → 该走定稿历史化。
- **废弃不标状态**：spec 不用了直接删或放着不管，读者不知它已失效。必须标 Deprecated 并加废弃提示块。
- **归档即删除**：归档不是删，是移入 archive 目录保留为意图入口。系统设计的历史决策对未来仍有参考价值。
- **直接复活旧文档**：跳过重新论证直接改 Archived spec 状态回 Active，丢失了"当初为什么废弃"的审视。
- **复审无结论**：开了复审但不给维持/改/退役的明确判定，复审流于形式。
