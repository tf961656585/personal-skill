#!/usr/bin/env python3
"""
Spec 验收项 ↔ 测试用例双向追溯校验器。

校验 spec 中声明的验收项与测试目录中的 @spec 标注是否双向一致，
发现三类漂移：缺失测试、孤儿测试、未标注测试。

扫描规则与漂移分类详见 references/consistency-checks.md。

用法:
    python3 trace_acceptance.py --spec <spec 文件> --tests <测试目录>
    python3 trace_acceptance.py --spec <spec 文件> --tests <测试目录> --format json
    python3 trace_acceptance.py --spec <spec 文件> --tests <测试目录> --tests <测试目录 2>   # 多目录合并扫描

退出码:
    0  无阻断级漂移（仅有未标注测试或完全通过）
    1  存在缺失测试或孤儿测试（阻断级漂移）
    2  输入错误（文件/目录不存在、未找到任何内容）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ===== 正则约定（与 references/consistency-checks.md 对齐）=====

# 验收项 ID：#### 验收：<ID>  或  #### 验收: <ID>
# ID 形如 PAY-001、AUTH-002（域缩写-序号），兼容字母数字
# ID 后允许带描述（#### 验收：PAY-001 创建订单成功）或直接行尾
ACCEPTANCE_HEADER_RE = re.compile(
    r"^#{1,6}\s*验收\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]*)(?:\s|$)",
    re.MULTILINE,
)

# 行内 EARS + ID 标记：验收：<ID> ... WHEN/WHILE/IF/WHERE ... SHALL
# 用于扫描 EARS 格式验收项，要求附近有 ID 标记
EARS_BLOCK_RE = re.compile(
    r"验收\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]*)(?:\s|$)"
    r"[\s\S]{0,200}?"
    r"\b(?:WHEN|WHILE|IF|WHERE)\b[\s\S]{0,300}?\bSHALL\b",
)

# 测试侧标注：@spec: ID, ID  —— 只取同行内容，不跨行
# 多个 ID 与代码符号（引号/括号/注释符）在后续 split 时清洗
SPEC_TAG_RE = re.compile(
    r"@spec\s*[:：][ \t]*([^\n]*)",
    re.IGNORECASE,
)

# 严格 ID token 校验（清洗 split 后的候选项）
ID_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# 标注提取时的分隔符：逗号、空白、引号、括号、注释符等代码符号
ANNOTATION_SPLIT_RE = re.compile(r"[,\s\"'`(){}\[\];]+")

# 测试文件后缀（常见语言）
TEST_FILE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cts",
    ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".swift", ".m", ".cs", ".scala",
}

# 测试文件名特征（无后缀匹配时补充判断）
TEST_NAME_HINTS = ("test", "spec", "_test", ".test", ".spec")


# ===== 数据结构 =====


@dataclass
class AcceptanceItem:
    """spec 中的验收项。"""

    id: str
    line: int
    context: str  # 标题或上下文片段


@dataclass
class TestAnnotation:
    """测试文件中的 @spec 标注。"""

    file: Path
    line: int
    ids: list[str]


@dataclass
class DriftReport:
    """漂移报告。"""

    missing_tests: list[tuple[AcceptanceItem, None]] = field(default_factory=list)
    orphan_tests: list[tuple[str, TestAnnotation]] = field(default_factory=list)
    unannotated_tests: list[Path] = field(default_factory=list)
    unnumbered_acceptances: list[tuple[int, str]] = field(default_factory=list)
    spec_acceptances: list[AcceptanceItem] = field(default_factory=list)
    test_annotations: list[TestAnnotation] = field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return bool(self.missing_tests or self.orphan_tests)


# ===== 扫描函数 =====


def scan_acceptances(text: str) -> tuple[list[AcceptanceItem], list[tuple[int, str]]]:
    """扫描 spec 文本，提取验收项。

    返回 (编号验收项列表, 未编号验收项列表[(行号, 上下文)])。
    """
    items: list[AcceptanceItem] = []
    seen_ids: set[str] = set()
    unnumbered: list[tuple[int, str]] = []

    lines = text.splitlines()

    # 扫描 #### 验收：<ID> 格式
    for match in ACCEPTANCE_HEADER_RE.finditer(text):
        item_id = match.group(1).strip()
        line_no = text[: match.start()].count("\n") + 1
        context = lines[line_no - 1].strip() if line_no - 1 < len(lines) else item_id
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        items.append(AcceptanceItem(id=item_id, line=line_no, context=context))

    # 扫描 EARS 格式（验收：<ID> ... WHEN/WHILE/IF/WHERE ... SHALL）
    for match in EARS_BLOCK_RE.finditer(text):
        item_id = match.group(1).strip()
        line_no = text[: match.start()].count("\n") + 1
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        context = lines[line_no - 1].strip() if line_no - 1 < len(lines) else item_id
        items.append(AcceptanceItem(id=item_id, line=line_no, context=context))

    # 检测未编号验收项：标题含"验收"但无 ID
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if re.match(r"^#{1,6}\s*验收\s*[:：]?\s*$", stripped):
            unnumbered.append((i, stripped))
        elif re.match(r"^#{1,6}\s*验收\s*[:：]\s*$", stripped):
            unnumbered.append((i, stripped))

    return items, unnumbered


def is_test_file(path: Path) -> bool:
    """判断文件是否为测试文件。"""
    if path.suffix in TEST_FILE_SUFFIXES:
        name_lower = path.stem.lower()
        return any(hint in name_lower for hint in TEST_NAME_HINTS) or path.suffix == ".py"
    return False


def scan_test_annotations(tests_dir: Path) -> tuple[list[TestAnnotation], list[Path]]:
    """扫描测试目录，提取 @spec 标注。

    返回 (标注列表, 未标注测试文件列表)。
    """
    annotations: list[TestAnnotation] = []
    unannotated: list[Path] = []

    test_files = sorted(
        p for p in tests_dir.rglob("*") if p.is_file() and is_test_file(p)
    )

    for file_path in test_files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        file_has_annotation = False
        for match in SPEC_TAG_RE.finditer(text):
            raw_ids = match.group(1)
            # 按分隔符（含引号/括号等代码符号）拆分，严格校验每个 token 是否合法 ID
            ids = [
                tok
                for tok in ANNOTATION_SPLIT_RE.split(raw_ids.strip())
                if tok and ID_TOKEN_RE.match(tok)
            ]
            if not ids:
                continue
            line_no = text[: match.start()].count("\n") + 1
            annotations.append(
                TestAnnotation(file=file_path, line=line_no, ids=ids)
            )
            file_has_annotation = True

        if not file_has_annotation:
            unannotated.append(file_path)

    return annotations, unannotated


# ===== 漂移检测 =====


def detect_drift(
    acceptances: list[AcceptanceItem],
    annotations: list[TestAnnotation],
) -> dict[str, set[str]]:
    """构建 ID 映射，返回 {acceptance_ids, annotated_ids}。"""
    acceptance_ids = {item.id for item in acceptances}
    annotated_ids: set[str] = set()
    for ann in annotations:
        annotated_ids.update(ann.ids)
    return {"acceptance_ids": acceptance_ids, "annotated_ids": annotated_ids}


def build_report(
    acceptances: list[AcceptanceItem],
    annotations: list[TestAnnotation],
    unannotated: list[Path],
    unnumbered: list[tuple[int, str]],
) -> DriftReport:
    """构建完整漂移报告。"""
    report = DriftReport()
    report.spec_acceptances = acceptances
    report.test_annotations = annotations
    report.unannotated_tests = unannotated
    report.unnumbered_acceptances = unnumbered

    maps = detect_drift(acceptances, annotations)
    acceptance_ids = maps["acceptance_ids"]
    annotated_ids = maps["annotated_ids"]

    # 缺失测试：spec 有、测试无
    for item in acceptances:
        if item.id not in annotated_ids:
            report.missing_tests.append((item, None))

    # 孤儿测试：测试有、spec 无
    for ann in annotations:
        for test_id in ann.ids:
            if test_id not in acceptance_ids:
                report.orphan_tests.append((test_id, ann))

    return report


# ===== 输出 =====


def format_text_report(report: DriftReport, spec_path: Path, tests_dirs: list[Path]) -> str:
    """人类可读的文本报告。"""
    lines: list[str] = []
    lines.append(f"Spec: {spec_path}")
    lines.append("测试目录: " + ", ".join(str(d) for d in tests_dirs))
    lines.append(
        f"验收项 {len(report.spec_acceptances)} 个 | "
        f"测试标注 {len(report.test_annotations)} 处 | "
        f"测试文件 {len(report.unannotated_tests) + sum(1 for _ in report.test_annotations)} 个"
    )
    total = len(report.spec_acceptances)
    if total:
        covered = total - len(report.missing_tests)
        lines.append(
            f"覆盖率（代理读数）: {covered}/{total} 个验收项有测试标注——"
            "未覆盖 ≠ 未实现，有测试 ≈ 已实现；实现状态的权威口径以代码为准"
        )
    lines.append("")

    if not report.has_blocking and not report.unnumbered_acceptances:
        if report.unannotated_tests:
            lines.append("✓ 无阻断级漂移。")
            lines.append("")
            lines.append(
                f"提示: {len(report.unannotated_tests)} 个测试文件无 @spec 标注（提示级，不阻断）："
            )
            for p in report.unannotated_tests[:20]:
                lines.append(f"  - {p}")
            if len(report.unannotated_tests) > 20:
                lines.append(f"  ... 共 {len(report.unannotated_tests)} 个")
        else:
            lines.append("✓ 校验通过：验收项与测试标注双向一致。")
        return "\n".join(lines)

    if report.missing_tests:
        lines.append(f"✗ 缺失测试（阻断级）：{len(report.missing_tests)} 个验收项无测试覆盖")
        for item, _ in report.missing_tests:
            lines.append(f"  - {item.id} (spec 第 {item.line} 行): {item.context}")
        lines.append("")

    if report.orphan_tests:
        lines.append(
            f"✗ 孤儿测试（阻断级）：{len(report.orphan_tests)} 个标注指向不存在的验收项"
        )
        for test_id, ann in report.orphan_tests:
            lines.append(
                f"  - {test_id} (测试 {ann.file}:{ann.line})"
            )
        lines.append("")

    if report.unnumbered_acceptances:
        lines.append(
            f"⚠ 未编号验收项（提示级）：{len(report.unnumbered_acceptances)} 个"
        )
        for line_no, ctx in report.unnumbered_acceptances:
            lines.append(f"  - spec 第 {line_no} 行: {ctx}")
        lines.append("")

    if report.unannotated_tests:
        lines.append(
            f"提示: {len(report.unannotated_tests)} 个测试文件无 @spec 标注（提示级）"
        )
        for p in report.unannotated_tests[:10]:
            lines.append(f"  - {p}")
        if len(report.unannotated_tests) > 10:
            lines.append(f"  ... 共 {len(report.unannotated_tests)} 个")
        lines.append("")

    lines.append("裁定指引：缺失/孤儿为阻断级，必须裁定（补测试 / 改 spec / 修标注）。")
    lines.append("详见 references/consistency-checks.md「漂移裁定流程」。")
    return "\n".join(lines)


def format_json_report(report: DriftReport, spec_path: Path, tests_dirs: list[Path]) -> str:
    """JSON 格式报告（供 CI / 工具消费）。"""
    return json.dumps(
        {
            "spec": str(spec_path),
            "tests_dir": ", ".join(str(d) for d in tests_dirs),
            "summary": {
                "acceptances": len(report.spec_acceptances),
                "annotations": len(report.test_annotations),
                "covered_acceptances": len(report.spec_acceptances) - len(report.missing_tests),
                "missing_tests": len(report.missing_tests),
                "orphan_tests": len(report.orphan_tests),
                "unannotated_tests": len(report.unannotated_tests),
                "unnumbered_acceptances": len(report.unnumbered_acceptances),
                "has_blocking": report.has_blocking,
            },
            "missing_tests": [
                {"id": item.id, "line": item.line, "context": item.context}
                for item, _ in report.missing_tests
            ],
            "orphan_tests": [
                {"id": test_id, "file": str(ann.file), "line": ann.line}
                for test_id, ann in report.orphan_tests
            ],
            "unannotated_tests": [str(p) for p in report.unannotated_tests],
            "unnumbered_acceptances": [
                {"line": line_no, "context": ctx}
                for line_no, ctx in report.unnumbered_acceptances
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


# ===== 主入口 =====


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验 spec 验收项与测试用例的双向追溯一致性"
    )
    parser.add_argument("--spec", required=True, help="spec 文件路径（.md）")
    parser.add_argument(
        "--tests",
        required=True,
        action="append",
        help="测试目录路径（可重复传参扫描多个目录）",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text）",
    )
    args = parser.parse_args()

    spec_path = Path(args.spec)
    tests_dirs = [Path(t) for t in args.tests]

    if not spec_path.exists():
        print(f"spec 文件不存在: {spec_path}")
        return 2
    for tests_dir in tests_dirs:
        if not tests_dir.exists() or not tests_dir.is_dir():
            print(f"测试目录不存在或不是目录: {tests_dir}")
            return 2

    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"读取 spec 失败: {e}")
        return 2

    acceptances, unnumbered = scan_acceptances(spec_text)
    annotations: list[TestAnnotation] = []
    unannotated: list[Path] = []
    for tests_dir in tests_dirs:
        dir_annotations, dir_unannotated = scan_test_annotations(tests_dir)
        annotations.extend(dir_annotations)
        unannotated.extend(dir_unannotated)

    report = build_report(acceptances, annotations, unannotated, unnumbered)

    if args.format == "json":
        print(format_json_report(report, spec_path, tests_dirs))
    else:
        print(format_text_report(report, spec_path, tests_dirs))

    return 1 if report.has_blocking else 0


if __name__ == "__main__":
    sys.exit(main())
