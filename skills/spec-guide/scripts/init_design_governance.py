#!/usr/bin/env python3
"""
新仓库设计层治理脚手架。

在目标仓库生成设计层治理骨架：目录结构、产物登记表、agent-map 导航桩。
幂等——只创建缺失项，已存在的一律跳过不覆盖；可重复运行。

用法:
    python3 init_design_governance.py --root /path/to/repo
    python3 init_design_governance.py --root . --dry-run

退出码:
    0  成功（含全部跳过）
    2  输入错误（root 不存在或不是目录）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# 骨架清单：(相对路径, 内容或 None 表示目录)
# 内容刻意只放最小可校验骨架，不预填任何业务口径——脚手架管结构，不管设计。
SKELETON: list[tuple[str, str | None]] = [
    ("docs/spec", None),
    ("docs/adr", None),
    ("docs/flowcharts", None),
    ("prototypes", None),
    (
        "docs/design-registry.yaml",
        """# 产物登记表：流程图 / 原型的生命周期登记口径（格式规范见 spec-guide references/frontmatter.md 第五节）
# frontmatter 产物（spec / ADR / 契约文档 / 设计文档）自描述，无需登记。
version: 1
artifacts: []
""",
    ),
    (
        "docs/agent-map.yaml",
        """# 文档地图：任务路由（routes）与废弃关系指针（pointers），按需加载。
# frontmatter 是状态唯一源，本文件只承载导航与指针，不得形成第二套口径；
# 存在即被 design_lint.py 校验（最小契约见 spec-guide references/frontmatter.md 第六节）。
version: 1
routes: []
#  - match: 订单/账单          # 任务关键词或模式
#    read: [docs/spec/billing.md]
pointers: []
#  - path: docs/spec/billing-v1.md
#    relation: superseded       # current | superseded | deprecated | archived
#    by: docs/spec/billing.md   # 可选：替代口径
""",
    ),
]

GITKEEP = "# 占位文件：目录有产物后可删除\n"


def scaffold(root: Path, dry_run: bool) -> tuple[list[str], list[str]]:
    """执行脚手架，返回 (已创建, 已跳过) 路径列表。"""
    created: list[str] = []
    skipped: list[str] = []

    for rel, content in SKELETON:
        target = root / rel
        if target.exists():
            skipped.append(rel)
            continue
        created.append(rel)
        if dry_run:
            continue
        if content is None:
            target.mkdir(parents=True, exist_ok=True)
            (target / ".gitkeep").write_text(GITKEEP, encoding="utf-8")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    return created, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="生成仓库设计层治理骨架（幂等）")
    parser.add_argument("--root", default=".", help="目标仓库根目录（默认当前目录）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将创建的内容，不落盘")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"目标根目录不存在或不是目录: {root}")
        return 2

    created, skipped = scaffold(root, args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    if created:
        print(f"{prefix}已创建 {len(created)} 项：")
        for rel in created:
            print(f"  + {rel}")
    if skipped:
        print(f"跳过已存在 {len(skipped)} 项：")
        for rel in skipped:
            print(f"  = {rel}")

    print()
    print("下一步：")
    print("  1. 首份设计产物走 design-guide 路由（判可逆性 → 选载体）")
    print("  2. 交付门禁：python3 design_lint.py docs --root .（随 spec-guide skill 提供）")
    print("  3. 登记表只在引入流程图 / 原型时填写，frontmatter 产物无需登记")
    print("  4. agent-map 按需填 routes（任务 → 必读产物）与 pointers（废弃关系）；")
    print("     全量产物清点用 python3 design_lint.py docs --root . --list-artifacts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
