#!/usr/bin/env python3
"""
Mermaid 业务流程图基础校验器。
用于在流程图评审前做结构级门禁，避免明显的语义缺陷进入沟通环节。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FLOW_HEADER_RE = re.compile(r"^\s*(flowchart|graph)\s+\w+", re.IGNORECASE)
MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*(.*?)```", re.DOTALL | re.IGNORECASE)
NON_FLOW_TYPES_RE = re.compile(
    r"^\s*(sequencediagram|classDiagram|stateDiagram|erDiagram|journey|gantt)\b",
    re.IGNORECASE,
)
DECISION_NODE_RE = re.compile(r"\b([A-Za-z0-9_]+)\{[^}]+\}")
EDGE_FROM_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\b.*(?:-->|==>|-.->)")
EDGE_RE = re.compile(r"(-->|==>|-.->)")
SQUARE_NODE_LABEL_RE = re.compile(r"\b([A-Za-z0-9_]+)\[([^\]]+)\]")
DECISION_LABEL_RE = re.compile(r"\b([A-Za-z0-9_]+)\{([^}]+)\}")
RISKY_ASCII_PUNCTUATION = ":()[]{}|"


def _is_double_quoted(label: str) -> bool:
    stripped = label.strip()
    return len(stripped) >= 2 and stripped[0] == '"' and stripped[-1] == '"'


def _contains_risky_punctuation(label: str) -> bool:
    return any(ch in label for ch in RISKY_ASCII_PUNCTUATION)


def _build_quote_hint(node_id: str, shape: str, raw_label: str) -> str:
    stripped = raw_label.strip().replace('"', '\\"')
    if shape == "square":
        return f'{node_id}["{stripped}"]'
    return f'{node_id}{{"{stripped}"}}'


def _validate_label_quoting(lines: list[str]) -> list[str]:
    errors: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        # 忽略注释行
        if line.lstrip().startswith("%%"):
            continue

        for node_id, raw_label in SQUARE_NODE_LABEL_RE.findall(line):
            if _is_double_quoted(raw_label):
                continue
            if not _contains_risky_punctuation(raw_label):
                continue
            hint = _build_quote_hint(node_id, "square", raw_label)
            errors.append(
                f"第 {line_no} 行节点 {node_id} 的标签包含高风险标点 {RISKY_ASCII_PUNCTUATION}，"
                f"请使用双引号包裹标签，例如：{hint}"
            )

        for node_id, raw_label in DECISION_LABEL_RE.findall(line):
            if _is_double_quoted(raw_label):
                continue
            if not _contains_risky_punctuation(raw_label):
                continue
            hint = _build_quote_hint(node_id, "decision", raw_label)
            errors.append(
                f"第 {line_no} 行决策节点 {node_id} 的标签包含高风险标点 {RISKY_ASCII_PUNCTUATION}，"
                f"请使用双引号包裹标签，例如：{hint}"
            )
    return errors


def load_mermaid_text(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    match = MERMAID_BLOCK_RE.search(content)
    if match:
        return match.group(1).strip()
    return content.strip()


def validate_mermaid_text(text: str) -> list[str]:
    errors: list[str] = []
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ["Mermaid 内容为空。"]

    first = lines[0]
    if NON_FLOW_TYPES_RE.match(first):
        errors.append("仅允许 Mermaid flowchart/graph，当前是其他图类型。")
    if not FLOW_HEADER_RE.match(first):
        errors.append("第一行必须是 flowchart/graph 声明，例如：flowchart TD。")

    edge_count = sum(len(EDGE_RE.findall(line)) for line in lines)
    if edge_count == 0:
        errors.append("流程图缺少连线，至少需要一条箭头连接。")

    decision_nodes = set(DECISION_NODE_RE.findall(text))
    outgoing_counts: dict[str, int] = {}
    for line in lines:
        m = EDGE_FROM_RE.match(line)
        if m:
            src = m.group(1)
            outgoing_counts[src] = outgoing_counts.get(src, 0) + 1

    for node in sorted(decision_nodes):
        if outgoing_counts.get(node, 0) < 2:
            errors.append(f"决策节点 {node} 的出口少于 2 条，请补充分支。")

    errors.extend(_validate_label_quoting(lines))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Mermaid 业务流程图的基础结构")
    parser.add_argument("--input", required=True, help="Mermaid 文件路径（.mmd 或 .md）")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"文件不存在: {path}")
        return 1

    text = load_mermaid_text(path)
    errors = validate_mermaid_text(text)
    if errors:
        print("校验失败：")
        for item in errors:
            print(f"- {item}")
        return 1

    print("校验通过：Mermaid 流程图结构符合基础规范。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
