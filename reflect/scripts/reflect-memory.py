#!/usr/bin/env python3
# reflect-memory.py — memory/ 生命周期辅助脚本（reflect skill）
#
# 用法:
#   reflect-memory.py init  [repo_root]   创建 memory/ 标准骨架（已存在则不改动）
#   reflect-memory.py check [repo_root]   检测失效与漂移信号：
#                                           - 证据引用文件已消失（疑似失效）
#                                           - 索引漂移（主题文件条目 ↔ 索引条目
#                                             「日期 + 指向文件」多重集不对齐）
#                                           - 失联提案（proposals/ 有文件但索引未登记）
#   repo_root 省略时自动向上探测仓库根（.git 或已存在的 memory/），未命中按 cwd 处理——
#   agent 会话的 shell 常停在子目录，直接按 cwd 落骨架会在子目录建出平行 memory/。
#
# 职责边界：脚本只做机械信号检测与骨架初始化，不修改任何记忆条目。
# check 的输出是疑似清单，条目是否失效由 agent 读代码按"失效条件"裁决。
#
# 兼容性：Python 3.9+（避免 match 语法，用 if/elif），纯 stdlib。
# shebang 用 /usr/bin/env python3 以保证可分发性。

import os
import re
import sys
from collections import Counter
from pathlib import Path

# --- 索引行格式: - [类型] <YYYY-MM-DD> 主题句 → file.md
# 日期作为条目的稳定主键——主题文件标题 ## YYYY-MM-DD — 主题 与索引行共享同一日期。
INDEX_LINE_RE = re.compile(
    r'^-\s*\[(?P<type>[^\]]+)\]\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<topic>.+?)\s*→\s*(?P<file>\S+)\s*$'
)
# --- 主题文件条目标题: ## YYYY-MM-DD — 主题
TOPIC_HEADING_RE = re.compile(
    r'^##\s+(?P<date>\d{4}-\d{2}-\d{2})\s+[—-]\s*(?P<topic>.+?)\s*$'
)
# --- 证据行里的文件引用（须带行号标注才算引用）
# 两种标注都要认：`path:12` 与 `path 第 12 行`——后者是本仓库实际在用的写法，
# 不认它会漏检（2026-09-10 实测：证据文件已消失，check 仍报 OK）。
# 刻意保留"须带行号"这个前提：证据里常出现「某文件已删除」这类把文件名当反例
# 的表述，若接受裸路径，会把它们连同 URL 路径、`.md` 这类选择器一起报成失效
# 条目（2026-09-10 实测：一次放宽产生 12 条误报，噪声直接淹没信号）。
# 扩展名顺序重要：`tsx` 必须排在 `ts` 前，否则 `x.tsx:1` 会回溯到不成立的
# `x.ts` 后整体匹配失败、静默漏检；`json` 同理须在 `js` 前。
# CJK 字符类用于 田丰-U3D.resume.json 这类中文文件名。
EVIDENCE_REF_RE = re.compile(
    r'(?P<path>[A-Za-z0-9_./\-\u4e00-\u9fff]*\.'
    r'(?:tsx|jsx|mjs|cjs|json|yaml|yml|toml|html|css|md|ts|js|py|sh|sql|go|rs|java|kt|rb|php|vue|svelte))'
    r'(?P<line>\s*:\s*[0-9]+|\s*第\s*[0-9]+(?:\s*[-–—~]\s*[0-9]+)?\s*行)'
)

TOPIC_FILES = [
    ('dependencies.md', '隐藏依赖'),
    ('pitfalls.md', '踩坑'),
    ('decisions.md', '决策及原因'),
    ('preferences.md', '被纠正的偏好'),
    ('facts.md', '情境事实'),
]


def usage():
    print('用法: reflect-memory.py init|check [repo_root]', file=sys.stderr)
    sys.exit(2)


def detect_repo_root(start: Path) -> Path:
    """省略 repo_root 参数时，自 start 向上探测仓库根（.git 或已存在的 memory/），未命中回退 start。"""
    cur = start.resolve()
    for path in (cur, *cur.parents):
        if (path / '.git').exists() or (path / 'memory').is_dir():
            return path
    return start


def memory_skeleton_md():
    return """# MEMORY — 可探索记忆索引

经验性记忆，非权威 spec。按需读取，使用前按条目的失效条件核验仍成立。

## 主题文件

- dependencies.md — 隐藏依赖
- pitfalls.md — 踩坑
- decisions.md — 决策及原因
- preferences.md — 被纠正的偏好
- facts.md — 情境事实

## 条目

（无）

## 待确认提案

（无）
"""


def cmd_init(root: Path):
    mem = root / 'memory'
    if mem.is_dir():
        print(f'已存在: {mem}（不改动）')
        return
    proposals = mem / 'proposals'
    proposals.mkdir(parents=True)
    (proposals / '.gitkeep').touch()
    (mem / 'MEMORY.md').write_text(memory_skeleton_md(), encoding='utf-8')
    for fname, title in TOPIC_FILES:
        (mem / fname).write_text(f'# {title}\n', encoding='utf-8')
    print(f'已创建 memory/ 骨架: {mem}')


def parse_topic_entries(path: Path):
    """从主题文件提取条目: 返回 [(date, topic_heading_line), ...]，按出现顺序。"""
    entries = []
    for line in path.read_text(encoding='utf-8').splitlines():
        m = TOPIC_HEADING_RE.match(line)
        if m:
            entries.append((m.group('date'), line))
    return entries


def parse_index(path: Path):
    """从 MEMORY.md 解析。返回:
       - index_entries: {date: [raw_line, ...]}（「## 条目」区块下，日期主键）
         **必须保留同日全部行**：同一天可有多个条目（分属不同主题文件）——
         用 {date: raw_line} 覆盖会让同日多出的悬空行在后续比对里整条消失。
       - proposals_listed: set(日期字符串)（「## 待确认提案」区块下出现的日期）
       - has_entry_section: bool
    """
    text = path.read_text(encoding='utf-8')
    lines = text.splitlines()
    index_entries = {}
    proposals_listed = set()
    has_entry_section = False

    # 找各区块
    section = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## '):
            heading = stripped[3:].strip()
            if heading == '条目':
                section = 'entries'
                has_entry_section = True
            elif heading == '待确认提案':
                section = 'proposals'
            else:
                section = None
            continue
        if section == 'entries':
            m = INDEX_LINE_RE.match(line)
            if m:
                index_entries.setdefault(m.group('date'), []).append(line)
        elif section == 'proposals':
            # 提案区块里出现的任何 YYYY-MM-DD 视为已登记
            for d in re.findall(r'\d{4}-\d{2}-\d{2}', line):
                proposals_listed.add(d)
    return index_entries, proposals_listed, has_entry_section


def cmd_check(root: Path):
    mem = root / 'memory'
    if not mem.is_dir():
        print(f'无 memory/ 目录: {root}（本仓库尚未沉淀记忆）')
        return

    signals = []  # 每个元素是一段输出文本

    # 1. 证据文件存在性 —— 检测证据行里带行号标注的文件引用
    evidence_missing = []
    for f in sorted(mem.glob('*.md')):
        if f.name == 'MEMORY.md':
            continue
        current_entry_date = None
        for line in f.read_text(encoding='utf-8').splitlines():
            hm = TOPIC_HEADING_RE.match(line)
            if hm:
                current_entry_date = f"{f.name} | {hm.group('date')} — {hm.group('topic')}"
                continue
            if line.strip().startswith('- 证据:') or line.strip().startswith('-证据:'):
                for ref in EVIDENCE_REF_RE.findall(line):
                    p = ref[0]
                    if not (root / p).exists():
                        evidence_missing.append((current_entry_date or f.name, p))
    if evidence_missing:
        out = ['疑似失效条目（证据文件已消失；需读代码按失效条件裁决，不可据此直接删除）:',
               '条目 | 缺失文件']
        for entry, p in evidence_missing:
            out.append(f'{entry} | {p}')
        signals.append('\n'.join(out))

    # 2. 索引漂移 —— 用日期主键做双向关联
    memory_md = mem / 'MEMORY.md'
    if memory_md.exists():
        index_entries, _, has_entry_section = parse_index(memory_md)
        # 汇总所有主题文件的条目（按日期）
        topic_dates = {}  # date -> [主题文件名]
        for f in sorted(mem.glob('*.md')):
            if f.name == 'MEMORY.md':
                continue
            for date, _ in parse_topic_entries(f):
                topic_dates.setdefault(date, []).append(f.name)

        drift_lines = []
        if not has_entry_section:
            drift_lines.append('MEMORY.md 缺「## 条目」区块（脚本骨架应有，可能被误删或手动建的索引未对齐）')
        else:
            # 用多重集（日期 + 指向文件）双向关联，而非集合：
            # ① 同一天可有多个条目（分属不同主题文件），set 比对会把"同日多出的悬空
            #    索引行"整条吞掉——2026-09-10 实测：索引比 pitfalls.md 多一行同日条目，
            #    check 仍报 OK，需人工用 Counter 才查出；
            # ② 带上指向文件后，"行指向了错误的主题文件"也能暴露——日期虽在、
            #    照索引去该文件却找不到条目，同属漂移。
            topic_pairs = Counter(
                (date, fname)
                for date, fnames in topic_dates.items()
                for fname in fnames
            )
            index_pairs = Counter()
            for date, raws in index_entries.items():
                for raw in raws:
                    m = INDEX_LINE_RE.match(raw)
                    if m:
                        index_pairs[(date, m.group('file'))] += 1
            for (date, fname), n in sorted(topic_pairs.items()):
                have = index_pairs.get((date, fname), 0)
                if have < n:
                    drift_lines.append(
                        f'索引漏登: {date} → {fname}（主题文件 {n} 条，索引 {have} 条）'
                    )
            for (date, fname), n in sorted(index_pairs.items()):
                have = topic_pairs.get((date, fname), 0)
                if have < n:
                    drift_lines.append(
                        f'索引悬空: {date} → {fname}（索引 {n} 条，主题文件 {have} 条）'
                    )
        if drift_lines:
            signals.append('索引漂移信号:\n' + '\n'.join(drift_lines))

        # 3. 索引「条目」行指向的文件存在性
        orphan_file = []
        for raws in index_entries.values():
            for raw in raws:
                m = INDEX_LINE_RE.match(raw)
                if m:
                    target = m.group('file')
                    if not (mem / target).exists():
                        orphan_file.append(f'{raw}（指向的 {target} 不存在）')
        if orphan_file:
            signals.append('索引条目指向文件不存在:\n' + '\n'.join(orphan_file))

    # 4. 失联提案 —— proposals/ 下有文件但索引「待确认提案」区块未列
    proposals_dir = mem / 'proposals'
    if proposals_dir.exists():
        _, proposals_listed, _ = parse_index(memory_md) if memory_md.exists() else (None, set(), False)
        orphan_proposals = []
        for f in sorted(proposals_dir.glob('*.md')):
            stem = f.stem  # 文件名形如 2026-08-08 或 2026-08-08-foo
            # 提案区块里出现的日期集合作为"已登记"判据
            listed = any(stem.startswith(d) or d.startswith(stem[:10]) for d in proposals_listed)
            if not listed and stem not in proposals_listed:
                # 更稳的判据: 文件名前 10 字符（日期）在 proposals_listed 里
                date_part = stem[:10]
                if date_part not in proposals_listed:
                    orphan_proposals.append(f.name)
        if orphan_proposals:
            signals.append('失联提案（proposals/ 下存在但索引「待确认提案」区块未列出，疑似裁决后未清理的残留；与用户确认后删除）:\n'
                           + '\n'.join(orphan_proposals))

    if not signals:
        print('OK: 所有证据引用的文件均存在，索引与主题文件同步，无失联提案')
        return
    print('\n\n'.join(signals))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    root = Path(argv[2]) if len(argv) > 2 else detect_repo_root(Path.cwd())
    if cmd == 'init':
        cmd_init(root)
    elif cmd == 'check':
        cmd_check(root)
    else:
        usage()


if __name__ == '__main__':
    main(sys.argv)
