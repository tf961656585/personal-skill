# 设计层产物 Frontmatter 规范（机器可读头部）

本文件是 SKILL.md「前置分流与产物类型」与「Spec 生命周期管理」的字段级展开：把"分流结果写进首部""状态写在首部"落实为**确定的字段清单**，使 spec 系产物的头部可被 `scripts/design_lint.py` 机械校验。SKILL.md 只说"写进首部"，本文件定义"首部里到底有哪些键、取什么值、什么条件下必填"。

## 总则

- **本文件是全部设计层产物字段口径的唯一源**。`lifecycle.md`、`persistence-models.md`、`templates.md` 中的字段示例必须与本文件对齐（有测试执法）；冲突以本文件为准。
- frontmatter 必须是文件**开头**的 YAML 块（`---` 起止），只允许**扁平键值**（`key: value`），禁止嵌套结构——扁平是硬约束，保证无依赖解析。
- 行内注释允许：`key: value  # 注释`（lint 按 YAML 规则忽略空白后的 `#` 起内容）；`key: # 注释` 视为空值，不登记字段。
- 键名一律 kebab-case。日期一律 `YYYY-MM-DD`。路径一律**相对仓库根**。
- 未在本规范定义的键允许存在（lint 不报警），但不产生任何治理语义。
- 正文里的人类可读状态行（如 ADR 的"状态: Accepted"）可以保留给人看，但**口径以 frontmatter 为准**；两者冲突时 lint 报阻断级。

## 一、spec（`type: spec`）

| 字段 | 必填 | 取值 | 含义 |
|------|------|------|------|
| `type` | 必 | `spec` | 产物类型 |
| `status` | 必 | `Active` / `Superseded` / `Deprecated` / `Archived` | 生命周期状态机（见 `lifecycle.md`） |
| `layer` | 必 | `spec-first` / `spec-anchored` / `spec-as-source` | 持久化层级（见 `persistence-models.md`） |
| `change-model` | 必 | `flow-back` / `flow-forward` / `living-spec` | 变更模型 |
| `review-trigger` | anchored/as-source 必 | 自由文本 | 复审触发条件；spec-first 可省 |
| `superseded-by` | status=Superseded 时必 | 相对路径 | 取代本 spec 的新文件 |
| `supersedes` | 定稿历史化新开时必 | 相对路径 | 本 spec 取代的旧文件（旧键 `replaces` 已更名，lint 报提示级并仍做断链检查） |
| `deprecated-on` | status=Deprecated 时必 | 日期 | 废弃日期 |
| `replaced-by` | status=Deprecated 且有替代口径时必 | 相对路径 | 替代口径指向 |
| `archived-on` | status=Archived 时必 | 日期 | 归档日期 |
| `last-reviewed` | 否 | 日期 | 最近复审日期；复审结论"维持"时更新 |

正文配套规范：

- `spec-anchored` / `spec-as-source` 的 spec 必须含 `## 变更记录` 节，且**创建时即初始化**（首行 = 初稿记录），不得等第一次变更才补——否则 lint 无法区分"未变更"与"漏记录"。
- `superseded-by` / `supersedes` / `replaced-by` 指向的文件必须存在（断链检查）。

## 二、ADR（`type: adr`）

ADR 原来只有正文状态行，本规范将其升级为状态机：`Proposed → Accepted → Superseded / Deprecated`。ADR 是追加式记录，状态流转只允许向前，Accepted 不得回退 Proposed（回退即新开 ADR，见 `templates.md` ADR 集合治理）。

| 字段 | 必填 | 取值 | 含义 |
|------|------|------|------|
| `type` | 必 | `adr` | 产物类型 |
| `status` | 必 | `Proposed` / `Accepted` / `Superseded` / `Deprecated` | 状态机 |
| `date` | 必 | 日期 | 决策日期 |
| `revisit-trigger` | 必 | 自由文本 | 重访触发条件 |
| `superseded-by` | status=Superseded 时必 | `ADR-XXXX` 或相对路径 | 取代本决策的新 ADR |
| `supersedes` | 推翻旧决策时必 | `ADR-XXXX` 或相对路径 | 本 ADR 取代的旧决策 |
| `deprecated-on` | status=Deprecated 时必 | 日期 | 废弃日期 |

正文六段模板（上下文/备选方案/选定方案与理由/后果/重访触发条件）见 `templates.md`，不变。

## 三、契约文档（`type: contract`）

契约文档分三种形态，校验规则不同：

**形态 A：Markdown 契约文档**（带 frontmatter 的 .md）——适用字段：

| 字段 | 必填 | 取值 |
|------|------|------|
| `type` | 必 | `contract` |
| `status` | 必 | 同 spec 四态 |
| `version` | 必 | semver |
| `compat-policy` | 必 | 自由文本（兼容策略，如"additive 优先，破坏性变更升主版本"） |

条件字段配套（status=Superseded/Deprecated/Archived 时的 `superseded-by` / `supersedes` / `deprecated-on` / `replaced-by` / `archived-on`）同第一节 spec 规则。

**形态 B：原生契约文件**（OpenAPI/AsyncAPI 的 .yaml/.yml，JSON Schema 的 .json）——无 frontmatter，lint 改查文件体内：

- `info.version` 必须存在（JSON Schema 查 `title` + `$schema`）；
- 顶层必须有 `x-compat-policy` 扩展键声明兼容策略；
- `deprecated: true` 的端点/消息必须在 `x-compat-policy` 或 description 中给出替代与 sunset 口径（提示级）。

**形态 C：SQL DDL 数据模型契约**（.sql）——无 frontmatter，元数据由文件开头的 `--` 注释头承载（扁平键值，规则同总则）：

```sql
-- contract: data-model
-- version: 1.0.0
-- compat-policy: additive 优先（加表/加可空字段不升版本），破坏性变更升主版本
```

- 注释头必填三键：`contract`（取值固定 `data-model`）、`version`（semver）、`compat-policy`（自由文本），缺失或非法均报阻断级；
- 扫描探针：目录扫描只纳入含 `-- contract:` 注释头的 .sql——migrations 等实现层 SQL 无此头，天然排除；直接指定路径的文件不受限；
- 深度校验（`sqlglot` 可用时接入，缺失降级为提示级）：语法解析失败、外键 REFERENCES 指向文件内不存在的表、出现 INSERT / UPDATE / DELETE / GRANT / DROP / ALTER 语句，均报阻断级；CREATE INDEX / 分区等物理语句报提示级。**逻辑子集纪律**：契约只承载实体、字段、类型、空值、唯一约束、外键（关系与所有权），索引与物理优化不进契约；
- 落盘约定：独立契约落 `docs/contracts/<域>-data-model.sql`；作为 spec 组成部分的随 spec 目录内嵌（同流程图落盘口径）。

## 四、落地设计文档（`type: design-doc`）

可逆决策但先出文档的形态（design-guide 路由产物）。原"首部状态行"升级为 frontmatter，与 ADR 同规则：正文状态行可留给人看，口径以 frontmatter 为准，冲突报阻断级。

| 字段 | 必填 | 取值 | 含义 |
|------|------|------|------|
| `type` | 必 | `design-doc` | 产物类型 |
| `status` | 必 | `草稿` / `待评审` / `已评审` / `已实现` / `已收口` | 五态状态机（转移时机见 design-guide `references/design-doc.md`） |
| `spec` | 否 | 相对路径 | 关联的 spec/ADR（回写决策的落点） |

路径约定 `docs/<域>/<主题>-design.md` 维持不变；不符合 `-design.md` 后缀约定报提示级。

## 五、产物登记表（`docs/design-registry.yaml`）

流程图与原型是无 frontmatter 产物（前者是 mermaid 文档、后者是可运行代码），其生命周期由登记表承载。登记表是仓库唯一的产物登记口径，每仓库至多一份，固定路径 `docs/design-registry.yaml`。

```yaml
version: 1
artifacts:
  - type: flowchart            # 流程图
    path: docs/flowcharts/order-flow.md
    status: active             # draft / active / deprecated
  - type: prototype            # 原型
    path: prototypes/login-flow/
    status: validated          # building / validated / written-back / retired
    write-back: docs/adr/0003-login-contract.md   # written-back / retired 时必填
```

校验规则（均为阻断级，除注明外）：

- `type` / `path` / `status` 必填，`status` 枚举按类型分流；
- `path` 相对仓库根。**存在性按状态分流**：`retired` 原型要求路径**不存在**（回写后删除是原型的合法终点，文件还在说明退役未完成）；其余状态要求路径存在；
- 原型 `written-back` / `retired` 必须配 `write-back`，指向的 spec/ADR 必须存在——这是"原型决策不允许只活在旧原型里"（SKILL.md）的执法点；
- 同一 `path` 重复登记报阻断级；
- 流程图条目（.md）委派 mermaid-business-flowchart 的 `validate_mermaid_flow.py` 做深度校验，错误报阻断级；校验器缺失报提示级；
- **反向孤儿检查**（提示级）：`docs/flowcharts/` 下的 .md 与 `prototypes/` 下的目录未登记即报警——登记表的完整性靠双向核对，不靠自觉。

## 六、agent-map.yaml 最小契约（导航与指针）

`docs/agent-map.yaml` 是**可选**导航文件：任务路由（routes）与废弃关系指针（pointers）。frontmatter 是状态唯一源，本文件永不承载状态定义，只承载导航与指针；**存在即被 lint 校验，不存在即跳过**。未定义的键允许存在（导航信息自由扩展），不产生校验语义。

```yaml
version: 1
routes:                    # 可选：任务 → 必读产物（agent 消费侧入口）
  - match: 订单/账单        # 任务关键词或模式（自由文本）
    read: [docs/spec/billing.md, docs/adr/0003-x.md]
pointers:                  # 可选：主口径与废弃关系指针
  - path: docs/spec/billing-v1.md
    relation: superseded   # current | superseded | deprecated | archived
    by: docs/spec/billing.md   # 可选：替代口径路径
```

校验规则：

- `routes[].match`、`routes[].read`（非空路径列表）、`pointers[].path`、`pointers[].relation` 必填，缺失或结构非法报阻断级；
- `routes[].read` / `pointers[].path` / `pointers[].by` 指向的文件必须存在（断链，阻断级）；
- `pointers[].relation` 与目标 frontmatter `status` 必须一致（current↔Active、superseded↔Superseded、deprecated↔Deprecated、archived↔Archived），冲突报**阻断级**——这是"map 不得形成第二套口径"的执法点，冲突时以 frontmatter 为准修 map；目标无 frontmatter status（非产物文件）时跳过该检查；
- `routes[].read` 指向 status 为 Superseded / Deprecated / Archived 的产物 → 提示级（路由指向失效口径）；
- 反向核对（提示级）：本次扫描范围内 status 为 Superseded / Deprecated / Archived 的产物未在 pointers 登记 → 提示导航滞后。Active 产物不强制登记——map 服务导航，全量清点用派生索引（见第九节）。

## 七、断链检查（跨产物）

lint 对带 frontmatter 的产物做两类引用存在性检查，均为阻断级：

1. frontmatter 路径字段（`superseded-by` / `supersedes` / `replaced-by`）指向的文件必须存在；
2. 正文 Markdown 相对链接（`[x](path)`，跳过 http(s)、纯锚点、mailto）指向的文件必须存在。

这 mechanize 了 design-review 五维度中"断链"维度的文件引用部分；语义层断链（术语无定义、流程中断、状态读写不对称）仍由 design-review 人工对照。

## 八、时态纯净度（提示级）

SKILL.md 的时态卫生（spec 只写应然，禁混入现状/进度/TODO）无法完全机械化，lint 做启发式扫描：正文（跳过 frontmatter 与变更记录节）出现 `TODO`、`Phase N`、`第 N 阶段`、`已实现`、`待开发`、`当前实现`、`目前用` 等标记即报提示级，由人裁定。宁漏不误报，只扫高置信模式。

## 九、lint 结果分级与出口

- **阻断级**：缺 frontmatter、必填字段缺失、枚举非法、条件字段未配套、断链、缺变更记录节（anchored/as-source）、frontmatter 与正文状态行冲突、agent-map 与 frontmatter 状态冲突。阻断级未清零前，产物不得视为已收口（delivery-check 门禁）。
- **提示级**：时态纯净度命中、契约 deprecation 口径缺失、`replaces` 旧键更名、agent-map 导航滞后。提示级不阻断，但必须显式裁定（修或声明豁免）。

校验器：`scripts/design_lint.py`，用法与退出码见其 docstring。

**派生索引**：`design_lint.py --list-artifacts <路径> --root .` 输出扫描范围内全部设计产物（frontmatter 产物 + 登记表产物）的 type / status / layer / 取代链清单，支持 `--format json`。索引是随时可再生成的派生物，**不入库、不维护**——它是"仓库有哪些设计产物、各在什么状态"的一次性机器查询入口，供 project-entry 消费侧发现链使用。
