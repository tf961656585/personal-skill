#!/usr/bin/env python3
"""spec 拆分器：单 spec 文件超载（>2000 行量级）时按域拆分 + 首版数值抽离 + 入站引用重定向 + 链接/锚点自检。

模式（plan.yaml 仅 split/values/inbound 需要，check 独立运行）：
  check    全量 Markdown 链接自检（文件存在性 + 标题锚点）。design_lint 只查文件存在不查锚点，
           断链锚点必须靠本模式兜底。
  split    按计划把源文件的 ### 节拆入 out_dir 域文件：frontmatter + 标题提升（### → ##）+
           链接重定位（按解析后路径重算相对层级，不用前缀启发式）+ 时态清理 + 变更记录存档。
           主索引文件（总清单）属设计工作，手写，不在本脚本职责内。
  values   把域文件中的「首版数值」块替换为指针行（同前缀多次出现按声明顺序消费）。
  inbound  源文件拆分/改名后的入站引用重定向，三种形态：带锚点链接 / 无锚点链接+同行段名关键词 /
           纯文本提及；跳过变更记录历史行（| 2026 开头）与 memory/（历史不许改写）。

用法：
  spec_splitter.py check --root Assets/docs [--extra web/AGENTS.md]
  spec_splitter.py split  --plan split-plan.yaml --root .
  spec_splitter.py values --plan split-plan.yaml --root .
  spec_splitter.py inbound --plan split-plan.yaml --root .

plan.yaml 字段见 scripts/examples/spec-split-plan.yaml（data-config.md 实战计划存档）。

已吸收的实战坑（2026-09-12 data-config.md 拆分）：
- 相对链接层级逐目标重算（sibling ../x.md 与 spec 根 ../../x.md 混用，批量替换前缀会双向误伤）
- 子目录文件自引主索引必须是 ../
- 入站重定向不改写历史行与 memory 证据
- 锚点修复须读语境——目标可能是「废除」而非「改名」，脚本只做机械重定向，语义复核在人
- checker 的标题索引键与链接解析键必须同源（绝对路径），否则全表假阳性
"""
import argparse
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip3 install pyyaml")

MD_LINK = re.compile(r"\]\(([^)]+)\)")  # 捕获完整目标（含 #锚点）；纯锚点链接也必须命中
HIST_ROW = re.compile(r"^\s*\|\s*20\d{2}")  # 变更记录历史行（| 2026-…），不许改写


def slug(heading: str) -> str:
    """GitHub 风格锚点：小写、去标点（保留中文/字母/数字/连字符/空格）、空格转连字符。"""
    h = heading.strip().lower()
    h = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", h)
    return h.replace(" ", "-")


def iter_md_files(root: Path, extra=None):
    files = sorted(p.resolve() for p in root.rglob("*.md"))
    for e in extra or []:
        e = Path(e).resolve()
        if e.exists() and e not in files:
            files.append(e)
    return files


def collect_headings(files):
    headings = {}
    for p in files:
        hs = set()
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", p.read_text(), re.M):
            hs.add(slug(m.group(1)))
        headings[str(p)] = hs
    return headings


# ---------------------------------------------------------------- check
def cmd_check(args):
    root = Path(args.root).resolve()
    files = iter_md_files(root, args.extra)
    headings = collect_headings(files)
    broken, checked = [], 0
    for p in files:
        for m in MD_LINK.finditer(p.read_text()):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            tgt, _, anchor = target.partition("#")
            resolved = (p.parent / tgt).resolve()
            checked += 1
            if not resolved.exists():
                broken.append(f"{p} → {tgt} (文件不存在)")
            elif anchor and resolved.suffix == ".md" and slug(anchor) not in headings.get(str(resolved), set()):
                broken.append(f"{p} → {tgt}#{anchor} (锚点不存在)")
    print(f"共检查 {checked} 个链接")
    if broken:
        print(f"断链 {len(broken)} 个:")
        for b in broken:
            print("  " + b)
        sys.exit(1)
    print("✓ 全部链接（文件+锚点）解析通过")


# ---------------------------------------------------------------- plan
def load_plan(path):
    plan = yaml.safe_load(Path(path).read_text())
    for key in ("source", "out_dir", "domains", "sections"):
        if key not in plan:
            sys.exit(f"plan 缺少必填字段: {key}")
    return plan


def anchor_map_of(plan):
    m = {s["title"]: s["domain"] for s in plan["sections"]}
    m.update(plan.get("extra_anchors") or {})
    return m


def new_target_for(resolved: Path, anchor: str | None, source: Path, out_dir: Path, anchors: dict):
    """拆分/重定向共用的目标裁决：源文件带已知锚点 → 域文件；否则维持原解析。"""
    if resolved == source and anchor and anchor.lstrip("#") in anchors:
        return out_dir / f"{anchors[anchor.lstrip('#')]}.md"
    return resolved


def fix_links(text: str, src_dir: Path, source: Path, out_dir: Path, anchors: dict, cur_file: Path, warns: list):
    """把 text 中的相对链接按「源目录解析 → 目标目录重定位」改写；裸锚点走域映射。"""
    def repl(m):
        target = m.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        if target.startswith("#"):  # 纯锚点链接
            dom = anchors.get(target[1:])
            if dom is None:
                return m.group(0)  # 节内锚点（同文件）或未知，保持
            dom_path = (out_dir / f"{dom}.md").resolve()
            if dom_path == cur_file.resolve():
                return m.group(0)
            return f"]({os.path.relpath(dom_path, cur_file.parent)}{target})"
        tgt, _, anchor = target.partition("#")
        resolved = (src_dir / tgt).resolve()
        if not resolved.exists():
            warns.append(f"链接目标不存在，保持原样: {tgt}")
            return m.group(0)
        final = new_target_for(resolved, anchor, source, out_dir, anchors)
        rel = os.path.relpath(final, cur_file.parent)
        return f"]({rel}{'#' + anchor if anchor else ''})"
    return MD_LINK.sub(repl, text)


# ---------------------------------------------------------------- split
def cmd_split(args):
    root = Path(args.root).resolve()
    plan = load_plan(args.plan)
    source = (root / plan["source"]).resolve()
    out_dir = (root / plan["out_dir"]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fm = plan["frontmatter"].rstrip("\n")
    today = plan.get("date") or args.date

    lines = source.read_text().splitlines(keepends=True)
    heads = [(i, l) for i, l in enumerate(lines) if l.startswith("### ")]
    title2dom = {s["title"]: s["domain"] for s in plan["sections"]}
    pos = {}
    for i, l in heads:
        t = l.strip()[4:]
        if t in title2dom:
            if t in pos:
                sys.exit(f"重复节标题: {t}")
            pos[t] = i
    missing = set(title2dom) - set(pos)
    if missing:
        sys.exit(f"源文件找不到节标题: {sorted(missing)}")
    # 计划是「节 → 域」映射，按文档序处理（不要求计划列表与文档同序）
    order = sorted(pos.items(), key=lambda kv: kv[1])

    anchors = anchor_map_of(plan)
    warns = []
    # 每节结束边界：下一个计划节 与 下一个任意 ## 标题（关键约束/待决策项等尾部节属主文件）取较早者
    h2_positions = [i for i, l in enumerate(lines) if l.startswith("## ")]
    bounds = []
    for k, (t, i) in enumerate(order):
        next_planned = order[k + 1][1] if k + 1 < len(order) else len(lines)
        next_h2 = next((j for j in h2_positions if j > i), len(lines))
        bounds.append(min(next_planned, next_h2))
    unplanned = [l.strip()[4:] for i, l in heads if l.strip()[4:] not in title2dom
                 and order and i > order[0][1]]
    if unplanned:
        warns.append(f"以下 ### 节不在计划内，将被并入前一节的域文件（确认是否有意）: {unplanned}")
    out_content = {d: [] for d in plan["domains"]}
    for k, (t, i) in enumerate(order):
        dom = title2dom[t]
        end = bounds[k]
        body = lines[i:end]  # 含节标题行——标题即锚点载体，丢弃会让 values 的 heading 结束标记失配
        while body and body[-1].strip() == "":
            body.pop()
        text = "".join(body)
        for r in plan.get("temporal_replacements") or []:
            if r["old"] in text:
                text = text.replace(r["old"], r["new"])
        text = re.sub(r"^(#{3,4}) ", lambda m: "#" * (len(m.group(1)) - 1) + " ", text, flags=re.M)  # 单遍提升，防 ####→###→## 双重命中
        text = fix_links(text, source.parent, source, out_dir, anchors, out_dir / f"{dom}.md", warns)
        out_content[dom].append(text.rstrip("\n") + "\n\n")

    for dom, meta in plan["domains"].items():
        intro = (f"> 本文件是 [data-config.md](../{plan['main_name']}) 的域拆分文件（{meta['desc']}）。"
                 f"核心契约与配置表总索引见 [../{plan['main_name']}](../{plan['main_name']})。")
        parts = [f"{fm}\n\n# {meta['title']}\n\n{intro}\n\n"]
        parts += [f"> 各表首版数值统一见 [{plan['values_file']}]({plan['values_file']})；"
                  f"本目录全部文件的历史变更记录见 [{plan['changelog_name']}]({plan['changelog_name']})。\n\n"
                  ] if plan.get("values_file") else []
        parts += out_content[dom]
        parts += [f"## 变更记录\n\n本目录拆分前统一记录于主文件，历史条目见 [{plan['changelog_name']}]({plan['changelog_name']})。"
                  f"本文件级变更自下表起记录。\n\n| 日期 | 变更内容 | 变更原因 | 影响范围 |\n|------|----------|----------|----------|\n"
                  f"| {today} | 本文件由 {plan['main_name']} 按域拆分建立（文件组织重组，契约内容不变更） | 单文件超载，信息密度与导航成本失控 | 全文件 |\n"]
        (out_dir / f"{dom}.md").write_text("".join(parts))

    # 变更记录历史存档（Archived 形态：spec-first 免变更记录节要求 + archived-on 配套，design_lint 合规）
    src_text = source.read_text()
    m = re.search(r"^## 变更记录.*?(\n\| 日期 \|.*?)(\n(?=#|\Z))", src_text, re.S | re.M)
    cl = []
    if m:
        cl_fm = (f"---\ntype: spec\nstatus: Archived\narchived-on: {today}\n"
                 "layer: spec-first\nchange-model: flow-back\n---\n\n")
        cl = [cl_fm, f"# {plan['main_name']} 目录变更记录（历史存档）\n\n",
              f"> 本文件收录 {plan['main_name']} 拆分前的全部变更记录，作为主文件与各域文件的共享历史档案。"
              f"新变更分别记录于主文件与各域文件的「变更记录」节。\n\n", m.group(1) + "\n"]
        (out_dir / plan["changelog_name"]).write_text("".join(cl))
    for w in sorted(set(warns)):
        print(f"  ⚠ {w}")
    print(f"split 完成 → {out_dir}（{len(plan['domains'])} 域文件" + (f" + {plan['changelog_name']}" if cl else "") + "）")


# ---------------------------------------------------------------- values
def cmd_values(args):
    root = Path(args.root).resolve()
    plan = load_plan(args.plan)
    out_dir = (root / plan["out_dir"]).resolve()
    blocks = plan.get("value_blocks") or []
    by_file = {}
    for b in blocks:
        by_file.setdefault(b["file"], []).append(b)
    for fname, bs in by_file.items():
        p = out_dir / fname
        lines = p.read_text().splitlines(keepends=True)
        out, i, qi = [], 0, 0
        while i < len(lines):
            line = lines[i]
            if qi < len(bs) and line.startswith(bs[qi]["start_prefix"]):
                b = bs[qi]
                j = i + 1
                while j < len(lines):
                    t = lines[j]
                    et, em = b["end_type"], b["end_marker"]
                    if (et == "bold" and t.startswith(em)) or (et == "heading" and t.startswith("## ")) \
                       or (et == "text" and t.strip() == em):
                        break
                    j += 1
                else:
                    sys.exit(f"{fname}: 块『{b['start_prefix'][:24]}…』未找到结束标记 {em}")
                out.append(b["pointer"] + "\n\n")
                qi += 1
                i = j
                continue
            out.append(line)
            i += 1
        assert qi == len(bs), f"{fname}: 只匹配 {qi}/{len(bs)} 个数值块"
        p.write_text("".join(out))
        print(f"{fname}: 替换 {qi} 个数值块")
    print(f"values 完成（{len(blocks)} 块）")


# ---------------------------------------------------------------- inbound
def cmd_inbound(args):
    root = Path(args.root).resolve()
    plan = load_plan(args.plan)
    source = (root / plan["source"]).resolve()
    out_dir = (root / plan["out_dir"]).resolve()
    anchors = anchor_map_of(plan)
    keywords = sorted(plan.get("keywords") or [], key=lambda kv: -len(kv[0]))
    plain = plan.get("plain") or []
    roots = [root / r for r in (plan.get("inbound_roots") or ["."])]
    changed, report = {}, []

    files = sorted({p.resolve() for r in roots for p in r.rglob("*.md")})
    for p in files:
        if p.is_relative_to(out_dir) or p.is_relative_to(root / "memory"):
            continue
        out_lines, n = [], 0
        for line in p.read_text().splitlines(keepends=True):
            orig = line
            if HIST_ROW.match(line) or line.lstrip().startswith("| 日期"):
                out_lines.append(line)
                continue

            def repl(m):
                target = m.group(1)
                if target.startswith(("http", "mailto")):
                    return m.group(0)
                tgt, _, anchor = target.partition("#")
                if not tgt:
                    return m.group(0)  # 纯锚点是文件内自引，不可能是源文件引用
                resolved = (p.parent / tgt).resolve()
                if resolved != source:
                    return m.group(0)
                if anchor and anchor.lstrip("#") in anchors:
                    final = out_dir / f"{anchors[anchor.lstrip('#')]}.md"
                else:
                    # 无锚点/未知锚点链接：按同行段名关键词路由（长词优先），无线索报人工复核
                    tail = line[m.end():m.end() + 80]
                    dom = next((d for kw, d in keywords if kw in tail), None) \
                        or next((d for kw, d in keywords if kw in line), None)
                    if dom is None:
                        report.append(f"{p.name}: 无段名线索，维持主文件指向: {line.strip()[:60]}")
                        return m.group(0)
                    final = out_dir / f"{dom}.md"
                return f"]({os.path.relpath(final, p.parent)}{'#' + anchor if anchor else ''})"

            line = MD_LINK.sub(repl, line)
            for old, new in plain:
                line = line.replace(old, new)
            if line != orig:
                n += 1
            out_lines.append(line)
        if n:
            p.write_text("".join(out_lines))
            changed[p.name] = n
    print("== 修改的文件 ==")
    for k, v in sorted(changed.items()):
        print(f"  {k}: {v} 行")
    if report:
        print("== 待人工复核 ==")
        for r in report:
            print("  " + r)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="全量链接自检（文件+锚点）")
    c.add_argument("--root", required=True)
    c.add_argument("--extra", nargs="*", default=[])
    c.set_defaults(fn=cmd_check)
    for name in ("split", "values", "inbound"):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--root", default=".")
        s.add_argument("--date", default=None)
        s.set_defaults(fn={"split": cmd_split, "values": cmd_values, "inbound": cmd_inbound}[name])
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
