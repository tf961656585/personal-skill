#!/usr/bin/env python3
# reflect-memory.py — memory/ 生命周期辅助脚本（reflect skill）
#
# 用法:
#   reflect-memory.py init       [repo_root]  创建/补齐 memory/ 骨架（已存在时只补缺失文件，不改动已有内容）
#   reflect-memory.py check      [repo_root]  只读检测：格式、失效、漂移、残余行、队列信号
#   reflect-memory.py certify    [repo_root]  重建索引 → 校验形状 → 写 memory-schema 合规标记
#   reflect-memory.py index      [repo_root]  只重建 MEMORY.md「## 条目」区块（索引是生成物）
#   reflect-memory.py add        <payload.json|-> [repo_root]  写入一条记忆并重建索引
#   reflect-memory.py stale-add  <payload.json|-> [repo_root]  追加一条待清理队列记录
#   reflect-memory.py inbox-add  <payload.json|-> [repo_root]  追加一条待补队列记录
#   reflect-memory.py schema                  输出机器可读的格式契约
#   repo_root 省略时自动向上探测仓库根（.git 或已存在的 memory/），未命中按 cwd 处理——
#   agent 会话的 shell 常停在子目录，直接按 cwd 落骨架会在子目录建出平行 memory/。
#
# 职责边界：脚本不代替 agent 判断内容。check 的输出是疑似清单，条目是否失效、是否导入
# 由 agent 读代码/读源按规则裁决。合规标记只证明形状合规（字段齐全、索引与条目一致、
# 残余行可解析、证据文件存在），不证明内容正确。
#
# 两条设计约束（2026-10-24 加固）：
#   1. 索引是生成物。MEMORY.md 的「## 条目」区块由条目字段渲染，禁止手写；
#      因此"索引漂移 / 锚点悬空"这类问题在写入路径上不可能产生。
#   2. 残余行严格化。队列文件与索引区块里任何"看起来该是记录、但解析不了"的行
#      都报错并阻断认证，不再静默丢弃——静默丢弃会让读侧的失效上报无声蒸发。
#
# 兼容性：Python 3.9+（避免 match 语法，用 if/elif），纯 stdlib。
# shebang 用 /usr/bin/env python3 以保证可分发性。

import json
import re
import sys
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = 3
MARKER_RE = re.compile(r'<!--\s*memory-schema:\s*(\d+)\s*-->')

# --- 索引行格式: - [类型] <YYYY-MM-DD> <钩子> → file.md#id
# 条目地址是 file#id；日期是捕获日，不是唯一定位键（同文件同日可有多条）。
# 该行由 render_index_lines() 生成，不手写。
INDEX_LINE_RE = re.compile(
    r'^-\s*\[(?P<type>[^\]]+)\]\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<topic>.+?)\s*→\s*'
    r'(?P<file>[^\s#]+)(?:#(?P<id>\S+))?\s*$'
)
# --- 主题文件条目标题: ## YYYY-MM-DD — 主题
# en dash / hyphen 也接受：历史条目用它们写的不能被静默跳过。
TOPIC_HEADING_RE = re.compile(
    r'^##\s+(?P<date>\d{4}-\d{2}-\d{2})\s+[—–-]\s*(?P<topic>.+?)\s*$'
)
# 形似条目但分隔符坏了：必须显式报错，不能被当成普通说明小节静默跳过。
MALFORMED_HEADING_RE = re.compile(r'^##\s+(?P<date>\d{4}-\d{2}-\d{2})')
# --- 条目字段行: - <字段名>: <值>，半角/全角冒号都认
FIELD_LINE_RE = re.compile(r'^-\s*(?P<name>[^\s:：]+)\s*[:：]\s*(?P<value>.*)$')
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

# 条目「类型」字段的取值（与主题文件的分组名不同，别混用）。
TYPES = ('隐藏依赖', '踩坑', '决策', '偏好', '情境事实')
SCOPES = ('user', 'project')

# 读侧待清理队列。
# v3: - <date> <file>#<id> — <evidence>
# v2 legacy: - <date> <file> :: <topic> — <evidence>（兼容存量队列）
STALE_FILE = 'stale.md'
STALE_LINE_RE = re.compile(
    r'^-\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<file>[^\s#]+)#(?P<id>\S+)\s+[—-]\s+'
    r'(?P<evidence>.+?)\s*$'
)
STALE_LEGACY_LINE_RE = re.compile(
    r'^-\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<file>\S+\.md)\s*::\s*'
    r'(?P<topic>.+?)\s+[—-]\s+(?P<evidence>.+?)\s*$'
)

# 导入待补队列。格式: - [待补] <来源路径>:<行> | 缺: <字段列表> | <条目标题> — <一句话内容>
# 来源段用 +? 而不是 \S+：路径可能含空格，写入器不该产出自己读不回的行。
INBOX_FILE = 'inbox.md'
INBOX_LINE_RE = re.compile(
    r'^- \[待补\]\s+(?P<source>.+?)\s*\|\s*缺[:：]\s*(?P<missing>.+?)\s*\|\s*(?P<title>.+)$'
)

# 骨架里的格式示例行，逐字跳过；除此之外任何"像记录但解析不了"的行都报错。
STALE_TEMPLATE = '- <YYYY-MM-DD> <主题文件>#<id> — <失效证据>'
INBOX_TEMPLATE = '- [待补] <来源路径>:<行> | 缺: <字段列表> | <条目标题> — <一句话内容>'

# 认证要求条目具备的字段。旧格式条目缺触发/作用域等会在此被点名，进入补齐流程。
REQUIRED_FIELDS = ('id', '类型', '作用域', '触发', '证据', '捕获于', '失效条件', '内容')
# 可选字段：钩子是索引行用的短触发语；缺省时索引回退用「触发」。
OPTIONAL_FIELDS = ('钩子',)
KNOWN_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
# 队列行"行首是日期"要用前缀匹配；DATE_PATTERN 带 $ 只匹配整行日期，
# 用它判断会把 `2026-10-24 deps.md#id — ...` 这类漏写 `-` 的行静默放过。
DATE_PREFIX_RE = re.compile(r'^\d{4}-\d{2}-\d{2}(?!\d)')
# 主题文件名会被渲染进索引行 `→ <file>#<id>`；这类字符会让该行不可解析。
# 主题文件是 memory/ 下的平铺文件，路径分隔符同样不接受。
INVALID_FILENAME_RE = re.compile(r'[\\/\s#→]')

# add 子命令的 payload 键别名（中英文都收，减少手写摩擦）。
FIELD_ALIASES = {
    'file': 'file',
    'topic': '主题', 'title': '主题', '主题': '主题', '标题': '主题',
    'id': 'id',
    'type': '类型', '类型': '类型',
    'scope': '作用域', '作用域': '作用域',
    'hook': '钩子', '钩子': '钩子',
    'trigger': '触发', '触发': '触发',
    'evidence': '证据', '证据': '证据',
    'captured': '捕获于', 'captured_at': '捕获于', 'date': '捕获于', '捕获于': '捕获于',
    'invalidation': '失效条件', 'invalidates': '失效条件', '失效条件': '失效条件',
    'content': '内容', '内容': '内容',
}

QUEUE_FILES = (STALE_FILE, INBOX_FILE)
NON_TOPIC_FILES = ('MEMORY.md', STALE_FILE, INBOX_FILE)


def usage():
    print(
        '用法:\n'
        '  reflect-memory.py init|check|certify|index [repo_root]\n'
        '  reflect-memory.py add|stale-add|inbox-add <payload.json|-> [repo_root]\n'
        '  reflect-memory.py schema',
        file=sys.stderr,
    )
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
索引行写触发钩子（下次什么情境下该读），并用 `file#id` 定位条目；结论留在主题文件条目里。
「条目」区块由 `reflect-memory.py index` 从条目生成，禁止手写。
骨架不含格式标记：条目写完运行 `certify` 认证并写入标记。
格式契约与导入规则见 reflect skill 的 references/memory-conversion.md。

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


def stale_skeleton_md():
    return """# 待清理条目

读侧核验失效后追加，`/reflect` 消费并清空。格式：

- <YYYY-MM-DD> <主题文件>#<id> — <失效证据>

（无）
"""


def inbox_skeleton_md():
    return """# 待补条目

导入时字段不齐、暂时无法进入主题文件的条目。`/reflect` 逐条补全：补齐并核验后移入主题文件并登记索引；已过时带证据删除；仍补不齐保留并报告。
本文件是工作队列，不是可检索记忆，也不是归档区。格式：

- [待补] <来源路径>:<行> | 缺: <字段列表> | <条目标题> — <一句话内容>

（无）
"""


def cmd_init(root: Path):
    mem = root / 'memory'
    created = []
    if not mem.is_dir():
        mem.mkdir(parents=True)
        created.append('memory/')

    if not (mem / 'MEMORY.md').exists():
        (mem / 'MEMORY.md').write_text(memory_skeleton_md(), encoding='utf-8')
        created.append('MEMORY.md')

    proposals = mem / 'proposals'
    if not proposals.is_dir():
        proposals.mkdir()
        (proposals / '.gitkeep').touch()
        created.append('proposals/')

    for fname, text in ((STALE_FILE, stale_skeleton_md()), (INBOX_FILE, inbox_skeleton_md())):
        if not (mem / fname).exists():
            (mem / fname).write_text(text, encoding='utf-8')
            created.append(fname)

    for fname, title in TOPIC_FILES:
        if not (mem / fname).exists():
            (mem / fname).write_text(f'# {title}\n', encoding='utf-8')
            created.append(fname)

    if not created:
        print(f'已存在: {mem}（无改动）')
        return
    print(f'已创建/补齐: {", ".join(created)} → {mem}')
    if 'MEMORY.md' in created:
        print('MEMORY.md 骨架不含 memory-schema 标记；条目写完运行 certify 认证。')


def topic_files(mem: Path):
    """主题文件顺序：标准五类优先，其余 *.md 按名称追加（新主题按需新增）。"""
    ordered = [fname for fname, _ in TOPIC_FILES if (mem / fname).exists()]
    extra = sorted(
        p.name for p in mem.glob('*.md')
        if p.name not in NON_TOPIC_FILES and p.name not in ordered
    )
    return ordered + extra


def parse_topic_entries(path: Path):
    """从主题文件提取条目: 返回 [(date, topic, heading_line), ...]，按出现顺序。"""
    entries = []
    for line in path.read_text(encoding='utf-8').splitlines():
        m = TOPIC_HEADING_RE.match(line)
        if m:
            entries.append((m.group('date'), m.group('topic'), line))
    return entries


def parse_entry_blocks_text(text):
    """从主题文件文本提取条目及其正文行: [{date, topic, line, body}, ...]。

    条目边界是「日期标题」到下一个 `## ` 标题：非日期标题也会截断正文，
    避免末尾的说明性小节被算进最后一条条目。
    """
    blocks = []
    current = None
    for line in text.splitlines():
        if line.lstrip().startswith('## ') and not TOPIC_HEADING_RE.match(line):
            current = None
            continue
        m = TOPIC_HEADING_RE.match(line)
        if m:
            current = {
                'date': m.group('date'),
                'topic': m.group('topic'),
                'line': line,
                'body': [],
            }
            blocks.append(current)
        elif current is not None:
            current['body'].append(line)
    for block in blocks:
        block['id'] = get_field_value(block['body'], 'id')
        block['type'] = get_field_value(block['body'], '类型')
    return blocks


def parse_entry_blocks(path: Path):
    return parse_entry_blocks_text(path.read_text(encoding='utf-8'))


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
            m = INDEX_LINE_RE.match(line.strip())
            if m:
                index_entries.setdefault(m.group('date'), []).append(line.strip())
        elif section == 'proposals':
            # 提案区块里出现的任何 YYYY-MM-DD 视为已登记
            for d in re.findall(r'\d{4}-\d{2}-\d{2}', line):
                proposals_listed.add(d)
    return index_entries, proposals_listed, has_entry_section


def section_lines(text, heading):
    """返回 MEMORY.md 中指定 `## heading` 区块的原始行（不含标题行）。"""
    out = []
    active = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('## '):
            active = (stripped[2:].strip() == heading)
            continue
        if active:
            out.append(line)
    return out


def rewrite_section(text, heading, body_lines):
    """把 `## heading` 区块替换为 body_lines；区块缺失时抛 ValueError。"""
    lines = text.splitlines()
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == f'## {heading}':
            start = i
            for j in range(i + 1, len(lines)):
                if lines[j].lstrip().startswith('## '):
                    end = j
                    break
            break
    if start is None:
        raise ValueError(f'MEMORY.md 缺「## {heading}」区块')
    head = lines[:start + 1]
    tail = lines[end:]
    body = [''] + (list(body_lines) if body_lines else ['（无）']) + ['']
    new_lines = head + body + tail
    return '\n'.join(new_lines).rstrip('\n') + '\n'


def field_line(raw):
    """解析列首字段行，返回 (字段名, 值) 或 None。

    字段行必须从第 0 列开始。render_entry 写出的多行「内容」会缩进两格；
    若这里先 strip 再匹配，内容里的 `- 类型: ...` 会被误判成重复字段。
    缩进行属于内容续行，不参与字段解析。
    """
    if not raw or not raw.startswith('-'):
        return None
    m = FIELD_LINE_RE.match(raw)
    if not m:
        return None
    return m.group('name').strip(), m.group('value').strip()


def get_field_value(body, name):
    for line in body:
        parsed = field_line(line)
        if parsed and parsed[0] == name:
            return parsed[1]
    return None


def has_field(body, name):
    return bool(get_field_value(body, name))


def entry_hook(block):
    """索引行用的钩子：优先「钩子」字段，缺省回退「触发」。"""
    return get_field_value(block['body'], '钩子') or get_field_value(block['body'], '触发')


# ---------------------------------------------------------------------------
# 严格行级校验：任何"像记录但解析不了"的行都必须报出来
# ---------------------------------------------------------------------------

def is_blank_or_placeholder(s):
    return not s or s.startswith('#') or s == '（无）' or s in (STALE_TEMPLATE, INBOX_TEMPLATE)


def scan_queue(mem: Path, fname, record_res):
    """逐行扫描队列文件。返回 (records, problems)。

    records 是匹配成功的原始行；problems 是无法解析但显然想写成记录的行
    （以 `-` 开头，或行首就是日期）。静默丢弃会让读侧的失效上报蒸发，
    所以这里必须报出来。
    """
    path = mem / fname
    if not path.exists():
        return [], []
    records, problems = [], []
    for i, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        s = raw.strip()
        if is_blank_or_placeholder(s):
            continue
        if any(r.match(s) for r in record_res):
            records.append(s)
            continue
        if s.startswith('-') or DATE_PREFIX_RE.match(s):
            problems.append(f'{fname}:{i} 无法解析的队列行: {s}')
    return records, problems


def parse_stale_queue(mem: Path):
    """解析 memory/stale.md。返回 (entries, orphans, problems)。

    entries: [(raw_line, date, file, id_or_None, topic_or_None), ...]
    orphans: 主题文件已消失、或目标条目已不存在的队列行
    problems: 无法解析的队列行（v3 用 file#id 定位；v2 的 file :: topic 仍兼容读取）
    """
    records, problems = scan_queue(mem, STALE_FILE, (STALE_LINE_RE, STALE_LEGACY_LINE_RE))
    entries = []
    for raw in records:
        m = STALE_LINE_RE.match(raw)
        if m:
            entries.append((raw, m.group('date'), m.group('file'), m.group('id'), None))
            continue
        m = STALE_LEGACY_LINE_RE.match(raw)
        if m:
            entries.append((raw, m.group('date'), m.group('file'), None, m.group('topic')))

    orphans = []
    cache = {}
    for raw, date, fname, eid, topic in entries:
        target = mem / fname
        if not target.exists():
            orphans.append(f'{raw}（指向的 {fname} 不存在）')
            continue
        if fname not in cache:
            cache[fname] = parse_entry_blocks(target)
        blocks = cache[fname]
        if eid:
            # v3 用 file#id 唯一定位；行首日期是读侧发现失效的日期，
            # 不是条目捕获日，不能拿来和 block['date'] 比对。
            if not any(b['id'] == eid for b in blocks):
                orphans.append(f'{raw}（{fname} 中找不到 id={eid}）')
            continue
        # v2 legacy 没有 id，只能靠标题定位；日期在不同版本里含义不一致
        # （条目捕获日 / 读侧发现日），因此只用标题匹配，避免误报孤立行
        # 导致读侧的失效上报被当成垃圾删掉。
        matched = any(
            t == topic or t.startswith(topic) or topic.startswith(t)
            for _, t in ((b['date'], b['topic']) for b in blocks)
        )
        if not matched:
            orphans.append(f'{raw}（{fname} 中找不到标题接近「{topic}」的条目）')
    return entries, orphans, problems


def parse_inbox(mem: Path):
    """解析 memory/inbox.md。返回 (records, problems)；骨架里的格式示例行逐字跳过。"""
    return scan_queue(mem, INBOX_FILE, (INBOX_LINE_RE,))


def collect_index_line_problems(mem: Path):
    """「## 条目」区块内任何无法解析的非空行。索引是生成物，不该出现自由文本。"""
    path = mem / 'MEMORY.md'
    if not path.exists():
        return []
    problems = []
    in_entries = False
    for i, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        s = raw.strip()
        if s.startswith('## '):
            in_entries = (s[2:].strip() == '条目')
            continue
        if not in_entries or not s or s == '（无）':
            continue
        if INDEX_LINE_RE.match(s):
            continue
        problems.append(f'MEMORY.md:{i} 索引区块内无法解析的行: {s}')
    return problems


def collect_duplicate_fields(mem: Path):
    """同一 block 内已知字段重复出现——第二个会被 get_field_value 静默忽略。"""
    out = []
    for fname in topic_files(mem):
        for block in parse_entry_blocks(mem / fname):
            counts = Counter()
            for line in block['body']:
                parsed = field_line(line)
                if parsed and parsed[0] in KNOWN_FIELDS:
                    counts[parsed[0]] += 1
            for name, n in counts.items():
                if n > 1:
                    out.append(
                        f"{fname} | {block['date']} — {block['topic']} | 字段重复: {name}（×{n}）"
                    )
    return out


def collect_duplicate_ids(mem: Path):
    out = []
    for fname in topic_files(mem):
        seen = Counter()
        for block in parse_entry_blocks(mem / fname):
            eid = block.get('id')
            if eid:
                seen[eid] += 1
        for eid, n in seen.items():
            if n > 1:
                out.append(f'{fname} | id 重复: {eid}（×{n}）')
    return out


def collect_hook_problems(mem: Path):
    """钩子会被渲染进索引行，`→` 是分隔符保留字符，出现在钩子里会让索引不可解析。"""
    out = []
    for fname in topic_files(mem):
        for block in parse_entry_blocks(mem / fname):
            hook = entry_hook(block)
            if not hook:
                continue
            if '→' in hook:
                out.append(
                    f"{fname}#{block.get('id') or '?'} | 钩子/触发含索引保留字符「→」: {hook}"
                )
    return out


def collect_malformed_headings(mem: Path):
    """形似 `## YYYY-MM-DD ...` 但分隔符不合法：过去会被当成普通小节静默跳过。"""
    out = []
    for fname in topic_files(mem):
        for i, raw in enumerate(
            (mem / fname).read_text(encoding='utf-8').splitlines(), 1
        ):
            if MALFORMED_HEADING_RE.match(raw) and not TOPIC_HEADING_RE.match(raw):
                out.append(
                    f'{fname}:{i} 疑似条目标题但无法解析'
                    f'（日期后需要 — / – / - 分隔）: {raw.strip()}'
                )
    return out


def collect_invalid_topic_filenames(mem: Path):
    """主题文件名会进入索引行 `→ <file>#<id>`，含空白/#/→ 时该行不可解析。"""
    out = []
    for fname in topic_files(mem):
        if INVALID_FILENAME_RE.search(fname):
            out.append(
                f'{fname} | 主题文件名含空白、# 或 →，无法生成可解析的索引行（请重命名）'
            )
    return out


def entry_problems(blocks, fname):
    """对一组 block 做条目形状校验，供写前预演与 check 复用。"""
    out = []
    for block in blocks:
        missing = [name for name in REQUIRED_FIELDS if not has_field(block['body'], name)]
        if missing:
            out.append(
                f"{fname} | {block['date']} — {block['topic']} | 缺 {', '.join(missing)}"
            )
        counts = Counter()
        for line in block['body']:
            parsed = field_line(line)
            if parsed and parsed[0] in KNOWN_FIELDS:
                counts[parsed[0]] += 1
        for name, n in counts.items():
            if n > 1:
                out.append(
                    f"{fname} | {block['date']} — {block['topic']} | 字段重复: {name}（×{n}）"
                )
        hook = entry_hook(block)
        if hook and '→' in hook:
            out.append(
                f"{fname}#{block.get('id') or '?'} | 钩子/触发含索引保留字符「→」: {hook}"
            )
    return out


def duplicate_id_problems(blocks, fname):
    out = []
    seen = Counter(block.get('id') for block in blocks if block.get('id'))
    for eid, n in seen.items():
        if n > 1:
            out.append(f'{fname} | id 重复: {eid}（×{n}）')
    return out


def collect_missing_fields(mem: Path):
    out = []
    for fname in topic_files(mem):
        for block in parse_entry_blocks(mem / fname):
            missing = [name for name in REQUIRED_FIELDS if not has_field(block['body'], name)]
            if missing:
                out.append(
                    f"{fname} | {block['date']} — {block['topic']} | 缺 {', '.join(missing)}"
                )
    return out


def collect_anchor_problems(mem: Path):
    """校验条目 id 与索引锚点 file#id。返回问题列表；认证遇到任何一条都阻断。"""
    problems = []
    problems.extend(collect_duplicate_ids(mem))

    entries_by_file = {}
    for fname in topic_files(mem):
        by_id = {}
        for block in parse_entry_blocks(mem / fname):
            eid = block.get('id')
            if eid:
                by_id.setdefault(eid, block)
        entries_by_file[fname] = by_id

    memory_md = mem / 'MEMORY.md'
    if not memory_md.exists():
        return problems

    index_entries, _, _ = parse_index(memory_md)
    anchored = Counter()
    for raws in index_entries.values():
        for raw in raws:
            m = INDEX_LINE_RE.match(raw)
            if not m:
                continue
            fname = m.group('file')
            eid = m.group('id')
            if not eid:
                problems.append(f'索引行缺锚点: {raw.strip()}')
                continue
            if not (mem / fname).exists():
                continue  # 指向文件不存在由 orphan_file 覆盖
            anchored[(fname, eid)] += 1
            if anchored[(fname, eid)] > 1:
                problems.append(f'索引锚点重复: {fname}#{eid}')
            block = entries_by_file.get(fname, {}).get(eid)
            if block is None:
                problems.append(f'索引锚点悬空: {fname}#{eid}（该文件中没有这个 id）')
                continue
            if block['date'] != m.group('date'):
                problems.append(
                    f'锚点日期不匹配: {fname}#{eid}（条目 {block["date"]}，索引 {m.group("date")}）'
                )
            if block.get('type') and block['type'] != m.group('type'):
                problems.append(
                    f'锚点类型不匹配: {fname}#{eid}（条目 {block["type"]}，索引 {m.group("type")}）'
                )

    for fname, by_id in entries_by_file.items():
        for eid in by_id:
            if anchored.get((fname, eid), 0) == 0:
                problems.append(f'条目缺索引: {fname}#{eid}')

    return problems


def collect_evidence_missing(root: Path, mem: Path):
    """检测证据行里带行号标注、但文件已不存在的引用。

    只认列首的「证据」字段（半角/全角冒号都收）；缩进的内容续行不算证据，
    避免内容里顺手写的路径被误当成失效条目。
    """
    evidence_missing = []
    for fname in topic_files(mem):
        current_entry_date = None
        for line in (mem / fname).read_text(encoding='utf-8').splitlines():
            hm = TOPIC_HEADING_RE.match(line)
            if hm:
                current_entry_date = f"{fname} | {hm.group('date')} — {hm.group('topic')}"
                continue
            parsed = field_line(line)
            if not parsed or parsed[0] != '证据':
                continue
            for ref in EVIDENCE_REF_RE.findall(parsed[1]):
                p = ref[0]
                if not (root / p).exists():
                    evidence_missing.append((current_entry_date or fname, p))
    return evidence_missing


def collect_index_state(mem: Path):
    """返回 (index_entries, drift_lines, orphan_file, has_entry_section)。"""
    memory_md = mem / 'MEMORY.md'
    if not memory_md.exists():
        return None, [], [], False

    index_entries, _, has_entry_section = parse_index(memory_md)
    topic_dates = {}
    for fname in topic_files(mem):
        for date, _, _ in parse_topic_entries(mem / fname):
            topic_dates.setdefault(date, []).append(fname)

    drift_lines = []
    if not has_entry_section:
        drift_lines.append('MEMORY.md 缺「## 条目」区块（脚本骨架应有，可能被误删）')
    else:
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

    orphan_file = []
    for raws in index_entries.values():
        for raw in raws:
            m = INDEX_LINE_RE.match(raw)
            if m:
                target = m.group('file')
                if not (mem / target).exists():
                    orphan_file.append(f'{raw}（指向的 {target} 不存在）')
    return index_entries, drift_lines, orphan_file, has_entry_section


def collect_orphan_proposals(mem: Path):
    proposals_dir = mem / 'proposals'
    if not proposals_dir.exists():
        return []
    memory_md = mem / 'MEMORY.md'
    _, proposals_listed, _ = parse_index(memory_md) if memory_md.exists() else (None, set(), False)
    out = []
    for f in sorted(proposals_dir.glob('*.md')):
        stem = f.stem
        date_part = stem[:10]
        if date_part not in proposals_listed:
            out.append(f.name)
    return out


# ---------------------------------------------------------------------------
# 索引生成（R2）
# ---------------------------------------------------------------------------

def render_index_lines(mem: Path):
    """从条目渲染索引行。缺字段 / 钩子含保留字符的条目由 entry_shape_problems 拦截。"""
    lines = []
    for fname in topic_files(mem):
        for block in parse_entry_blocks(mem / fname):
            eid = block.get('id')
            etype = block.get('type')
            hook = entry_hook(block)
            if not eid or not etype or not hook:
                continue
            if '→' in hook:
                continue
            lines.append(f'- [{etype}] {block["date"]} {hook} → {fname}#{eid}')
    return lines


def current_index_lines(mem: Path):
    path = mem / 'MEMORY.md'
    if not path.exists():
        return []
    out = []
    for raw in section_lines(path.read_text(encoding='utf-8'), '条目'):
        s = raw.strip()
        if s and s != '（无）' and INDEX_LINE_RE.match(s):
            out.append(s)
    return out


def collect_index_sync(mem: Path):
    """索引是生成物：与条目渲染结果不一致就是问题（顺序也参与比较）。"""
    path = mem / 'MEMORY.md'
    if not path.exists():
        return []
    rendered = render_index_lines(mem)
    current = current_index_lines(mem)
    if current == rendered:
        return []
    cur, ren = Counter(current), Counter(rendered)
    missing = list((ren - cur).elements())
    extra = list((cur - ren).elements())
    out = ['索引与条目不一致（索引是生成物；运行 certify 或 index 重新生成）:']
    for line in missing[:3]:
        out.append(f'  未生成: {line}')
    for line in extra[:3]:
        out.append(f'  多余: {line}')
    if not missing and not extra:
        out.append('  行内容相同但顺序不一致')
    return out


def entry_shape_problems(mem: Path):
    """写入前的条目形状门禁：文件名、标题、缺字段、字段重复、id 重复、钩子保留字符。"""
    problems = []
    problems.extend(collect_invalid_topic_filenames(mem))
    problems.extend(collect_malformed_headings(mem))
    problems.extend(collect_missing_fields(mem))
    problems.extend(collect_duplicate_fields(mem))
    problems.extend(collect_duplicate_ids(mem))
    problems.extend(collect_hook_problems(mem))
    return problems


def regenerate_index(mem: Path):
    """重建「## 条目」区块。返回问题列表；空表示成功。"""
    problems = entry_shape_problems(mem)
    if problems:
        return problems
    lines = render_index_lines(mem)
    path = mem / 'MEMORY.md'
    try:
        text = rewrite_section(path.read_text(encoding='utf-8'), '条目', lines)
    except ValueError as exc:
        return [str(exc)]
    path.write_text(text, encoding='utf-8')
    return []


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def read_marker(mem: Path):
    """读取 MEMORY.md 的 memory-schema 标记。返回 (status, version)。
       status: no-index | missing | ok | older | newer | malformed
    """
    path = mem / 'MEMORY.md'
    if not path.exists():
        return 'no-index', None
    head = path.read_text(encoding='utf-8').splitlines()[:20]
    for line in head:
        m = MARKER_RE.search(line)
        if m:
            v = int(m.group(1))
            if v == SCHEMA_VERSION:
                return 'ok', v
            if v < SCHEMA_VERSION:
                return 'older', v
            return 'newer', v
    if any('memory-schema' in line and '<!--' in line for line in head):
        return 'malformed', None
    return 'missing', None


def guard_write_version(mem: Path, action: str):
    """写路径的格式版本门禁。返回 True 表示可以继续。

    newer / malformed 一律拒绝：旧技能写新格式会把未知布局改坏。
    missing / older 允许（首次认证与 v2→v3 迁移都依赖写入），older 提示升级。
    """
    if not (mem / 'MEMORY.md').exists():
        print(
            f'{action} 失败：memory/ 未初始化或缺少 MEMORY.md；先运行 init 或 /reflect',
            file=sys.stderr,
        )
        return False
    status, version = read_marker(mem)
    if status == 'newer':
        print(
            f'{action} 失败：记忆格式 v{version} 高于当前技能支持的 v{SCHEMA_VERSION}；'
            '只读，先升级 skill',
            file=sys.stderr,
        )
        return False
    if status == 'malformed':
        print(
            f'{action} 失败：memory-schema 标记无法识别；先人工确认格式并修复标记',
            file=sys.stderr,
        )
        return False
    if status == 'older':
        print(
            f'注意：记忆格式 v{version} 低于当前 v{SCHEMA_VERSION}；'
            '写入将在 certify 时升级标记',
            file=sys.stderr,
        )
    return True


def collect_report(root: Path, mem: Path):
    _, drift, orphan_file, _ = collect_index_state(mem)
    stale_entries, stale_orphans, stale_problems = parse_stale_queue(mem)
    inbox_records, inbox_problems = parse_inbox(mem)
    return {
        'marker': read_marker(mem),
        'has_index': (mem / 'MEMORY.md').exists(),
        'evidence_missing': collect_evidence_missing(root, mem),
        'drift': drift,
        'index_sync': collect_index_sync(mem),
        'index_line_problems': collect_index_line_problems(mem),
        'orphan_file': orphan_file,
        'orphan_proposals': collect_orphan_proposals(mem),
        'stale_entries': stale_entries,
        'stale_orphans': stale_orphans,
        'queue_problems': stale_problems + inbox_problems,
        'inbox': inbox_records,
        'missing_fields': collect_missing_fields(mem),
        'duplicate_fields': collect_duplicate_fields(mem),
        'hook_problems': collect_hook_problems(mem),
        'anchor_problems': collect_anchor_problems(mem),
        'invalid_topic_files': collect_invalid_topic_filenames(mem),
        'malformed_headings': collect_malformed_headings(mem),
    }


def format_report(report):
    signals = []
    status, version = report['marker']

    if not report['has_index']:
        signals.append('MEMORY.md 不存在：不是已知的记忆布局；只读并报告，不要猜测或改写。')
    elif status == 'missing':
        signals.append(
            '未认证：MEMORY.md 缺 memory-schema 标记；确认形状后运行 certify，'
            '转换步骤见 references/memory-conversion.md'
        )
    elif status == 'older':
        signals.append(f'记忆格式 v{version} 低于当前 v{SCHEMA_VERSION}：可运行 /reflect 升级并 certify')
    elif status == 'newer':
        signals.append(
            f'记忆格式 v{version} 高于当前技能支持的 v{SCHEMA_VERSION}：只读，先升级 skill，禁止写入'
        )
    elif status == 'malformed':
        signals.append(
            f'memory-schema 标记无法识别（应为 `<!-- memory-schema: {SCHEMA_VERSION} -->`）'
        )

    if report['evidence_missing']:
        out = ['疑似失效条目（证据文件已消失；需读代码按失效条件裁决，不可据此直接删除）:',
               '条目 | 缺失文件']
        for entry, p in report['evidence_missing']:
            out.append(f'{entry} | {p}')
        signals.append('\n'.join(out))

    if report['drift']:
        signals.append('索引漂移信号:\n' + '\n'.join(report['drift']))

    if report['index_sync']:
        signals.append('\n'.join(report['index_sync']))

    if report['index_line_problems']:
        signals.append(
            '索引区块内有无法解析的行（不再静默忽略；索引是生成物，请删除该行后重新生成）:\n'
            + '\n'.join(report['index_line_problems'])
        )

    if report['orphan_file']:
        signals.append('索引条目指向文件不存在:\n' + '\n'.join(report['orphan_file']))

    if report['missing_fields']:
        signals.append(
            '条目缺必填字段（认证会阻断；补齐或移入 inbox）:\n'
            + '\n'.join(report['missing_fields'])
        )

    if report['duplicate_fields']:
        signals.append(
            '条目字段重复（第二个值会被静默忽略；认证会阻断）:\n'
            + '\n'.join(report['duplicate_fields'])
        )

    if report['hook_problems']:
        signals.append(
            '钩子含索引保留字符（认证会阻断）:\n' + '\n'.join(report['hook_problems'])
        )

    if report['invalid_topic_files']:
        signals.append(
            '主题文件名无法生成可解析索引行（认证会阻断）:\n'
            + '\n'.join(report['invalid_topic_files'])
        )

    if report['malformed_headings']:
        signals.append(
            '疑似条目标题但无法解析（认证会阻断）:\n'
            + '\n'.join(report['malformed_headings'])
        )

    if report['anchor_problems']:
        signals.append(
            '锚点问题（认证会阻断）:\n' + '\n'.join(report['anchor_problems'])
        )

    if report['queue_problems']:
        signals.append(
            '队列文件有无法解析的行（会被静默丢弃，认证会阻断）:\n'
            + '\n'.join(report['queue_problems'])
        )

    if report['orphan_proposals']:
        signals.append(
            '失联提案（proposals/ 下存在但索引「待确认提案」区块未列出，疑似裁决后未清理的残留；与用户确认后删除）:\n'
            + '\n'.join(report['orphan_proposals'])
        )

    if report['stale_entries']:
        out = ['待清理条目（读侧已核验失效，等待本 skill 删除；不是归档，处理后清空队列）:']
        out.extend(raw for raw, *_ in report['stale_entries'])
        signals.append('\n'.join(out))

    if report['stale_orphans']:
        signals.append(
            '待清理队列孤立行（目标条目已不存在，直接删队列行）:\n'
            + '\n'.join(report['stale_orphans'])
        )

    if report['inbox']:
        signals.append(
            '待补队列非空（导入时缺字段的条目；/reflect 逐条处理）:\n'
            + '\n'.join(report['inbox'])
        )

    return signals


def cmd_check(root: Path):
    mem = root / 'memory'
    if not mem.is_dir():
        print(f'无 memory/ 目录: {root}（本仓库尚未沉淀记忆）')
        return

    signals = format_report(collect_report(root, mem))
    if not signals:
        print(
            f'OK: 已认证 memory-schema {SCHEMA_VERSION}，证据文件存在，'
            '索引与条目一致，队列行均可解析且为空，无失联提案'
        )
        return
    print('\n\n'.join(signals))


def write_marker(mem: Path):
    path = mem / 'MEMORY.md'
    lines = path.read_text(encoding='utf-8').splitlines()
    kept = [line for line in lines if not MARKER_RE.search(line)]
    marker = f'<!-- memory-schema: {SCHEMA_VERSION} -->'
    insert_at = 0
    for i, line in enumerate(kept):
        if line.startswith('# '):
            insert_at = i + 1
            break
    kept.insert(insert_at, marker)
    path.write_text('\n'.join(kept) + '\n', encoding='utf-8')


def print_blocking(blocking):
    print('认证失败，未写入标记：')
    for item in blocking:
        print(f'- {item}')
    print('\n明细请运行 check。')


def cmd_certify(root: Path):
    mem = root / 'memory'
    if not mem.is_dir():
        print(f'认证失败：无 memory/ 目录: {root}')
        sys.exit(1)
    if not (mem / 'MEMORY.md').exists():
        print('认证失败：memory/MEMORY.md 不存在')
        sys.exit(1)

    report = collect_report(root, mem)
    status, version = report['marker']
    blocking = []
    if status == 'malformed':
        blocking.append('memory-schema 标记无法识别')
    elif status == 'newer':
        blocking.append(f'记忆格式 v{version} 高于当前技能支持的 v{SCHEMA_VERSION}；先升级 skill')
    # 条目本身形状不合法时不动索引：生成结果会是残缺的。
    if report['missing_fields']:
        blocking.append('存在缺必填字段的条目')
    if report['duplicate_fields']:
        blocking.append('存在字段重复的条目')
    if report['hook_problems']:
        blocking.append('存在钩子含保留字符的条目')
    if report['invalid_topic_files']:
        blocking.append('存在无法生成可解析索引行的主题文件名')
    if report['malformed_headings']:
        blocking.append('存在疑似条目但无法解析的标题')
    if report['index_line_problems']:
        blocking.append('索引区块内存在无法解析的行')

    if blocking:
        print_blocking(blocking)
        sys.exit(1)

    # 索引是生成物：认证时先重建，再做锚点/一致性校验。
    gen_problems = regenerate_index(mem)
    if gen_problems:
        print_blocking([f'无法生成索引: {p}' for p in gen_problems])
        sys.exit(1)

    report = collect_report(root, mem)
    blocking = []
    if report['drift']:
        blocking.append('存在索引漂移')
    if report['index_sync']:
        blocking.append('索引与条目不一致')
    if report['orphan_file']:
        blocking.append('存在指向不存在文件的索引行')
    if report['evidence_missing']:
        blocking.append('存在证据文件已消失的条目')
    if report['missing_fields']:
        blocking.append('存在缺必填字段的条目')
    if report['duplicate_fields']:
        blocking.append('存在字段重复的条目')
    if report['hook_problems']:
        blocking.append('存在钩子含保留字符的条目')
    if report['invalid_topic_files']:
        blocking.append('存在无法生成可解析索引行的主题文件名')
    if report['malformed_headings']:
        blocking.append('存在疑似条目但无法解析的标题')
    if report['anchor_problems']:
        blocking.append('存在锚点问题')
    if report['queue_problems']:
        blocking.append('队列文件存在无法解析的行')

    if blocking:
        print_blocking(blocking)
        sys.exit(1)

    write_marker(mem)
    print(f'已认证: memory-schema {SCHEMA_VERSION}')


def cmd_index(root: Path):
    mem = root / 'memory'
    if not guard_write_version(mem, '生成索引'):
        sys.exit(1)
    problems = regenerate_index(mem)
    if problems:
        print('未生成索引，先修复条目问题：')
        for item in problems:
            print(f'- {item}')
        sys.exit(1)
    print('已重新生成 MEMORY.md「## 条目」索引')


# ---------------------------------------------------------------------------
# 写入子命令（R3）：把畸形数据挡在落盘之前
# ---------------------------------------------------------------------------

def load_payload(path_str):
    try:
        if path_str == '-':
            data = sys.stdin.read()
        else:
            data = Path(path_str).read_text(encoding='utf-8')
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        print(f'payload 不是合法 JSON：{exc}', file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f'读不到 payload：{exc}', file=sys.stderr)
        sys.exit(1)
    if not isinstance(payload, dict):
        print('payload 必须是 JSON 对象', file=sys.stderr)
        sys.exit(1)
    return payload


def normalize_payload(payload):
    out = {}
    for k, v in payload.items():
        out[FIELD_ALIASES.get(k, k)] = v
    return out


def one_line(value):
    return ' '.join(str(value).split())


def render_entry(data):
    lines = [
        f'## {data["捕获于"]} — {one_line(data["主题"])}',
        '',
        f'- id: {data["id"]}',
        f'- 类型: {data["类型"]}',
        f'- 作用域: {data["作用域"]}',
    ]
    if data.get('钩子'):
        lines.append(f'- 钩子: {one_line(data["钩子"])}')
    lines.extend([
        f'- 触发: {one_line(data["触发"])}',
        f'- 证据: {one_line(data["证据"])}',
        f'- 捕获于: {data["捕获于"]}',
        f'- 失效条件: {one_line(data["失效条件"])}',
    ])
    content_lines = str(data['内容']).splitlines()
    lines.append(f'- 内容: {content_lines[0].strip() if content_lines else ""}')
    for extra in content_lines[1:]:
        lines.append(f'  {extra}'.rstrip())
    return '\n'.join(lines) + '\n'


def append_queue_line(path, line, skeleton):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(skeleton, encoding='utf-8')
    lines = [l for l in path.read_text(encoding='utf-8').splitlines() if l.strip() != '（无）']
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append(line)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def today_str():
    import datetime
    return datetime.date.today().isoformat()


def cmd_add(root: Path, payload_path: str):
    mem = root / 'memory'
    if not guard_write_version(mem, '写入'):
        sys.exit(1)
    data = normalize_payload(load_payload(payload_path))

    errors = []
    fname = data.get('file')
    if not fname:
        errors.append('缺 file（目标主题文件，如 pitfalls.md）')
    elif not isinstance(fname, str):
        errors.append(f'file 必须是字符串: {fname}')
    elif fname in NON_TOPIC_FILES or not (mem / fname).exists():
        errors.append(f'file 非法或不存在: {fname}（先 init 或手动建主题文件）')
    elif INVALID_FILENAME_RE.search(fname):
        errors.append(f'file 必须是 memory/ 下的单段文件名（不能含空白、路径分隔符、# 或 →）: {fname}')

    topic = data.get('主题')
    if not topic:
        errors.append('缺 主题（条目的一行标题）')

    eid = data.get('id')
    if not eid:
        errors.append('缺 id')
    elif not ID_PATTERN.match(str(eid)):
        errors.append(f'id 必须是短 ASCII slug（小写字母/数字/._-）: {eid}')

    if data.get('类型') not in TYPES:
        errors.append(f'类型必须是 {"/".join(TYPES)} 之一: {data.get("类型")}')
    if data.get('作用域') not in SCOPES:
        errors.append(f'作用域必须是 {" | ".join(SCOPES)}: {data.get("作用域")}')

    data.setdefault('捕获于', today_str())
    if not DATE_PATTERN.match(str(data.get('捕获于', ''))):
        errors.append(f'捕获于必须是 YYYY-MM-DD: {data.get("捕获于")}')

    for field in REQUIRED_FIELDS:
        if field == 'id':
            continue
        if not str(data.get(field, '')).strip():
            errors.append(f'缺必填字段: {field}')

    hook = data.get('钩子') or data.get('触发')
    if hook and '→' in str(hook):
        errors.append('钩子/触发不能包含索引分隔符「→」，请改用 / 或 ->')

    if errors:
        print('写入失败，未落盘：', file=sys.stderr)
        for item in errors:
            print(f'- {item}', file=sys.stderr)
        sys.exit(1)

    # 写前预演：把新条目并入现有内容后做整文件形状校验。
    # 索引是全文件生成的，任何一条不合法都会导致"条目已写、索引建不出来"的半写状态。
    path = mem / fname
    original = path.read_text(encoding='utf-8')
    combined = original
    if combined and not combined.endswith('\n'):
        combined += '\n'
    if combined.strip():
        combined += '\n'
    combined += render_entry(data)

    prospective = parse_entry_blocks_text(combined)
    problems = entry_problems(prospective, fname)
    problems.extend(duplicate_id_problems(prospective, fname))
    if problems:
        print('写入失败，未落盘（条目形状不合法）：', file=sys.stderr)
        for item in problems:
            print(f'- {item}', file=sys.stderr)
        sys.exit(1)

    path.write_text(combined, encoding='utf-8')
    gen = regenerate_index(mem)
    if gen:
        path.write_text(original, encoding='utf-8')
        print('写入失败，已回滚（索引重建失败）：', file=sys.stderr)
        for item in gen:
            print(f'- {item}', file=sys.stderr)
        sys.exit(1)
    print(f'已写入: {fname}#{eid}；索引已重新生成')


def cmd_stale_add(root: Path, payload_path: str):
    mem = root / 'memory'
    if not guard_write_version(mem, '追加待清理'):
        sys.exit(1)
    data = normalize_payload(load_payload(payload_path))
    errors = []
    fname = data.get('file')
    eid = data.get('id')
    evidence = data.get('evidence') or data.get('证据')
    date = data.get('捕获于') or data.get('date') or today_str()
    if not fname:
        errors.append('缺 file')
    elif not isinstance(fname, str):
        errors.append(f'file 必须是字符串: {fname}')
    elif INVALID_FILENAME_RE.search(fname):
        errors.append(f'file 必须是 memory/ 下的单段文件名（不能含空白、路径分隔符、# 或 →）: {fname}')
    elif not (mem / fname).exists():
        errors.append(f'主题文件不存在: {fname}')
    if not eid:
        errors.append('缺 id')
    elif isinstance(fname, str) and (mem / fname).exists():
        if not any(b.get('id') == eid for b in parse_entry_blocks(mem / fname)):
            errors.append(f'{fname} 中没有 id={eid}（拒绝写入悬空队列行）')
    if not evidence:
        errors.append('缺 evidence（失效证据）')
    if not DATE_PATTERN.match(str(date)):
        errors.append(f'date 必须是 YYYY-MM-DD: {date}')

    line = f'- {date} {fname}#{eid} — {one_line(evidence)}'
    if not errors and not STALE_LINE_RE.match(line):
        errors.append('生成的队列行无法被解析器读取（检查 file / evidence 是否含空白或换行）')

    if errors:
        print('写入失败，未落盘：', file=sys.stderr)
        for item in errors:
            print(f'- {item}', file=sys.stderr)
        sys.exit(1)

    append_queue_line(mem / STALE_FILE, line, stale_skeleton_md())
    print(f'已追加待清理: {fname}#{eid}')


def cmd_inbox_add(root: Path, payload_path: str):
    mem = root / 'memory'
    if not guard_write_version(mem, '追加待补'):
        sys.exit(1)
    data = normalize_payload(load_payload(payload_path))
    source = data.get('source') or data.get('来源')
    missing = data.get('missing') or data.get('缺')
    title = data.get('title') or data.get('主题') or data.get('标题')
    summary = data.get('summary') or data.get('内容')
    errors = []
    if not source:
        errors.append('缺 source（来源路径:行）')
    if not missing:
        errors.append('缺 missing（缺失字段列表）')
    if not title:
        errors.append('缺 title（条目标题）')
    if not summary:
        errors.append('缺 summary（一句话内容）')

    line = (
        f'- [待补] {one_line(source)} | 缺: {one_line(missing)} | '
        f'{one_line(title)} — {one_line(summary)}'
    )
    if not errors and not INBOX_LINE_RE.match(line):
        errors.append('生成的队列行无法被解析器读取（检查 source / title / summary）')

    if errors:
        print('写入失败，未落盘：', file=sys.stderr)
        for item in errors:
            print(f'- {item}', file=sys.stderr)
        sys.exit(1)

    append_queue_line(mem / INBOX_FILE, line, inbox_skeleton_md())
    print(f'已追加待补: {title}')


# ---------------------------------------------------------------------------
# 格式契约（R4）：单一来源，文档引用而不是复述
# ---------------------------------------------------------------------------

def schema_descriptor():
    return {
        'schema_version': SCHEMA_VERSION,
        'entry_heading': '## <YYYY-MM-DD> — <一句话主题>',
        'required_fields': list(REQUIRED_FIELDS),
        'optional_fields': list(OPTIONAL_FIELDS),
        'types': list(TYPES),
        'scopes': list(SCOPES),
        'topic_files': {fname: title for fname, title in TOPIC_FILES},
        'index_line': '- [<类型>] <YYYY-MM-DD> <钩子> → <主题文件>#<id>',
        'index_is_generated': True,
        'index_note': '「## 条目」区块由 index / certify 从条目渲染，禁止手写。',
        'stale_line': STALE_TEMPLATE,
        'inbox_line': INBOX_TEMPLATE,
        'id_pattern': ID_PATTERN.pattern,
        'reserved_in_hook': ['→'],
        'field_line_rule': '字段行必须从第 0 列开始；缩进行视为「内容」续行，不参与字段解析。',
        'topic_filename_rule': '主题文件必须是 memory/ 下的单段文件名，且不得含空白、路径分隔符、# 或 →（索引行无法解析）。',
        'write_cli': {
            'add': 'reflect-memory.py add <payload.json|-> [repo_root]',
            'stale-add': 'reflect-memory.py stale-add <payload.json|-> [repo_root]',
            'inbox-add': 'reflect-memory.py inbox-add <payload.json|-> [repo_root]',
        },
        'add_payload_keys': [
            'file', '主题', 'id', '类型', '作用域', '钩子', '触发',
            '证据', '捕获于', '失效条件', '内容',
        ],
    }


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'schema':
        print(json.dumps(schema_descriptor(), ensure_ascii=False, indent=2))
        return
    if cmd in ('add', 'stale-add', 'inbox-add'):
        if len(argv) < 3:
            usage()
        root = Path(argv[3]) if len(argv) > 3 else detect_repo_root(Path.cwd())
        if cmd == 'add':
            cmd_add(root, argv[2])
        elif cmd == 'stale-add':
            cmd_stale_add(root, argv[2])
        else:
            cmd_inbox_add(root, argv[2])
        return

    root = Path(argv[2]) if len(argv) > 2 else detect_repo_root(Path.cwd())
    if cmd == 'init':
        cmd_init(root)
    elif cmd == 'check':
        cmd_check(root)
    elif cmd == 'certify':
        cmd_certify(root)
    elif cmd == 'index':
        cmd_index(root)
    else:
        usage()


if __name__ == '__main__':
    main(sys.argv)
