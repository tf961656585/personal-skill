#!/usr/bin/env python3
"""校验「显式文档路径 + §X.Y」引用：被引文档里该章节是否真的存在。

用法:
    python3 check-section-refs.py <repo_root> [扫描子目录 ...]

只校验形如 `path/x.md` §1.2 的引用——§ 前面明确写了目标文档路径。
刻意不校验同文档裸 §1.2：归属无法机械判定（一行里出现多个 §、或前文已声明目标
文档时，裸 § 指的是别的文档），实测假阳性极高（见下方"实测记录"）。退出码 0/1。

设计取舍:
- 章节标题识别允许编号前有 emoji / 符号前缀（`## ✅ 0.7 ...`、`### 7.4 ...`）。
  写成 `^#{2,4}\\s+(\\d+` 会漏判 `## ✅ 0.7` 这类标题——实测漏判 7 处。
- 同文档裸 § 引用曾纳入校验，全仓报 48-64 处，逐条核对**全部是假阳性**：
  `window-chrome.md` 的「消费其 §8.1」指的是同表格另一列点名的 visual-design 文档；
  `07-NanoBananaPro转换层映射对账.md` 的「§5.1-§5.12」指上一句点名的 05-GeminiFlash。
  加"本行出现 .md 就跳过"的启发式后仍剩 48 处（这些行用的是不带后缀的简称），
  故移除——归属判断需要语义理解，正则做不到。
- 剩余假阳性只有"叙述性提及"（如"本文件没有 §5.2"这类在讲某编号不存在的句子），
  量级为个位数，人工扫即可。
- 文件级断链（被引文件本身不存在）不在此脚本范围，归 `design_lint.py`。
"""
from __future__ import annotations

import os
import re
import sys

SKIP_DIRS = {"node_modules", ".git", "dist", "dist-static", ".next", "out", ".model-assets", "__pycache__"}
CODE_SUFFIXES = (".ts", ".tsx", ".cts", ".mts", ".js", ".mjs", ".py")

# 章节标题：允许编号前有 emoji / 符号前缀（`## ✅ 0.7 ...`、`### 7.4 ...`）
HEAD_RE = re.compile(r"^#{1,6}\s+[^\w\s]*\s*(\d+(?:\.\d+)*)", re.M)
# 带文档路径的引用：`path/x.md` §1.2 / path/x.md §1.2
DOC_REF_RE = re.compile(r"([A-Za-z0-9_\-./\u4e00-\u9fa5]+\.md)[`\s）)]*\s*§\s?(\d+(?:\.\d+)*)")


def sections_of(path: str) -> set[str]:
    with open(path, encoding="utf-8") as fh:
        return set(HEAD_RE.findall(fh.read()))


def resolve(doc: str, owner: str, root: str) -> str | None:
    """按 仓库根相对 → 引用方同目录相对 → 从路径尾部逐段回退 的顺序解析目标文档。"""
    parts = doc.split("/")
    candidates = [os.path.join(root, doc), os.path.normpath(os.path.join(os.path.dirname(owner), doc))]
    candidates += [os.path.join(root, *parts[i:]) for i in range(1, len(parts))]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def scan(root: str, subdirs: list[str]) -> list[tuple[str, int, str, str]]:
    bad: list[tuple[str, int, str, str]] = []
    cache: dict[str, set[str]] = {}
    targets = [os.path.join(root, d) for d in subdirs] or [root]
    for target in targets:
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                if not (name.endswith(".md") or name.endswith(CODE_SUFFIXES)):
                    continue
                owner = os.path.join(dirpath, name)
                with open(owner, encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
                for lineno, line in enumerate(lines, 1):
                    for doc, sec in DOC_REF_RE.findall(line):
                        real = resolve(doc, owner, root)
                        if real is None:
                            continue  # 文件级断链归 design_lint.py
                        heads = cache.setdefault(real, sections_of(real))
                        if sec not in heads:
                            bad.append((owner, lineno, doc, sec))
    return bad


def main() -> int:
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    bad = scan(root, sys.argv[2:])
    for owner, lineno, doc, sec in bad:
        print(f"{os.path.relpath(owner, root)}:{lineno}  ->  {doc} §{sec}")
    print(f"[check-section-refs] {len(bad)} 处 § 章节引用断链")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
