# Spec 模板骨架

本文件是契约文档 / ADR / 术语表的最小骨架参考。载体选择与可逆性判定归 design-guide；SKILL.md 只规定 spec 的写作纪律，不展开各载体的结构。骨架不是填空模板，是结构参照——按需裁剪，不是所有节都必须。

## 一、契约文档（contract-first）

跨边界接口优先用机器可校验格式。选型原则：
- **REST API** → OpenAPI
- **事件/消息流** → AsyncAPI
- **数据结构** → JSON Schema
- **RPC** → gRPC proto
- **数据模型（ER/持久化结构）** → SQL DDL 逻辑子集（sqlglot 机器校验，字段规范见 `frontmatter.md` 形态 C）

契约文档必须声明版本与兼容策略（见 `lifecycle.md` 状态机与 `persistence-models.md` 变更模型）。

### OpenAPI 片段骨架

```yaml
openapi: 3.1.0
info:
  title: <服务名> API
  version: 1.0.0          # semver，破坏性变更必须升主版本
  description: |
    <这个 API 做什么，解决什么问题。一句话。>
servers:
  - url: https://api.example.com/v1

paths:
  /resources/{id}:
    get:
      summary: 获取单个资源
      operationId: getResource
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: 资源详情
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Resource'
        '404':
          $ref: '#/components/responses/NotFound'

components:
  schemas:
    Resource:
      type: object
      required: [id, name]
      properties:
        id:
          type: string
          description: 资源唯一标识
        name:
          type: string
    # 错误响应统一结构
  responses:
    NotFound:
      description: 资源不存在
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
  # Error schema 复用
```

**契约必备节**（缺一不可）：
- 版本号（semver）
- 错误码与错误响应统一结构
- 鉴权方式
- 幂等性约定（写接口）
- 分页约定（列表接口）

### AsyncAPI 片段骨架

```yaml
asyncapi: 3.0.0
info:
  title: <事件流名>
  version: 1.0.0
channels:
  resource.created:
    address: resource.created
    messages:
      resourceCreated:
        $ref: '#/components/messages/ResourceCreated'
components:
  messages:
    ResourceCreated:
      payload:
        type: object
        properties:
          id: { type: string }
          createdAt: { type: string, format: date-time }
```

### JSON Schema 片段骨架

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Resource",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id": { "type": "string" },
    "name": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false
}
```

### SQL DDL 数据模型骨架

跨边界数据模型（ER/持久化结构）的契约载体。只写**逻辑子集**：实体、字段、类型、空值、唯一约束、外键（表达关系与所有权）。索引、分区、存储参数等物理优化不进契约；INSERT/ALTER 等现状或迁移内容不进契约（lint 深校执法，见 `frontmatter.md` 形态 C）。

```sql
-- contract: data-model
-- version: 1.0.0
-- compat-policy: additive 优先（加表/加可空字段不升版本），破坏性变更升主版本

CREATE TABLE users (
    id          BIGINT PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    created_at  TIMESTAMP NOT NULL
);

CREATE TABLE orders (
    id          BIGINT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),  -- 订单归属用户（所有权）
    status      VARCHAR(32) NOT NULL,
    total_cents BIGINT NOT NULL
);
```

评审需要 ER 图时，从 DDL 临时生成 Mermaid erDiagram 给人看，**图不落盘**——DDL 是唯一事实源，不双写。未来若要把图内嵌进 spec，必须先给 lint 加「派生图与内嵌块对账」检查，否则禁止双载体。

### 契约变更纪律

- **破坏性变更**（删字段、改类型、改语义）必须升主版本，不得 silent breaking。
- **兼容性演进优先**：能 additive 就不 versioning（加可选字段、加新端点不升主版本）。
- **deprecation 必须写进 spec**：标 `deprecated: true` + 废弃日期 + 替代方案，并设定 sunset 时机。
- 见 `persistence-models.md` 的变更模型选择。

## 二、ADR（Architecture Decision Record）

单个或少数不可逆决策的常态载体。半页以内。ADR 是追加式记录——决策变更时新开 ADR 并链接 supersedes，不改写历史 ADR（见 `lifecycle.md` 定稿历史化）。

### ADR 六段模板

frontmatter 为机器可读口径（字段规范见 `frontmatter.md`），正文状态行可保留给人看，但两者冲突时 lint 报阻断级：

```markdown
---
type: adr
status: Proposed
date: YYYY-MM-DD
revisit-trigger: <一句话：什么情况应重新审视本决策>
---

# ADR-<编号>: <决策标题>

- 决策者: <角色/人>

## 上下文
<为什么现在要做这个决策？面临什么问题、什么约束、什么触发事件。事实陈述，不带方案倾向。>

## 备选方案
列出至少 2 个备选：
- 方案 A：<描述> —— 优点 / 缺点
- 方案 B：<描述> —— 优点 / 缺点

## 选定方案与理由
<选了哪个，为什么选它。理由必须对照备选方案的缺点，说明为什么接受本方案的 trade-off。>

## 后果
- 正面：<本决策带来什么好处>
- 负面：<本决策带来什么代价、限制、技术债>
- 需跟进：<衍生出的后续工作或需观察的点>

## 重访触发条件
<什么情况下应该重新审视本决策。例如：上游系统换型、并发量增长 10 倍、出现新备选技术。>
```

### ADR 集合治理

- 编号连续（ADR-0001、ADR-0002），不复用编号。
- 决策被推翻时新开 ADR，旧 ADR frontmatter 标 `status: Superseded` + `superseded-by: ADR-XXXX`，新 ADR 标 `supersedes: ADR-YYYY`。
- ADR 目录建议 `docs/adr/`，带索引文件列出所有 ADR 及当前状态。

## 三、术语表（Glossary）

术语表是 spec 生态的单一术语源。SKILL.md 要求"首次出现的术语必须有定义"，术语表就是这些定义的集中地。

### 术语表条目模板

```markdown
## <术语>

- 定义: <一句话精确定义，无歧义>
- 作用域: <本术语在哪些 spec/模块中适用>
- 状态: active | deprecated | superseded by <新术语>
- 别名: <异名同义的其他叫法，列出以避免分裂>
- 关联: <与本术语易混的术语，说明区别>
- 引入于: <YYYY-MM-DD 或 spec 版本>
- 变更记录:
  - YYYY-MM-DD: <改名/修正定义/废弃>
```

### 术语表维护纪律

- **同名异义**禁止：同一术语只能有一个定义。若不同领域确实需要同名，用作用域或前缀区分（如 `order` 在交易域 vs 物流域应区分）。
- **异名同义**合并：发现两个术语指同一概念时，留一个为主口径，另一个标 `superseded by <主术语>` 并保留为别名。
- **改名走变更记录**：术语改名不改定义，在变更记录记一行，并在旧名条目标 `superseded by`。
- **废弃不删**：废弃术语保留条目，标状态 `deprecated`，写明替代术语——避免读者遇到旧术语时找不到解释。

## 四、spec 文档首部元信息模板

spec-anchored 层级 spec 的完整首部（字段口径以 `frontmatter.md` 为唯一源；本节示例被 `test_design_lint.py` 直接消费，改动必须同步跑 lint 测试）：

```markdown
---
type: spec
status: Active
layer: spec-anchored
change-model: living-spec
review-trigger: <复审条件；多条件分号分隔>
---

<!-- 条件字段：定稿历史化新开时加 supersedes: <旧 spec 相对路径>；被取代时配 status: Superseded
     + superseded-by: <新 spec 相对路径>；status: Deprecated 必须加 deprecated-on: <YYYY-MM-DD>，
     有替代口径时加 replaced-by: <相对路径>；status: Archived 必须加 archived-on: <YYYY-MM-DD>。
     可选 last-reviewed: <YYYY-MM-DD> 记录最近复审日期。行内注释（# 起）lint 会忽略。 -->
```

spec-first 层级可省 `review-trigger` 与变更记录节，但 `type` / `status` / `layer` / `change-model` 四键仍是 lint 必填。

## 五、使用原则

- 骨架是结构参照，不是填空题。按 spec 的实际复杂度裁剪——简单模块不必上完整契约骨架。
- 契约文档（OpenAPI 等）一旦写出就是机器可校验的事实源，其变更纪律严于普通 spec 文本。
- ADR 是轻量载体，别把完整 spec 的内容塞进 ADR；ADR 只记决策，不记系统全貌。
- 术语表独立成文（`docs/spec/glossary.md`），各 spec 引用而非各自重复定义。
