#!/usr/bin/env python3
"""测试↔spec 关联与测试活性全仓审计器（test-linkage skill 参考实现）。

规则语义唯一事实源：references/linkage-spec.md（R1/R2/R4/R5/R6/R10）。
ID 与标注格式约定同源 spec-guide references/consistency-checks.md，
正则与 spec-guide scripts/trace_acceptance.py 保持兼容。

用法:
    python3 check_test_linkage.py --root <仓库根> [--config <config.json>]
    python3 check_test_linkage.py --root . --format json
    python3 check_test_linkage.py --root . --retired-spec docs/foo.md   # 退役点名：列出该 spec 验收 ID 的全部测试引用者

退出码:
    0  无 error 级违规
    1  存在 error 级违规（R1/R2；seam mock 为 error 档时含 R10）
    2  输入错误
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ===== 正则（与 spec-guide trace_acceptance.py 兼容，勿单方改动）=====

ACCEPTANCE_HEADER_RE = re.compile(
    r"^#{1,6}\s*验收\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]*)(?:\s|$)",
    re.MULTILINE,
)
# 显式废弃形态：#### 废弃：<ID>（ID 保留原文、语义不再验收，linkage-spec §1）
DEPRECATED_HEADER_RE = re.compile(
    r"^#{1,6}\s*废弃\s*[:：]\s*([A-Za-z][A-Za-z0-9_-]*)(?:\s|$)",
    re.MULTILINE,
)
SPEC_TAG_RE = re.compile(r"@spec\s*[:：][ \t]*([^\n]*)", re.IGNORECASE)
ID_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
ANNOTATION_SPLIT_RE = re.compile(r"[,\s\"'`(){}\[\];]+")
SKIP_AUDIT_RE = re.compile(r"\b(?:describe|it|test)\s*\.\s*(?:skip|todo|fails)\b")

DEFAULT_CONFIG: dict = {
    "docs": {
        "dirs": ["docs"],
        "excludeDirNames": ["archive", "temp"],
        "specTypes": ["spec", "contract"],
        "activeStatuses": ["Active"],
        "terminalStatuses": ["Superseded", "Deprecated", "Archived"],
    },
    "tests": {
        "suffixes": [
            ".test.ts", ".test.tsx", ".test.mts", ".test.mjs",
            ".test.jsx", ".spec.ts", ".spec.tsx", ".spec.mts", ".spec.jsx",
        ],
        "excludeGlobs": [
            "**/node_modules/**", "**/dist/**", "**/dist-static/**",
            "**/.publish/**", "**/coverage/**", "**/build/**",
        ],
    },
    "entryGlobs": [],
    "seam": {
        "fileNamePattern": "seam",
        "detect": ["vi.mock(", "vi.doMock(", "jest.mock("],
        "exemptMarker": "guard-seam-mock-exempt",
        "level": "warning",
    },
    "annotationTag": "@spec:",
}


@dataclass
class SpecFile:
    path: Path
    type: str
    status: str
    acceptance: dict[str, int] = field(default_factory=dict)  # id -> line
    deprecated: dict[str, int] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass
class TestAnnotation:
    file: Path
    line: int
    ids: list[str]


ACTIVE_STATUSES: set[str] = set()
TERMINAL_STATUSES: set[str] = set()


def merge_config(overrides: dict) -> dict:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def parse_frontmatter(text: str) -> tuple[str, str]:
    """行级解析首个 --- 块内的 type:/status: 扁平标量（不引 YAML 库）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", ""
    doc_type = status = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        match = re.match(r"^(type|status):\s*(.+?)\s*$", stripped)
        if match:
            if match.group(1) == "type":
                doc_type = match.group(2)
            else:
                status = match.group(2)
    return doc_type, status


def scan_spec_file(path: Path) -> SpecFile:
    text = path.read_text(encoding="utf-8", errors="replace")
    doc_type, status = parse_frontmatter(text)
    spec = SpecFile(path=path, type=doc_type, status=status)
    for match in ACCEPTANCE_HEADER_RE.finditer(text):
        item_id = match.group(1)
        line_no = text[: match.start()].count("\n") + 1
        spec.acceptance.setdefault(item_id, line_no)
    for match in DEPRECATED_HEADER_RE.finditer(text):
        item_id = match.group(1)
        line_no = text[: match.start()].count("\n") + 1
        spec.deprecated.setdefault(item_id, line_no)
    return spec


def glob_to_regex(pattern: str) -> re.Pattern:
    """glob→regex，对齐 node glob 语义：`**/` 匹配零或多层目录，`*` 不跨 /。

    fnmatch 的 `**/` 不匹配零目录层（`src/**/__tests__/` 接不住 `src/__tests__/`），
    直接用 fnmatch 会把顶层测试目录整体误判为孤儿，故自译。
    """
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append(r"(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(r".*")
            index += 2
        elif pattern[index] == "*":
            parts.append(r"[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append(r"[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts) + r"\Z")


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_match(rel_posix: str, pattern: str) -> bool:
    regex = _GLOB_CACHE.get(pattern)
    if regex is None:
        regex = glob_to_regex(pattern)
        _GLOB_CACHE[pattern] = regex
    return regex.match(rel_posix) is not None


PRUNE_DIR_NAMES = {".git", "node_modules", "dist", "dist-static", ".publish", "coverage", "build"}


def iter_repo_files(root: Path):
    """全仓遍历，剪枝纯产物/依赖目录（fnmatch 的 * 跨 /，剪枝只为提速）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIR_NAMES]
        for name in filenames:
            yield Path(dirpath) / name


def find_test_files(root: Path, cfg: dict) -> list[Path]:
    suffixes = tuple(cfg["tests"]["suffixes"])
    exclude_globs = cfg["tests"]["excludeGlobs"]
    files: list[Path] = []
    for path in iter_repo_files(root):
        if not path.name.endswith(suffixes):
            continue
        rel = path.relative_to(root).as_posix()
        if any(glob_match(rel, pattern) for pattern in exclude_globs):
            continue
        files.append(path)
    return sorted(files)


def scan_test_file(path: Path, root: Path) -> tuple[list[TestAnnotation], list[tuple[int, str]]]:
    """返回 (@spec 标注列表, skip 命中行列表)。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    annotations: list[TestAnnotation] = []
    skips: list[tuple[int, str]] = []
    for match in SPEC_TAG_RE.finditer(text):
        raw = match.group(1)
        ids = [
            token
            for token in ANNOTATION_SPLIT_RE.split(raw.strip())
            if token and ID_TOKEN_RE.match(token)
        ]
        if not ids:
            continue
        line_no = text[: match.start()].count("\n") + 1
        annotations.append(TestAnnotation(file=path, line=line_no, ids=ids))
    for i, line in enumerate(text.splitlines(), start=1):
        if SKIP_AUDIT_RE.search(line):
            skips.append((i, line.strip()))
    return annotations, skips


def scan_seam_mocks(
    path: Path, cfg: dict
) -> list[tuple[int, str]]:
    """seam 文件内的模块级 mock 命中（豁免标记与注释行不算违规）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    detect = tuple(cfg["seam"]["detect"])
    marker = cfg["seam"]["exemptMarker"]
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        if not any(detect_str in line for detect_str in detect):
            continue
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        window = "\n".join(lines[max(0, i - 3): i])
        if marker in window:
            continue
        violations.append((i, stripped))
    return violations


# ===== 主流程 =====


def audit(root: Path, cfg: dict) -> dict:
    docs_cfg = cfg["docs"]
    global ACTIVE_STATUSES, TERMINAL_STATUSES
    ACTIVE_STATUSES = set(docs_cfg["activeStatuses"])
    TERMINAL_STATUSES = set(docs_cfg["terminalStatuses"])

    spec_files: list[SpecFile] = []
    for docs_dir in docs_cfg["dirs"]:
        base = root / docs_dir
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if any(part in docs_cfg["excludeDirNames"] for part in path.relative_to(root).parts[:-1]):
                continue
            spec_files.append(scan_spec_file(path))

    eligible = [s for s in spec_files if s.type in docs_cfg["specTypes"]]
    active_specs = [s for s in eligible if s.is_active]
    terminal_specs = [s for s in eligible if s.is_terminal]
    active_ids: dict[str, SpecFile] = {}
    for spec in active_specs:
        for item_id in spec.acceptance:
            active_ids.setdefault(item_id, spec)
    all_ids: dict[str, list[SpecFile]] = {}
    for spec in eligible:
        for item_id in list(spec.acceptance) + list(spec.deprecated):
            all_ids.setdefault(item_id, []).append(spec)
    deprecated_ids: dict[str, SpecFile] = {}
    for spec in eligible:
        for item_id in spec.deprecated:
            deprecated_ids.setdefault(item_id, spec)

    test_files = find_test_files(root, cfg)
    annotations: list[TestAnnotation] = []
    unannotated: list[Path] = []
    skip_hits: list[tuple[Path, int, str]] = []
    annotated_files: set[Path] = set()
    for path in test_files:
        file_annotations, file_skips = scan_test_file(path, root)
        skip_hits.extend((path, line, text) for line, text in file_skips)
        if file_annotations:
            annotations.extend(file_annotations)
            annotated_files.add(path)
        else:
            unannotated.append(path)

    # R1 引用闭包
    r1_violations: list[dict] = []
    for ann in annotations:
        for item_id in ann.ids:
            if item_id in deprecated_ids:
                owner = deprecated_ids[item_id]
                r1_violations.append({
                    "kind": "deprecated", "id": item_id,
                    "file": str(ann.file.relative_to(root)), "line": ann.line,
                    "spec": str(owner.path.relative_to(root)), "specLine": owner.deprecated[item_id],
                    "hint": "验收项已显式废弃（语义翻转/裁断废弃）——按新口径改写断言并改标新 ID，或删测试",
                })
            elif item_id not in active_ids:
                owners = all_ids.get(item_id, [])
                terminal_owners = [s for s in owners if s.is_terminal]
                if terminal_owners:
                    owner = terminal_owners[0]
                    r1_violations.append({
                        "kind": "retired", "id": item_id,
                        "file": str(ann.file.relative_to(root)), "line": ann.line,
                        "spec": str(owner.path.relative_to(root)), "specLine": owner.acceptance.get(item_id, 0),
                        "hint": f"验收项所属 spec status={owner.status}（已退役）——查取代 spec 的新 ID 或删测试",
                    })
                else:
                    r1_violations.append({
                        "kind": "undefined", "id": item_id,
                        "file": str(ann.file.relative_to(root)), "line": ann.line,
                        "spec": "", "specLine": 0,
                        "hint": "ID 全仓未定义（拼写错误或验收项从未存在）——修标注或补 spec 验收项",
                    })

    # R2 ID 唯一性
    r2_errors: list[dict] = []
    r2_warnings: list[dict] = []
    for item_id, specs in all_ids.items():
        active_owners = [s for s in specs if s.is_active]
        if len(active_owners) > 1:
            r2_errors.append({
                "id": item_id,
                "files": [str(s.path.relative_to(root)) for s in active_owners],
            })
        elif len(specs) > len(active_owners):
            r2_warnings.append({
                "id": item_id,
                "files": [str(s.path.relative_to(root)) for s in specs],
                "hint": "终态产物与 Active 产物 ID 重号——编号复用嫌疑，核对 consistency-checks §二",
            })

    # R4 运行入口覆盖
    r4_orphans: list[str] = []
    entry_globs = cfg.get("entryGlobs", [])
    if entry_globs:
        for path in test_files:
            rel = path.relative_to(root).as_posix()
            if not any(glob_match(rel, pattern) for pattern in entry_globs):
                r4_orphans.append(rel)

    # R5 skip 审计
    # skip_hits 已收集

    # R10 seam mock
    seam_cfg = cfg["seam"]
    seam_level = seam_cfg.get("level", "warning")
    r10_violations: list[dict] = []
    seam_pattern = seam_cfg["fileNamePattern"].lower()
    for path in test_files:
        if seam_pattern not in path.name.lower():
            continue
        for line, text in scan_seam_mocks(path, cfg):
            r10_violations.append({
                "file": str(path.relative_to(root)), "line": line, "text": text,
                "hint": "seam 文件内模块级 mock——合法边界替身/副作用隔离打豁免标记，桩被测链路则重构",
            })

    # R6 覆盖读数
    annotated_id_set: set[str] = set()
    for ann in annotations:
        annotated_id_set.update(ann.ids)
    covered = sum(1 for item_id in active_ids if item_id in annotated_id_set)

    return {
        "specFiles": spec_files,
        "activeCount": len(active_ids),
        "covered": covered,
        "r1": r1_violations,
        "r2Errors": r2_errors,
        "r2Warnings": r2_warnings,
        "r4": r4_orphans,
        "r5": [{"file": str(p.relative_to(root)), "line": line, "text": text} for p, line, text in skip_hits],
        "r10": r10_violations,
        "r10Level": seam_level,
        "unannotatedCount": len(unannotated),
        "testFileCount": len(test_files),
        "annotationCount": len(annotations),
    }


def format_text(root: Path, report: dict, cfg: dict) -> str:
    lines: list[str] = []
    lines.append(f"root: {root}")
    lines.append(
        f"Active 验收 ID {report['activeCount']} 个 | 测试标注 {report['annotationCount']} 处 / "
        f"测试文件 {report['testFileCount']} 个 | 有标注覆盖 {report['covered']} 个验收 ID "
        f"(代理读数，未覆盖 ≠ 未实现) | 无标注测试文件 {report['unannotatedCount']} 个"
    )
    lines.append("")

    has_error = bool(report["r1"] or report["r2Errors"]) or (
        report["r10Level"] == "error" and report["r10"]
    )

    if report["r1"]:
        lines.append(f"✗ R1 引用闭包（阻断级）：{len(report['r1'])} 处标注指向无效验收 ID")
        for v in report["r1"]:
            kind_label = {"deprecated": "已废弃", "retired": "已随 spec 退役", "undefined": "未定义"}[v["kind"]]
            spec_ref = f" (见 {v['spec']}:{v['specLine']})" if v["spec"] else ""
            lines.append(f"  - [{kind_label}] {v['id']} ← {v['file']}:{v['line']}{spec_ref}")
            lines.append(f"      {v['hint']}")
        lines.append("")

    if report["r2Errors"]:
        lines.append(f"✗ R2 ID 重复定义（阻断级）：{len(report['r2Errors'])} 个")
        for v in report["r2Errors"]:
            lines.append(f"  - {v['id']} 定义于: {', '.join(v['files'])}")
        lines.append("")

    if report["r2Warnings"]:
        lines.append(f"⚠ R2 编号复用嫌疑（提示级）：{len(report['r2Warnings'])} 个")
        for v in report["r2Warnings"]:
            lines.append(f"  - {v['id']}: {', '.join(v['files'])}")
        lines.append("")

    if report["r10"]:
        level_label = "阻断级" if report["r10Level"] == "error" else "提示级"
        lines.append(f"{'✗' if report['r10Level'] == 'error' else '⚠'} R10 seam mock（{level_label}）：{len(report['r10'])} 处")
        for v in report["r10"]:
            lines.append(f"  - {v['file']}:{v['line']}  {v['text'][:100]}")
            lines.append(f"      {v['hint']}")
        lines.append("")

    if report["r4"] is not None and report["r4"]:
        lines.append(f"⚠ R4 孤儿测试文件（提示级）：{len(report['r4'])} 个不被任何运行入口覆盖")
        for rel in report["r4"][:20]:
            lines.append(f"  - {rel}")
        if len(report["r4"]) > 20:
            lines.append(f"  ... 共 {len(report['r4'])} 个")
        lines.append("")
    elif not cfg.get("entryGlobs"):
        lines.append("ℹ R4 跳过：未配置 entryGlobs 运行入口清单")
        lines.append("")

    if report["r5"]:
        lines.append(f"⚠ R5 skip 审计（提示级）：{len(report['r5'])} 处 skip/todo")
        for v in report["r5"][:15]:
            lines.append(f"  - {v['file']}:{v['line']}  {v['text'][:90]}")
        if len(report["r5"]) > 15:
            lines.append(f"  ... 共 {len(report['r5'])} 处")
        lines.append("")

    if not has_error:
        lines.append("✓ 无阻断级违规")
    return "\n".join(lines)


def format_json(root: Path, report: dict) -> str:
    payload = {key: value for key, value in report.items() if key != "specFiles"}
    payload["root"] = str(root)
    payload["hasError"] = bool(report["r1"] or report["r2Errors"]) or (
        report["r10Level"] == "error" and report["r10"]
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def list_retired_spec_references(root: Path, cfg: dict, spec_path: Path) -> int:
    """退役点名：列出给定 spec 全部验收 ID 的测试引用者（R3 显式工具）。"""
    if not spec_path.is_file():
        print(f"spec 文件不存在: {spec_path}")
        return 2
    spec = scan_spec_file(spec_path)
    if not spec.acceptance:
        print(f"该 spec 无验收 ID: {spec_path}")
        return 0
    test_files = find_test_files(root, cfg)
    references: dict[str, list[str]] = {item_id: [] for item_id in spec.acceptance}
    for path in test_files:
        file_annotations, _ = scan_test_file(path, root)
        for ann in file_annotations:
            for item_id in ann.ids:
                if item_id in references:
                    references[item_id].append(f"{path.relative_to(root).as_posix()}:{ann.line}")
    print(f"Spec: {spec_path} (status={spec.status or '无 frontmatter'})，验收 ID {len(references)} 个")
    for item_id, refs in references.items():
        if refs:
            print(f"  {item_id} ← {len(refs)} 处引用:")
            for ref in refs:
                print(f"    - {ref}")
        else:
            print(f"  {item_id} ← 无测试引用")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="测试↔spec 关联与测试活性全仓审计")
    parser.add_argument("--root", default=".", help="仓库根目录（默认当前目录）")
    parser.add_argument("--config", help="配置 JSON 路径（缺省用内置保守默认）")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--retired-spec", help="退役点名：列出该 spec 验收 ID 的全部测试引用者后退出")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"仓库根不存在: {root}")
        return 2

    cfg = dict(DEFAULT_CONFIG)
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_file():
            print(f"配置文件不存在: {config_path}")
            return 2
        cfg = merge_config(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        default_config = root / "test-linkage.config.json"
        if default_config.is_file():
            cfg = merge_config(json.loads(default_config.read_text(encoding="utf-8")))

    if args.retired_spec:
        return list_retired_spec_references(root, cfg, Path(args.retired_spec))

    report = audit(root, cfg)
    if args.format == "json":
        print(format_json(root, report))
    else:
        print(format_text(root, report, cfg))
    has_error = bool(report["r1"] or report["r2Errors"]) or (
        report["r10Level"] == "error" and report["r10"]
    )
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
