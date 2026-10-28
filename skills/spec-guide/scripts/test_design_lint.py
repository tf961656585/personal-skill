import re
import tempfile
import unittest
from pathlib import Path

from design_lint import (
    LintReport,
    collect_files,
    collect_inventory,
    crosscheck_terminal_registration,
    lint_file,
    parse_frontmatter,
)

try:
    import sqlglot  # noqa: F401
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False


VALID_SPEC = """---
type: spec
status: Active
layer: spec-anchored
change-model: living-spec
review-trigger: 关联契约大改或定期 6 个月
---

# 订单系统 spec

## 术语定义

订单：用户提交的商品购买请求。

## 变更记录

| 日期 | 变更内容 | 变更原因 | 影响范围 |
|------|----------|----------|----------|
| 2026-08-12 | 初稿 | 系统新建 | 全文 |
"""

VALID_ADR = """---
type: adr
status: Accepted
date: 2026-08-12
revisit-trigger: 仓库数量超过 10 个时重新审视
---

# ADR-0001: 校验脚本放在 skill 内共享

## 上下文

多仓库都要跑同一套校验。

## 备选方案

- skill 共享 —— 单一事实源 / 依赖本地环境
- 仓库 vendor —— 自包含 / 漂移

## 选定方案与理由

skill 共享，避免多份拷贝漂移。

## 后果

- 正面：更新一处全仓库生效
- 负面：CI 依赖 skill 路径

## 重访触发条件

仓库数量超过 10 个，出现协作者无 skill 环境的场景。
"""


def lint_text(tmpdir: str, name: str, text: str) -> LintReport:
    path = Path(tmpdir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report = LintReport()
    lint_file(path, Path(tmpdir), report)
    return report


def blocking_messages(report: LintReport) -> list[str]:
    return [f.message for f in report.blocking()]


class DesignLintTests(unittest.TestCase):
    def test_valid_spec_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/spec/order.md", VALID_SPEC)
            self.assertEqual(report.findings, [])
            self.assertEqual(report.files_checked, 1)

    def test_missing_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/spec/bare.md", "# 没有头部的 spec\n")
            self.assertTrue(report.has_blocking)
            self.assertTrue(any("缺少 frontmatter" in m for m in blocking_messages(report)))

    def test_illegal_enum_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace("status: Active", "status: Living")
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("status 取值非法" in m for m in blocking_messages(report)))

    def test_superseded_without_superseded_by_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace("status: Active", "status: Superseded")
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("superseded-by" in m for m in blocking_messages(report)))

    def test_anchored_without_changelog_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.split("## 变更记录")[0]
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("变更记录" in m for m in blocking_messages(report)))

    def test_broken_markdown_link_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC + "\n详见[订单契约](./contract.yaml)。\n"
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("断链" in m for m in blocking_messages(report)))

    def test_existing_link_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "docs/spec/contract.yaml").parent.mkdir(parents=True, exist_ok=True)
            Path(tmpdir, "docs/spec/contract.yaml").write_text(
                "openapi: 3.1.0\n", encoding="utf-8"
            )
            good = VALID_SPEC + "\n详见[订单契约](./contract.yaml)。\n"
            report = lint_text(tmpdir, "docs/spec/order.md", good)
            self.assertEqual(report.findings, [])

    def test_temporal_marker_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace(
                "订单：用户提交的商品购买请求。",
                "订单：用户提交的商品购买请求。\n\n本模块已实现基本能力。",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("时态纯净度" in f.message for f in report.advisory()))

    def test_body_status_conflict_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_ADR + "\n- 状态: Proposed\n"
            report = lint_text(tmpdir, "docs/adr/0001-x.md", bad)
            self.assertTrue(any("状态口径冲突" in m for m in blocking_messages(report)))

    def test_valid_adr_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/adr/0001-x.md", VALID_ADR)
            self.assertEqual(report.findings, [])

    def test_adr_superseded_by_number_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_ADR.replace(
                "status: Accepted",
                "status: Superseded\nsuperseded-by: ADR-0002",
            )
            report = lint_text(tmpdir, "docs/adr/0001-x.md", bad)
            self.assertEqual(report.findings, [])

    def test_raw_contract_missing_compat_policy_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw = "openapi: 3.1.0\ninfo:\n  title: T\n  version: 1.0.0\n"
            report = lint_text(tmpdir, "contract.yaml", raw)
            self.assertTrue(any("x-compat-policy" in m for m in blocking_messages(report)))

    def test_raw_contract_complete_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw = (
                "openapi: 3.1.0\nx-compat-policy: additive 优先\n"
                "info:\n  title: T\n  version: 1.0.0\n"
            )
            report = lint_text(tmpdir, "contract.yaml", raw)
            self.assertFalse(report.has_blocking)
            # validator 未装时降级提示属于预期行为，装了则无提示
            for f in report.advisory():
                self.assertIn("openapi_spec_validator", f.message)

    def test_parse_frontmatter_flat_only(self):
        parsed = parse_frontmatter("---\ntype: spec\nnested:\n  a: 1\n---\nbody\n")
        self.assertIsNotNone(parsed)
        fields, _ = parsed
        self.assertEqual(fields, {"type": "spec"})

    def test_collect_files_skips_plain_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "README.md").write_text("# 普通文档\n", encoding="utf-8")
            (root / "docs/adr").mkdir(parents=True)
            (root / "docs/adr/0001.md").write_text(VALID_ADR, encoding="utf-8")
            collected = collect_files([root])
            self.assertEqual([p.name for p in collected], ["0001.md"])

    # ===== 波次 1：条件字段与更名宽限 =====

    def test_deprecated_without_deprecated_on_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace("status: Active", "status: Deprecated")
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("deprecated-on" in m for m in blocking_messages(report)))

    def test_deprecated_complete_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "docs/spec").mkdir(parents=True, exist_ok=True)
            (root / "docs/spec/new.md").write_text(VALID_SPEC, encoding="utf-8")
            good = VALID_SPEC.replace(
                "status: Active",
                "status: Deprecated\ndeprecated-on: 2026-08-01\nreplaced-by: docs/spec/new.md",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", good)
            self.assertEqual(report.findings, [])

    def test_deprecated_on_bad_date_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace(
                "status: Active", "status: Deprecated\ndeprecated-on: 2026/08/01",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("deprecated-on 格式非法" in m for m in blocking_messages(report)))

    def test_replaced_by_broken_link_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace(
                "status: Active",
                "status: Deprecated\ndeprecated-on: 2026-08-01\nreplaced-by: docs/spec/ghost.md",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("断链" in m and "replaced-by" in m for m in blocking_messages(report)))

    def test_supersedes_broken_link_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SPEC.replace(
                "review-trigger: 关联契约大改或定期 6 个月",
                "review-trigger: 定期复审\nsupersedes: docs/spec/ghost.md",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", bad)
            self.assertTrue(any("断链" in m and "supersedes" in m for m in blocking_messages(report)))

    def test_replaces_alias_is_advisory_but_still_link_checked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "docs/spec").mkdir(parents=True, exist_ok=True)
            (root / "docs/spec/old.md").write_text(VALID_SPEC, encoding="utf-8")
            aliased = VALID_SPEC.replace(
                "review-trigger: 关联契约大改或定期 6 个月",
                "review-trigger: 定期复审\nreplaces: docs/spec/old.md",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", aliased)
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("已更名为 supersedes" in f.message for f in report.advisory()))

        with tempfile.TemporaryDirectory() as tmpdir:
            dangling = VALID_SPEC.replace(
                "review-trigger: 关联契约大改或定期 6 个月",
                "review-trigger: 定期复审\nreplaces: docs/spec/ghost.md",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", dangling)
            self.assertTrue(any("断链" in m and "replaces" in m for m in blocking_messages(report)))

    def test_frontmatter_inline_comment_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            commented = VALID_SPEC.replace(
                "status: Active", "status: Active   # 当前主口径",
            ).replace(
                "layer: spec-anchored", "layer: spec-anchored   # 长期锚点",
            )
            report = lint_text(tmpdir, "docs/spec/order.md", commented)
            self.assertEqual(report.findings, [])

    def test_key_with_only_comment_is_absent(self):
        parsed = parse_frontmatter("---\ntype: spec\nsupersedes: # 定稿历史化时填\n---\nbody\n")
        self.assertIsNotNone(parsed)
        fields, _ = parsed
        self.assertEqual(fields, {"type": "spec"})


VALID_DESIGN_DOC = """---
type: design-doc
status: 已评审
---

# 登录页交互设计

## 交互流程

用户输入账号密码，点击登录。
"""

VALID_FLOWCHART = """# 订单流程

```mermaid
flowchart TD
    A([开始]) --> B{校验参数}
    B -- 通过 --> C[创建订单]
    B -- 拒绝 --> D[提示错误]
    C --> E([结束])
    D --> E
```
"""


def lint_registry_text(tmpdir: str, registry_yaml: str,
                       files: dict[str, str] | None = None) -> LintReport:
    """搭建含登记表的临时仓库并运行登记表校验。"""
    root = Path(tmpdir)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    report = LintReport()
    reg = root / "docs" / "design-registry.yaml"
    reg.write_text(registry_yaml, encoding="utf-8")
    lint_file(reg, root, report)
    return report


class DesignDocLintTests(unittest.TestCase):
    def test_valid_design_doc_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/shop/login-design.md", VALID_DESIGN_DOC)
            self.assertEqual(report.findings, [])

    def test_design_doc_bad_status_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_DESIGN_DOC.replace("status: 已评审", "status: 进行中")
            report = lint_text(tmpdir, "docs/shop/login-design.md", bad)
            self.assertTrue(any("status 取值非法" in m for m in blocking_messages(report)))

    def test_design_doc_name_convention_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/shop/login.md", VALID_DESIGN_DOC)
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("-design.md" in f.message for f in report.advisory()))


class RegistryLintTests(unittest.TestCase):
    def test_valid_flowchart_entry_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: flowchart\n"
                "    path: docs/flowcharts/order-flow.md\n"
                "    status: active\n",
                {"docs/flowcharts/order-flow.md": VALID_FLOWCHART},
            )
            self.assertEqual(report.findings, [])

    def test_registry_dangling_path_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: flowchart\n"
                "    path: docs/flowcharts/ghost.md\n"
                "    status: active\n",
            )
            self.assertTrue(any("断链" in m for m in blocking_messages(report)))

    def test_invalid_mermaid_in_registered_flowchart_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: flowchart\n"
                "    path: docs/flowcharts/bad.md\n"
                "    status: draft\n",
                {"docs/flowcharts/bad.md": "# 坏图\n\n```mermaid\nsequenceDiagram\nA->>B: hi\n```\n"},
            )
            self.assertTrue(any("流程图校验未过" in m for m in blocking_messages(report)))

    def test_retired_prototype_must_be_deleted_with_writeback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # 合法尾：已回写 + 路径已删除
            good = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: prototype\n"
                "    path: prototypes/old-flow/\n"
                "    status: retired\n"
                "    write-back: docs/adr/0003-x.md\n",
                {"docs/adr/0003-x.md": VALID_ADR},
            )
            self.assertEqual(good.findings, [])

        with tempfile.TemporaryDirectory() as tmpdir:
            # 非法尾 1：退役了但文件还在
            bad1 = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: prototype\n"
                "    path: prototypes/old-flow/\n"
                "    status: retired\n"
                "    write-back: docs/adr/0003-x.md\n",
                {"docs/adr/0003-x.md": VALID_ADR, "prototypes/old-flow/app.py": "print(1)\n"},
            )
            self.assertTrue(any("已退役原型的路径仍存在" in m for m in blocking_messages(bad1)))

        with tempfile.TemporaryDirectory() as tmpdir:
            # 非法尾 2：声称已回写但无 write-back 链接
            bad2 = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: prototype\n"
                "    path: prototypes/old-flow/\n"
                "    status: written-back\n",
            )
            self.assertTrue(any("write-back" in m for m in blocking_messages(bad2)))

    def test_orphan_flowchart_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts: []\n",
                {"docs/flowcharts/orphan.md": VALID_FLOWCHART},
            )
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("未登记的流程图" in f.message for f in report.advisory()))

    def test_registry_rejects_frontmatter_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_registry_text(
                tmpdir,
                "version: 1\nartifacts:\n"
                "  - type: spec\n"
                "    path: docs/spec/x.md\n"
                "    status: active\n",
            )
            self.assertTrue(any("type 非法" in m for m in blocking_messages(report)))


VALID_SQL_CONTRACT = """-- contract: data-model
-- version: 1.0.0
-- compat-policy: additive 优先（加表/加可空字段不升版本），破坏性变更升主版本

CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE
);

CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id)
);
"""


class SqlContractLintTests(unittest.TestCase):
    """SQL DDL 数据模型契约（形态 C）：注释头 + sqlglot 深校。"""

    def test_sql_without_header_not_collected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "migrations").mkdir()
            (root / "migrations/0001_init.sql").write_text(
                "CREATE TABLE t (id INT);\n", encoding="utf-8"
            )
            (root / "docs/contracts").mkdir(parents=True)
            (root / "docs/contracts/shop-data-model.sql").write_text(
                VALID_SQL_CONTRACT, encoding="utf-8"
            )
            collected = collect_files([root])
            self.assertEqual([p.name for p in collected], ["shop-data-model.sql"])

    def test_sql_header_missing_keys_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql",
                               "-- contract: data-model\nCREATE TABLE t (id INT);\n")
            self.assertTrue(any("version" in m for m in blocking_messages(report)))
            self.assertTrue(any("compat-policy" in m for m in blocking_messages(report)))

    def test_sql_bad_version_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT.replace("-- version: 1.0.0", "-- version: 1.0")
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertTrue(any("semver" in m for m in blocking_messages(report)))

    def test_valid_sql_contract_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/contracts/shop-data-model.sql", VALID_SQL_CONTRACT)
            self.assertFalse(report.has_blocking)
            # sqlglot 未装时降级提示属于预期行为，装了则无提示
            for f in report.advisory():
                self.assertIn("sqlglot", f.message)

    @unittest.skipIf(HAS_SQLGLOT, "sqlglot 已安装，降级路径不触发")
    def test_sql_degraded_without_sqlglot_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/contracts/shop-data-model.sql", VALID_SQL_CONTRACT)
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("sqlglot 未安装" in f.message for f in report.advisory()))

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_parse_error_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT + "\nCREATE TABLE broken (\n"
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertTrue(any("解析失败" in m for m in blocking_messages(report)))

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_fk_dangling_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT + (
                "\nCREATE TABLE refunds (\n"
                "    id BIGINT PRIMARY KEY,\n"
                "    order_id BIGINT NOT NULL REFERENCES ghost(id)\n"
                ");\n"
            )
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertTrue(any("不存在的表: ghost" in m for m in blocking_messages(report)))

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_table_level_fk_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            good = VALID_SQL_CONTRACT + (
                "\nCREATE TABLE payments (\n"
                "    id BIGINT PRIMARY KEY,\n"
                "    order_id BIGINT NOT NULL,\n"
                "    FOREIGN KEY (order_id) REFERENCES orders(id)\n"
                ");\n"
            )
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", good)
            self.assertEqual(report.findings, [])

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_dml_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT + "\nINSERT INTO users (id, email) VALUES (1, 'a@b.c');\n"
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertTrue(any("非 CREATE TABLE 语句" in m for m in blocking_messages(report)))

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_alter_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT + "\nALTER TABLE users ADD COLUMN nickname VARCHAR(64);\n"
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertTrue(any("非 CREATE TABLE 语句" in m for m in blocking_messages(report)))

    @unittest.skipUnless(HAS_SQLGLOT, "sqlglot 未安装，跳过深度校验测试")
    def test_sql_create_index_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = VALID_SQL_CONTRACT + "\nCREATE INDEX idx_orders_user ON orders (user_id);\n"
            report = lint_text(tmpdir, "docs/contracts/x-data-model.sql", bad)
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("逻辑子集外语句" in f.message for f in report.advisory()))


# ===== 波次 2：agent-map 与派生索引 =====

SUPERSEDED_SPEC = VALID_SPEC.replace(
    "status: Active",
    "status: Superseded\nsuperseded-by: docs/spec/new.md",
)

VALID_AGENT_MAP = """version: 1
routes:
  - match: 订单
    read: [docs/spec/new.md]
pointers:
  - path: docs/spec/old.md
    relation: superseded
    by: docs/spec/new.md
"""


def lint_repo(tmpdir: str, files: dict[str, str], run_crosscheck: bool = True) -> LintReport:
    """搭建临时仓库，对全部文件跑一次完整 lint（含 agent-map 交叉核对）。"""
    root = Path(tmpdir)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    report = LintReport()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            lint_file(p, root, report)
    if run_crosscheck:
        crosscheck_terminal_registration(report)
    return report


class AgentMapLintTests(unittest.TestCase):
    SPEC_FILES = {
        "docs/spec/new.md": VALID_SPEC,
        "docs/spec/old.md": SUPERSEDED_SPEC,
    }

    def test_valid_agent_map_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_repo(tmpdir, {
                "docs/agent-map.yaml": VALID_AGENT_MAP, **self.SPEC_FILES,
            })
            self.assertEqual(report.findings, [])

    def test_routes_broken_read_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("read: [docs/spec/new.md]",
                                              "read: [docs/spec/ghost.md]")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertTrue(any("read 指向不存在的文件" in m for m in blocking_messages(report)))

    def test_routes_pointing_to_terminal_artifact_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("read: [docs/spec/new.md]",
                                              "read: [docs/spec/old.md]")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("路由指向已失效口径" in f.message for f in report.advisory()))

    def test_pointer_relation_conflicts_with_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("relation: superseded", "relation: deprecated")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertTrue(any("第二套口径" in m for m in blocking_messages(report)))

    def test_pointer_broken_path_and_by_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("path: docs/spec/old.md",
                                              "path: docs/spec/ghost.md")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertTrue(any("path 指向不存在的文件" in m for m in blocking_messages(report)))

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("by: docs/spec/new.md", "by: docs/spec/ghost.md")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertTrue(any("by 断链" in m for m in blocking_messages(report)))

    def test_pointer_illegal_relation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_map = VALID_AGENT_MAP.replace("relation: superseded", "relation: retired")
            report = lint_repo(tmpdir, {"docs/agent-map.yaml": bad_map, **self.SPEC_FILES})
            self.assertTrue(any("relation 非法" in m for m in blocking_messages(report)))

    def test_terminal_artifact_not_pointed_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_repo(tmpdir, {
                "docs/agent-map.yaml": "version: 1\npointers: []\n", **self.SPEC_FILES,
            })
            self.assertFalse(report.has_blocking)
            self.assertTrue(any("未在 pointers 登记" in f.message for f in report.advisory()))

    def test_no_agent_map_skips_crosscheck(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_repo(tmpdir, dict(self.SPEC_FILES))
            self.assertEqual(report.findings, [])


class InventoryTests(unittest.TestCase):
    def test_collect_inventory_covers_frontmatter_and_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            files = {
                "docs/spec/new.md": VALID_SPEC,
                "docs/spec/old.md": SUPERSEDED_SPEC,
                "docs/agent-map.yaml": VALID_AGENT_MAP,
                "docs/design-registry.yaml": (
                    "version: 1\nartifacts:\n"
                    "  - type: flowchart\n"
                    "    path: docs/flowcharts/order-flow.md\n"
                    "    status: active\n"
                    "  - type: prototype\n"
                    "    path: prototypes/old-flow/\n"
                    "    status: retired\n"
                    "    write-back: docs/adr/0003-x.md\n"
                ),
                "docs/flowcharts/order-flow.md": VALID_FLOWCHART,
                "docs/adr/0003-x.md": VALID_ADR,
            }
            for rel, content in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            items = collect_inventory(collect_files([root]), root)
            by_path = {it.path: it for it in items}
            self.assertEqual(by_path["docs/spec/new.md"].type, "spec")
            self.assertEqual(by_path["docs/spec/new.md"].status, "Active")
            self.assertEqual(by_path["docs/spec/old.md"].superseded_by, "docs/spec/new.md")
            self.assertEqual(by_path["docs/flowcharts/order-flow.md"].type, "flowchart")
            self.assertEqual(by_path["prototypes/old-flow/"].extra, "write-back: docs/adr/0003-x.md")
            # agent-map 是导航文件，不进产物索引
            self.assertNotIn("docs/agent-map.yaml", by_path)


class DocsConsistencyTests(unittest.TestCase):
    """规范文档自身不得再漂移：references 内禁止出现已废弃的字段拼写，
    templates.md 的 spec 首部示例必须能直接通过 lint（文档即测试）。"""

    REFERENCES = Path(__file__).resolve().parents[1] / "references"

    LEGACY_PATTERNS = [
        "Superseded by:", "Supersedes:", "Deprecated on:", "Replaced by:",
        "Cleanup owner:", "Archived on:", "review_triggers", "superseded_by:",
        "persistence:", "level: spec-", "model: Living Spec",
    ]

    def test_reference_docs_have_no_legacy_field_spellings(self):
        offenders = []
        for name in ("frontmatter.md", "lifecycle.md", "persistence-models.md", "templates.md"):
            text = (self.REFERENCES / name).read_text(encoding="utf-8")
            for pat in self.LEGACY_PATTERNS:
                if pat in text:
                    offenders.append(f"{name} 含 legacy 拼写: {pat!r}")
        self.assertEqual(offenders, [])

    def test_templates_spec_header_example_passes_lint(self):
        text = (self.REFERENCES / "templates.md").read_text(encoding="utf-8")
        section = text.split("## 四、spec 文档首部元信息模板", 1)[1]
        block = re.search(r"```markdown\n(.*?)```", section, re.DOTALL).group(1)
        doc = block + (
            "\n# 示例 spec\n\n## 变更记录\n\n"
            "| 日期 | 变更内容 | 变更原因 | 影响范围 |\n"
            "|------|----------|----------|----------|\n"
            "| 2026-08-12 | 初稿 | 新建 | 全文 |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            report = lint_text(tmpdir, "docs/spec/example.md", doc)
            self.assertEqual(report.findings, [])


if __name__ == "__main__":
    unittest.main()
