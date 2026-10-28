#!/usr/bin/env python3
"""
设计层产物 frontmatter 与链接校验器。

校验 spec 系设计层产物（spec / ADR / 契约文档）的机器可读头部、
条件字段配套、断链与时态纯净度。字段规范详见 references/frontmatter.md。

用法:
    python3 design_lint.py <文件或目录> [更多路径...]
    python3 design_lint.py docs --root . --format json
    python3 design_lint.py docs --root . --list-artifacts   # 全产物派生索引

目录扫描规则（避免误扫 README 等非产物文件）:
    - .md：含 frontmatter 块，或位于 docs/spec、docs/adr 路径下
    - .yaml/.yml：含 openapi: 或 asyncapi: 顶层键（原生契约文件），
      或文件名为 design-registry.yaml（产物登记表）
      或文件名为 agent-map.yaml（文档地图，存在即校验）
    - .json：含 json-schema.org 的 $schema（JSON Schema 契约）
    - .sql：含 `-- contract:` 注释头（SQL DDL 数据模型契约，形态 C；
      migrations 等实现层 SQL 无此头，天然排除）

退出码:
    0  无阻断级问题（仅有提示级或完全通过）
    1  存在阻断级问题
    2  输入错误（路径不存在、未扫描到任何产物）
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ===== 字段规范（与 references/frontmatter.md 对齐）=====

SPEC_STATUS = {"Active", "Superseded", "Deprecated", "Archived"}
SPEC_LAYER = {"spec-first", "spec-anchored", "spec-as-source"}
SPEC_CHANGE_MODEL = {"flow-back", "flow-forward", "living-spec"}
ADR_STATUS = {"Proposed", "Accepted", "Superseded", "Deprecated"}
DESIGN_DOC_STATUS = {"草稿", "待评审", "已评审", "已实现", "已收口"}

REQUIRED_BY_TYPE = {
    "spec": ["type", "status", "layer", "change-model"],
    "adr": ["type", "status", "date", "revisit-trigger"],
    "contract": ["type", "status", "version", "compat-policy"],
    "design-doc": ["type", "status"],
}

# 产物登记表（流程图 / 原型生命周期承载）
REGISTRY_NAME = "design-registry.yaml"
REGISTRY_FLOWCHART_STATUS = {"draft", "active", "deprecated"}
REGISTRY_PROTOTYPE_STATUS = {"building", "validated", "written-back", "retired"}

# agent-map 最小契约（frontmatter.md 第六节）：导航与指针，不承载状态定义
AGENT_MAP_NAME = "agent-map.yaml"
POINTER_RELATION_TO_STATUS = {
    "current": "Active",
    "superseded": "Superseded",
    "deprecated": "Deprecated",
    "archived": "Archived",
}
TERMINAL_STATUS = {"Superseded", "Deprecated", "Archived"}

# frontmatter 块与扁平键值行
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
FLAT_KV_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*:\s*(.+?)\s*$")

# 日期 YYYY-MM-DD
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# semver（宽松）
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")

# Markdown 相对链接：跳过 http(s)、纯锚点、mailto
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]+)?\)")

# 正文状态行（与 frontmatter 冲突检测用）：状态: Accepted
BODY_STATUS_LINE_RE = re.compile(r"^[-*]?\s*状态\s*[:：]\s*([A-Za-z]+)", re.MULTILINE)

# 时态纯净度高置信模式（提示级）
TEMPORAL_PATTERNS = [
    (re.compile(r"\bTODO\b"), "TODO 标记"),
    (re.compile(r"\bPhase\s*\d", re.IGNORECASE), "Phase 进度标记"),
    (re.compile(r"第\s*\d+\s*阶段"), "阶段进度标记"),
    (re.compile(r"已实现|待开发|当前实现|目前用"), "现状/进度描述"),
]

# 原生契约文件探测
RAW_CONTRACT_KEY_RE = re.compile(r"^(openapi|asyncapi)\s*:", re.MULTILINE)
RAW_VERSION_RE = re.compile(r"^\s{1,4}version\s*:\s*\S+", re.MULTILINE)
RAW_COMPAT_RE = re.compile(r"^x-compat-policy\s*:", re.MULTILINE)

# SQL DDL 数据模型契约（形态 C）探测：文件开头注释头 `-- contract: data-model`
SQL_CONTRACT_RE = re.compile(r"^--\s*contract\s*:\s*\S+", re.MULTILINE)
SQL_CONTRACT_KIND = {"data-model"}


# ===== 数据结构 =====


@dataclass
class Finding:
    """单条校验发现。"""

    severity: str  # blocking | advisory
    file: Path
    line: int
    message: str


@dataclass
class LintReport:
    """校验报告。"""

    findings: list[Finding] = field(default_factory=list)
    files_checked: int = 0
    # 交叉核对状态（agent-map ↔ frontmatter）
    terminal_artifacts: list[tuple[str, str]] = field(default_factory=list)  # (相对路径, status)
    agent_map_pointed: set[str] | None = None  # None = 本次未扫到 agent-map
    agent_map_path: Path | None = None

    @property
    def has_blocking(self) -> bool:
        return any(f.severity == "blocking" for f in self.findings)

    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    def advisory(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "advisory"]


# ===== frontmatter 解析 =====


def parse_frontmatter(text: str) -> tuple[dict[str, str], int] | None:
    """解析文件开头的扁平 YAML frontmatter。

    返回 (字段字典, frontmatter 结束行号)；无 frontmatter 返回 None。
    出现嵌套（缩进键）时该行被忽略，由调用方决定是否另行报警。
    行内注释按 YAML 规则处理：`key: value  # 注释` 忽略 `#` 起内容；
    `key: # 注释` 视为空值，不登记字段。
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        kv = FLAT_KV_RE.match(line)
        if kv:
            raw = kv.group(2).strip()
            if raw.startswith("#"):
                continue  # `key: # 注释` → YAML null，不登记
            value = re.split(r"\s+#", raw, maxsplit=1)[0].strip().strip('"').strip("'")
            if value:
                fields[kv.group(1)] = value
    end_line = text[: match.end()].count("\n") + 1
    return fields, end_line


def detect_product_type(path: Path, text: str, fm: dict[str, str] | None) -> str | None:
    """判定产物类型：frontmatter type 优先，原生契约文件按内容探测。"""
    if fm and fm.get("type") in REQUIRED_BY_TYPE:
        return fm["type"]
    if path.suffix in {".yaml", ".yml"} and RAW_CONTRACT_KEY_RE.search(text):
        return "contract-raw"
    if path.suffix == ".json" and "json-schema.org" in text:
        return "contract-raw"
    if path.suffix == ".sql" and SQL_CONTRACT_RE.search(text):
        return "contract-raw"
    return None


# ===== 各类型校验 =====


def check_enum(findings: list[Finding], path: Path, field_name: str,
               value: str, allowed: set[str]) -> None:
    if value not in allowed:
        findings.append(Finding(
            "blocking", path, 1,
            f"字段 {field_name} 取值非法: {value!r}（允许: {' / '.join(sorted(allowed))}）",
        ))


def lint_common(path: Path, fm: dict[str, str], ptype: str,
                findings: list[Finding]) -> None:
    """必填字段、枚举、条件字段配套。"""
    for req in REQUIRED_BY_TYPE[ptype]:
        if req not in fm:
            findings.append(Finding("blocking", path, 1, f"缺少必填字段: {req}"))

    if ptype == "spec":
        if "status" in fm:
            check_enum(findings, path, "status", fm["status"], SPEC_STATUS)
        if "layer" in fm:
            check_enum(findings, path, "layer", fm["layer"], SPEC_LAYER)
        if "change-model" in fm:
            check_enum(findings, path, "change-model", fm["change-model"], SPEC_CHANGE_MODEL)
        if fm.get("layer") in {"spec-anchored", "spec-as-source"} and "review-trigger" not in fm:
            findings.append(Finding(
                "blocking", path, 1,
                f"layer={fm['layer']} 的 spec 必须声明 review-trigger（复审触发条件）",
            ))
    elif ptype == "adr":
        if "status" in fm:
            check_enum(findings, path, "status", fm["status"], ADR_STATUS)
        if "date" in fm and not DATE_RE.match(fm["date"]):
            findings.append(Finding(
                "blocking", path, 1, f"date 格式非法: {fm['date']!r}（要求 YYYY-MM-DD）",
            ))
    elif ptype == "contract":
        if "status" in fm:
            check_enum(findings, path, "status", fm["status"], SPEC_STATUS)
        if "version" in fm and not SEMVER_RE.match(fm["version"]):
            findings.append(Finding(
                "blocking", path, 1, f"version 非法: {fm['version']!r}（要求 semver）",
            ))
    elif ptype == "design-doc":
        if "status" in fm:
            check_enum(findings, path, "status", fm["status"], DESIGN_DOC_STATUS)
        if not path.stem.endswith("-design"):
            findings.append(Finding(
                "advisory", path, 1,
                f"设计文档路径约定为 docs/<域>/<主题>-design.md，当前文件名: {path.name}",
            ))

    # 条件字段配套（spec / contract / adr 通用）
    status = fm.get("status")
    if status == "Superseded" and "superseded-by" not in fm:
        findings.append(Finding(
            "blocking", path, 1, "status=Superseded 必须配 superseded-by 字段",
        ))
    if status == "Deprecated" and ptype in {"spec", "contract", "adr"} and "deprecated-on" not in fm:
        findings.append(Finding(
            "blocking", path, 1, "status=Deprecated 必须配 deprecated-on 字段（废弃日期）",
        ))
    if status == "Archived" and ptype in {"spec", "contract"} and "archived-on" not in fm:
        findings.append(Finding(
            "blocking", path, 1, "status=Archived 必须配 archived-on 字段",
        ))
    for date_key in ("deprecated-on", "archived-on", "last-reviewed"):
        if date_key in fm and not DATE_RE.match(fm[date_key]):
            findings.append(Finding(
                "blocking", path, 1,
                f"{date_key} 格式非法: {fm[date_key]!r}（要求 YYYY-MM-DD）",
            ))


def lint_changelog_section(path: Path, fm: dict[str, str], text: str,
                           findings: list[Finding]) -> None:
    """spec-anchored / spec-as-source 必须有变更记录节（创建时即初始化）。"""
    if fm.get("type") == "spec" and fm.get("layer") in {"spec-anchored", "spec-as-source"}:
        if not re.search(r"^#{1,6}\s*变更记录", text, re.MULTILINE):
            findings.append(Finding(
                "blocking", path, 1,
                f"layer={fm['layer']} 的 spec 缺少「## 变更记录」节（创建时即应初始化）",
            ))


def lint_path_fields(path: Path, fm: dict[str, str], root: Path,
                     findings: list[Finding]) -> None:
    """frontmatter 路径字段断链检查（相对仓库根解析）。"""
    # 更名宽限：spec 的旧键 replaces 已更名 supersedes，提示级，仍做断链检查
    if fm.get("type") == "spec" and "replaces" in fm:
        findings.append(Finding(
            "advisory", path, 1,
            "字段 replaces 已更名为 supersedes，请改名（宽限期内仍做断链检查）",
        ))
    for key in ("superseded-by", "supersedes", "replaces", "replaced-by", "spec"):
        raw = fm.get(key)
        if not raw:
            continue
        # ADR 允许 ADR-XXXX 编号形式，存在性由 adr 集合治理保证，此处跳过
        if re.fullmatch(r"ADR-\d+", raw):
            continue
        if not (root / raw).exists():
            findings.append(Finding(
                "blocking", path, 1,
                f"断链: 字段 {key} 指向不存在的文件: {raw}",
            ))


def strip_excluded_regions(text: str, fm_end_line: int) -> list[tuple[int, str]]:
    """剔除 frontmatter、变更记录节、代码块后的正文行（供时态扫描）。"""
    lines = text.splitlines()
    result: list[tuple[int, str]] = []
    in_code = False
    in_changelog = False
    for i, line in enumerate(lines, start=1):
        if i < fm_end_line:
            continue
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"^#{1,6}\s*(.*)", line)
        if heading:
            in_changelog = "变更记录" in heading.group(1)
            continue
        if in_changelog:
            continue
        result.append((i, line))
    return result


def lint_temporal_purity(path: Path, text: str, fm_end_line: int,
                         findings: list[Finding]) -> None:
    """时态纯净度启发式扫描（提示级）。"""
    for line_no, line in strip_excluded_regions(text, fm_end_line):
        for pattern, desc in TEMPORAL_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    "advisory", path, line_no, f"时态纯净度疑似违规（{desc}）: {line.strip()[:60]}",
                ))
                break


def lint_md_links(path: Path, text: str, fm_end_line: int,
                  findings: list[Finding]) -> None:
    """正文 Markdown 相对链接存在性检查（相对文件所在目录解析）。"""
    lines = text.splitlines()
    for match in MD_LINK_RE.finditer(text):
        target = match.group(1)
        if re.match(r"^(https?|mailto):", target):
            continue
        line_no = text[: match.start()].count("\n") + 1
        if line_no < fm_end_line:
            continue  # frontmatter 内的路径由 lint_path_fields 管
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            findings.append(Finding(
                "blocking", path, line_no, f"断链: Markdown 链接指向不存在的文件: {target}",
            ))


def lint_body_status_conflict(path: Path, fm: dict[str, str], text: str,
                              fm_end_line: int, findings: list[Finding]) -> None:
    """frontmatter status 与正文状态行冲突检测。"""
    fm_status = fm.get("status")
    if not fm_status:
        return
    for match in BODY_STATUS_LINE_RE.finditer(text):
        line_no = text[: match.start()].count("\n") + 1
        if line_no < fm_end_line:
            continue
        body_status = match.group(1)
        if body_status in SPEC_STATUS | ADR_STATUS and body_status != fm_status:
            findings.append(Finding(
                "blocking", path, line_no,
                f"状态口径冲突: frontmatter status={fm_status}，正文状态行={body_status}",
            ))


def lint_contract_raw(path: Path, text: str, findings: list[Finding]) -> None:
    """原生契约文件（OpenAPI/AsyncAPI/JSON Schema/SQL DDL）校验。"""
    if path.suffix == ".sql":
        lint_sql_contract(path, text, findings)
        return
    if path.suffix == ".json":
        if '"title"' not in text or '"$schema"' not in text:
            findings.append(Finding(
                "blocking", path, 1, "JSON Schema 契约缺少 title 或 $schema",
            ))
        if '"x-compat-policy"' not in text:
            findings.append(Finding(
                "blocking", path, 1, "契约缺少 x-compat-policy（兼容策略声明）",
            ))
        return
    if not RAW_VERSION_RE.search(text):
        findings.append(Finding(
            "blocking", path, 1, "契约缺少 info.version（版本号）",
        ))
    if not RAW_COMPAT_RE.search(text):
        findings.append(Finding(
            "blocking", path, 1, "契约缺少顶层 x-compat-policy（兼容策略声明）",
        ))
    # 深度校验：openapi_spec_validator 可用时接入，缺失时降级为提示
    if re.match(r"^openapi\s*:", text):
        _run_openapi_validator(path, text, findings)


def _run_openapi_validator(path: Path, text: str, findings: list[Finding]) -> None:
    """外部 validator 委派：装了才深校，没装不假装校过。"""
    try:
        import yaml  # type: ignore
        from openapi_spec_validator import validate  # type: ignore
    except ImportError:
        findings.append(Finding(
            "advisory", path, 1,
            "openapi_spec_validator 未安装，契约仅做结构检查（pip install openapi-spec-validator 可启用深度校验）",
        ))
        return
    try:
        validate(yaml.safe_load(text))
    except Exception as e:  # validator 的异常类型随版本变化，统一兜底
        findings.append(Finding(
            "blocking", path, 1, f"OpenAPI 深度校验未通过: {str(e)[:200]}",
        ))


def parse_sql_header(text: str) -> dict[str, str]:
    """解析 .sql 文件开头的 `-- key: value` 注释头（扁平键值，规则同 frontmatter）。"""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue  # 允许注释头内空行
        if not stripped.startswith("--"):
            break  # 第一行非注释即注释头结束
        kv = FLAT_KV_RE.match(stripped[2:].strip())
        if kv:
            fields[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    return fields


def lint_sql_contract(path: Path, text: str, findings: list[Finding]) -> None:
    """SQL DDL 数据模型契约（形态 C）校验：注释头必填键 + sqlglot 深度校验。"""
    header = parse_sql_header(text)
    kind = header.get("contract")
    if kind is None:
        findings.append(Finding(
            "blocking", path, 1, "契约注释头缺少 contract 键（取值: data-model）",
        ))
    elif kind not in SQL_CONTRACT_KIND:
        findings.append(Finding(
            "blocking", path, 1,
            f"契约注释头 contract 取值非法: {kind!r}（允许: {' / '.join(sorted(SQL_CONTRACT_KIND))}）",
        ))
    version = header.get("version")
    if version is None:
        findings.append(Finding(
            "blocking", path, 1, "契约注释头缺少 version（版本号，semver）",
        ))
    elif not SEMVER_RE.match(version):
        findings.append(Finding(
            "blocking", path, 1, f"version 非法: {version!r}（要求 semver）",
        ))
    if "compat-policy" not in header:
        findings.append(Finding(
            "blocking", path, 1, "契约注释头缺少 compat-policy（兼容策略声明）",
        ))
    # 深度校验：sqlglot 可用时接入，缺失时降级为提示
    _run_sqlglot_validator(path, text, findings)


def _run_sqlglot_validator(path: Path, text: str, findings: list[Finding]) -> None:
    """sqlglot 委派：装了才深校，没装不假装校过（同 OpenAPI 模式）。

    深校三项：语法解析、逻辑子集纪律（只承载 CREATE TABLE 目标终态）、
    外键引用完整性（REFERENCES 指向文件内已定义的表）。
    """
    try:
        import sqlglot  # type: ignore
        from sqlglot import exp  # type: ignore
    except ImportError:
        findings.append(Finding(
            "advisory", path, 1,
            "sqlglot 未安装，DDL 契约仅做注释头结构检查（pip install sqlglot 可启用深度校验）",
        ))
        return
    try:
        statements = [st for st in sqlglot.parse(text) if st is not None]
    except Exception as e:  # ParseError 类型随版本变化，统一兜底
        findings.append(Finding(
            "blocking", path, 1, f"DDL 解析失败: {str(e)[:200]}",
        ))
        return

    tables: set[str] = set()
    referenced: set[str] = set()
    for st in statements:
        if isinstance(st, exp.Create):
            kind = (st.args.get("kind") or "").upper()
            if kind == "TABLE":
                name_node = st.this
                if isinstance(name_node, exp.Schema):
                    name_node = name_node.this
                if isinstance(name_node, exp.Table):
                    tables.add(name_node.name.lower())
            else:
                findings.append(Finding(
                    "advisory", path, 1,
                    f"逻辑子集外语句: CREATE {kind or '?'}（索引/物理优化不属于逻辑数据模型契约）",
                ))
        else:
            findings.append(Finding(
                "blocking", path, 1,
                f"非 CREATE TABLE 语句（{type(st).__name__}）：契约只承载目标终态的逻辑数据模型，"
                "不写 DML/GRANT/DROP/ALTER",
            ))
        # 内联 REFERENCES 与表级 FOREIGN KEY 都含 exp.Reference 节点，一次遍历全覆盖；
        # Reference.this 是 Schema 包装（sqlglot 30.x），需解包取 Table
        for ref in st.find_all(exp.Reference):
            target = ref.this
            if isinstance(target, exp.Schema):
                target = target.this
            if isinstance(target, exp.Table):
                referenced.add(target.name.lower())

    for name in sorted(referenced):
        if name not in tables:
            findings.append(Finding(
                "blocking", path, 1,
                f"外键 REFERENCES 指向文件内不存在的表: {name}（断链）",
            ))


# ===== 产物登记表校验 =====


def _load_mermaid_validator():
    """跨 skill 委派：加载 mermaid-business-flowchart 的校验器。

    流程图的深度校验规则唯一源在 mermaid skill，本 lint 不另立规则。
    """
    validator_path = (
        Path(__file__).resolve().parents[2]
        / "mermaid-business-flowchart" / "scripts" / "validate_mermaid_flow.py"
    )
    if not validator_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("validate_mermaid_flow", validator_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lint_registry(path: Path, root: Path, report: LintReport) -> None:
    """产物登记表校验：条目合法性 + 登记↔文件双向一致性 + 原型「有尾」执法。"""
    findings = report.findings
    try:
        import yaml  # type: ignore
    except ImportError:
        findings.append(Finding(
            "blocking", path, 1,
            "解析登记表需要 PyYAML（pip install pyyaml）——登记表无法校验即门禁不得通过",
        ))
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        findings.append(Finding("blocking", path, 1, f"登记表 YAML 解析失败: {str(e)[:200]}"))
        return

    artifacts = (data or {}).get("artifacts") or []
    if not isinstance(artifacts, list):
        findings.append(Finding("blocking", path, 1, "登记表 artifacts 必须是列表"))
        return

    registered_paths: set[str] = set()
    mermaid = _load_mermaid_validator()

    for idx, entry in enumerate(artifacts, start=1):
        where = f"条目 #{idx}"
        if not isinstance(entry, dict):
            findings.append(Finding("blocking", path, 1, f"{where}: 必须是键值映射"))
            continue
        etype = entry.get("type")
        epath = entry.get("path")
        estatus = entry.get("status")
        if not all([etype, epath, estatus]):
            findings.append(Finding(
                "blocking", path, 1, f"{where}: type / path / status 必填（当前: {entry}）",
            ))
            continue
        if epath in registered_paths:
            findings.append(Finding("blocking", path, 1, f"{where}: path 重复登记: {epath}"))
        registered_paths.add(epath)

        target = root / epath
        if etype == "flowchart":
            if estatus not in REGISTRY_FLOWCHART_STATUS:
                findings.append(Finding(
                    "blocking", path, 1,
                    f"{where}: flowchart status 非法: {estatus!r}（允许: {' / '.join(sorted(REGISTRY_FLOWCHART_STATUS))}）",
                ))
            if not target.exists():
                findings.append(Finding("blocking", path, 1, f"{where}: 断链，文件不存在: {epath}"))
            elif target.suffix == ".md":
                if mermaid is None:
                    findings.append(Finding(
                        "advisory", path, 1, f"{where}: mermaid 校验器缺失，跳过流程图深度校验: {epath}",
                    ))
                else:
                    errors = mermaid.validate_mermaid_text(mermaid.load_mermaid_text(target))
                    for err in errors:
                        findings.append(Finding("blocking", path, 1, f"{where}: 流程图校验未过: {epath}: {err}"))
        elif etype == "prototype":
            if estatus not in REGISTRY_PROTOTYPE_STATUS:
                findings.append(Finding(
                    "blocking", path, 1,
                    f"{where}: prototype status 非法: {estatus!r}（允许: {' / '.join(sorted(REGISTRY_PROTOTYPE_STATUS))}）",
                ))
            write_back = entry.get("write-back")
            # 「有尾」执法：回写完成才可退役，退役即删除
            if estatus in {"written-back", "retired"}:
                if not write_back:
                    findings.append(Finding(
                        "blocking", path, 1,
                        f"{where}: status={estatus} 必须配 write-back（原型决策不允许只活在原型里）",
                    ))
                elif not (root / write_back).exists():
                    findings.append(Finding(
                        "blocking", path, 1, f"{where}: write-back 断链: {write_back}",
                    ))
            if estatus == "retired":
                if target.exists():
                    findings.append(Finding(
                        "blocking", path, 1,
                        f"{where}: 已退役原型的路径仍存在（退役 = 回写后删除）: {epath}",
                    ))
            elif not target.exists():
                findings.append(Finding("blocking", path, 1, f"{where}: 断链，路径不存在: {epath}"))
        else:
            findings.append(Finding(
                "blocking", path, 1,
                f"{where}: type 非法: {etype!r}（登记表只承载 flowchart / prototype，"
                "frontmatter 产物自描述无需登记）",
            ))

    # 反向孤儿检查（提示级）：常规路径下的无头产物未登记
    for flowchart in sorted((root / "docs" / "flowcharts").rglob("*.md")) if (root / "docs" / "flowcharts").is_dir() else []:
        rel = flowchart.relative_to(root).as_posix()
        if rel not in registered_paths:
            findings.append(Finding("advisory", path, 1, f"未登记的流程图: {rel}"))
    prototypes_dir = root / "prototypes"
    if prototypes_dir.is_dir():
        for proto in sorted(p for p in prototypes_dir.iterdir() if p.is_dir()):
            rel = proto.relative_to(root).as_posix() + "/"
            if rel not in registered_paths and rel.rstrip("/") not in registered_paths:
                findings.append(Finding("advisory", path, 1, f"未登记的原型: {rel}"))


# ===== agent-map.yaml 校验 =====


def read_frontmatter_status(target: Path) -> str | None:
    """读取目标文件的 frontmatter status（供 agent-map 交叉核对）；读不到返回 None。"""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    parsed = parse_frontmatter(text)
    if not parsed:
        return None
    return parsed[0].get("status")


def lint_agent_map(path: Path, root: Path, report: LintReport) -> None:
    """agent-map.yaml 校验：导航与指针的断链 + 与 frontmatter 状态一致性。

    frontmatter 是状态唯一源；map 只承载导航与指针（routes / pointers），
    与 frontmatter 状态冲突即第二套口径（阻断级），冲突时以 frontmatter 为准修 map。
    """
    findings = report.findings
    report.agent_map_path = path
    report.agent_map_pointed = set()
    try:
        import yaml  # type: ignore
    except ImportError:
        findings.append(Finding(
            "blocking", path, 1,
            "解析 agent-map 需要 PyYAML（pip install pyyaml）",
        ))
        return
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        findings.append(Finding("blocking", path, 1, f"agent-map YAML 解析失败: {str(e)[:200]}"))
        return
    if data is None:
        data = {}
    if not isinstance(data, dict):
        findings.append(Finding("blocking", path, 1, "agent-map 顶层必须是键值映射"))
        return

    routes = data.get("routes") or []
    if not isinstance(routes, list):
        findings.append(Finding("blocking", path, 1, "routes 必须是列表"))
        routes = []
    for idx, entry in enumerate(routes, start=1):
        where = f"routes 条目 #{idx}"
        if not isinstance(entry, dict):
            findings.append(Finding("blocking", path, 1, f"{where}: 必须是键值映射"))
            continue
        if not entry.get("match"):
            findings.append(Finding("blocking", path, 1, f"{where}: 缺少 match（任务模式）"))
        read_list = entry.get("read")
        if not isinstance(read_list, list) or not read_list:
            findings.append(Finding("blocking", path, 1, f"{where}: read 必须是非空路径列表"))
            continue
        for rel in read_list:
            if not isinstance(rel, str):
                findings.append(Finding(
                    "blocking", path, 1, f"{where}: read 项必须是路径字符串: {rel!r}",
                ))
                continue
            target = root / rel
            if not target.exists():
                findings.append(Finding(
                    "blocking", path, 1, f"{where}: 断链，read 指向不存在的文件: {rel}",
                ))
                continue
            status = read_frontmatter_status(target)
            if status in TERMINAL_STATUS:
                findings.append(Finding(
                    "advisory", path, 1,
                    f"{where}: 路由指向已失效口径（status={status}）: {rel}——应指向当前主口径",
                ))

    pointers = data.get("pointers") or []
    if not isinstance(pointers, list):
        findings.append(Finding("blocking", path, 1, "pointers 必须是列表"))
        pointers = []
    for idx, entry in enumerate(pointers, start=1):
        where = f"pointers 条目 #{idx}"
        if not isinstance(entry, dict):
            findings.append(Finding("blocking", path, 1, f"{where}: 必须是键值映射"))
            continue
        rel = entry.get("path")
        relation = entry.get("relation")
        if not rel or not relation:
            findings.append(Finding(
                "blocking", path, 1, f"{where}: path / relation 必填（当前: {entry}）",
            ))
            continue
        if relation not in POINTER_RELATION_TO_STATUS:
            findings.append(Finding(
                "blocking", path, 1,
                f"{where}: relation 非法: {relation!r}"
                f"（允许: {' / '.join(sorted(POINTER_RELATION_TO_STATUS))}）",
            ))
            continue
        report.agent_map_pointed.add(rel)
        target = root / rel
        if not target.exists():
            findings.append(Finding(
                "blocking", path, 1, f"{where}: 断链，path 指向不存在的文件: {rel}",
            ))
            continue
        status = read_frontmatter_status(target)
        expected = POINTER_RELATION_TO_STATUS[relation]
        if status is not None and status != expected:
            findings.append(Finding(
                "blocking", path, 1,
                f"{where}: 与 frontmatter 状态冲突（第二套口径）: {rel} 的 frontmatter "
                f"status={status}，map 标 relation={relation}——以 frontmatter 为准修 map",
            ))
        by = entry.get("by")
        if by and not (root / by).exists():
            findings.append(Finding("blocking", path, 1, f"{where}: by 断链: {by}"))


def crosscheck_terminal_registration(report: LintReport) -> None:
    """反向核对：终态产物应登记进 agent-map pointers（提示级）。

    仅在本次运行扫到 agent-map 时执法（map 是可选产物，不存在即跳过）；
    判定范围以本次扫描到的产物为界。
    """
    if report.agent_map_pointed is None or report.agent_map_path is None:
        return
    for rel, status in report.terminal_artifacts:
        if rel not in report.agent_map_pointed:
            report.findings.append(Finding(
                "advisory", report.agent_map_path, 1,
                f"终态产物未在 pointers 登记（导航滞后）: {rel}（status={status}）",
            ))


# ===== 文件收集与主流程 =====


def collect_files(paths: list[Path]) -> list[Path]:
    """按目录扫描规则收集待校验文件。"""
    collected: list[Path] = []

    def consider(p: Path) -> None:
        if not p.is_file():
            return
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        suffix = p.suffix.lower()
        if suffix == ".md":
            in_spec_dir = any(
                part in {"spec", "adr"} for part in p.parts if part != "docs"
            ) and "docs" in p.parts
            if FRONTMATTER_RE.match(text) or in_spec_dir:
                collected.append(p)
        elif suffix in {".yaml", ".yml"}:
            if p.name in {REGISTRY_NAME, AGENT_MAP_NAME} or RAW_CONTRACT_KEY_RE.search(text):
                collected.append(p)
        elif suffix == ".json" and "json-schema.org" in text:
            collected.append(p)
        elif suffix == ".sql" and SQL_CONTRACT_RE.search(text):
            collected.append(p)

    for base in paths:
        if base.is_file():
            collected.append(base)
        elif base.is_dir():
            for p in sorted(base.rglob("*")):
                consider(p)
    # 去重保持顺序
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in collected:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def lint_file(path: Path, root: Path, report: LintReport) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        report.findings.append(Finding("blocking", path, 1, f"读取失败: {e}"))
        return

    if path.name == REGISTRY_NAME:
        report.files_checked += 1
        lint_registry(path, root, report)
        return

    if path.name == AGENT_MAP_NAME:
        report.files_checked += 1
        lint_agent_map(path, root, report)
        return

    parsed = parse_frontmatter(text)
    fm = parsed[0] if parsed else None
    fm_end_line = parsed[1] if parsed else 1
    ptype = detect_product_type(path, text, fm)

    if ptype is None:
        if path.suffix == ".sql":
            report.findings.append(Finding(
                "blocking", path, 1,
                "缺少契约注释头（-- contract: data-model / version / compat-policy，"
                "见 references/frontmatter.md 形态 C）",
            ))
        else:
            report.findings.append(Finding(
                "blocking", path, 1,
                "缺少 frontmatter 或 type 字段（允许: spec / adr / contract / design-doc）",
            ))
        return

    report.files_checked += 1

    if ptype == "contract-raw":
        lint_contract_raw(path, text, report.findings)
        return

    assert fm is not None
    lint_common(path, fm, ptype, report.findings)
    lint_changelog_section(path, fm, text, report.findings)
    lint_path_fields(path, fm, root, report.findings)
    lint_md_links(path, text, fm_end_line, report.findings)
    lint_body_status_conflict(path, fm, text, fm_end_line, report.findings)
    lint_temporal_purity(path, text, fm_end_line, report.findings)

    # 终态产物登记（供 agent-map 反向核对，见 crosscheck_terminal_registration）
    if fm.get("status") in TERMINAL_STATUS:
        report.terminal_artifacts.append((_relative_to_root(path, root), fm["status"]))


def _relative_to_root(path: Path, root: Path) -> str:
    """相对仓库根的 POSIX 路径；不在 root 下时退化为原路径。"""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ===== 派生索引（--list-artifacts）=====


@dataclass
class ArtifactInfo:
    """单条产物索引项（派生物，不入库、不维护）。"""

    path: str
    type: str
    status: str
    layer: str = ""
    supersedes: str = ""
    superseded_by: str = ""
    extra: str = ""  # 原型 write-back 等补充信息


def collect_inventory(files: list[Path], root: Path) -> list[ArtifactInfo]:
    """从扫描到的产物派生全量索引：frontmatter 产物 + 登记表产物。"""
    items: list[ArtifactInfo] = []
    for path in files:
        rel = _relative_to_root(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.name == AGENT_MAP_NAME:
            continue  # 导航文件，不是产物
        if path.name == REGISTRY_NAME:
            items.extend(_inventory_from_registry(text))
            continue
        parsed = parse_frontmatter(text)
        fm = parsed[0] if parsed else None
        ptype = detect_product_type(path, text, fm)
        if ptype == "contract-raw":
            items.append(ArtifactInfo(rel, "contract", "(raw)"))
        elif ptype is not None and fm is not None:
            items.append(ArtifactInfo(
                rel, ptype, fm.get("status", "?"),
                layer=fm.get("layer", ""),
                supersedes=fm.get("supersedes", ""),
                superseded_by=fm.get("superseded-by", ""),
            ))
    return items


def _inventory_from_registry(text: str) -> list[ArtifactInfo]:
    """登记表（design-registry.yaml）条目转索引项；yaml 不可用/解析失败时降级为空。"""
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except Exception:
        return []
    items: list[ArtifactInfo] = []
    for entry in (data or {}).get("artifacts") or []:
        if not isinstance(entry, dict):
            continue
        write_back = entry.get("write-back") or ""
        items.append(ArtifactInfo(
            str(entry.get("path", "?")), str(entry.get("type", "?")),
            str(entry.get("status", "?")),
            extra=f"write-back: {write_back}" if write_back else "",
        ))
    return items


def format_inventory_text(items: list[ArtifactInfo]) -> str:
    lines = [f"设计层产物索引（派生自 frontmatter 与登记表，共 {len(items)} 项）", ""]
    for it in items:
        layer = f" [{it.layer}]" if it.layer else ""
        extra = f"  {it.extra}" if it.extra else ""
        lines.append(f"{it.type:<12} {it.status:<14} {it.path}{layer}{extra}")
    return "\n".join(lines)


def format_inventory_json(items: list[ArtifactInfo]) -> str:
    return json.dumps(
        {"artifacts": [
            {
                "path": it.path, "type": it.type, "status": it.status,
                "layer": it.layer, "supersedes": it.supersedes,
                "superseded_by": it.superseded_by, "extra": it.extra,
            }
            for it in items
        ]},
        ensure_ascii=False,
        indent=2,
    )


# ===== 输出 =====


def format_text_report(report: LintReport) -> str:
    lines: list[str] = [f"校验文件 {report.files_checked} 个", ""]
    if not report.findings:
        lines.append("✓ 校验通过：frontmatter、断链、时态纯净度均无问题。")
        return "\n".join(lines)

    blocking = report.blocking()
    advisory = report.advisory()
    if blocking:
        lines.append(f"✗ 阻断级问题 {len(blocking)} 个：")
        for f in blocking:
            lines.append(f"  - {f.file}:{f.line} {f.message}")
        lines.append("")
    if advisory:
        lines.append(f"⚠ 提示级问题 {len(advisory)} 个（需显式裁定，不阻断）：")
        for f in advisory:
            lines.append(f"  - {f.file}:{f.line} {f.message}")
        lines.append("")
    if blocking:
        lines.append("裁定指引：阻断级未清零前产物不得视为已收口。字段规范见 references/frontmatter.md。")
    return "\n".join(lines)


def format_json_report(report: LintReport) -> str:
    return json.dumps(
        {
            "files_checked": report.files_checked,
            "has_blocking": report.has_blocking,
            "blocking": [
                {"file": str(f.file), "line": f.line, "message": f.message}
                for f in report.blocking()
            ],
            "advisory": [
                {"file": str(f.file), "line": f.line, "message": f.message}
                for f in report.advisory()
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


# ===== 主入口 =====


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验设计层产物（spec/ADR/契约文档）的 frontmatter、断链与时态纯净度"
    )
    parser.add_argument("paths", nargs="+", help="产物文件或目录（可多个）")
    parser.add_argument(
        "--root", default=".",
        help="仓库根目录，用于解析 frontmatter 路径字段（默认当前目录）",
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="输出格式（默认 text）",
    )
    parser.add_argument(
        "--list-artifacts", action="store_true",
        help="只输出扫描范围内全部设计产物的派生索引（type/status/path/取代链），不做 lint 校验",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths]
    for p in paths:
        if not p.exists():
            print(f"路径不存在: {p}")
            return 2
    root = Path(args.root).resolve()

    files = collect_files(paths)
    if not files:
        print("未扫描到任何设计层产物（扫描规则见 docstring）")
        return 2

    if args.list_artifacts:
        items = collect_inventory(files, root)
        print(format_inventory_json(items) if args.format == "json" else format_inventory_text(items))
        return 0

    report = LintReport()
    for f in files:
        lint_file(f, root, report)
    crosscheck_terminal_registration(report)

    if args.format == "json":
        print(format_json_report(report))
    else:
        print(format_text_report(report))

    return 1 if report.has_blocking else 0


if __name__ == "__main__":
    sys.exit(main())
