#!/usr/bin/env python3
# repo-hygiene.py — 仓库卫生巡检机械信号扫描（repo-hygiene skill）
#
# 用法:
#   repo-hygiene.py [repo_root]     默认当前目录；markdown 信号报告输出到 stdout
#
# 职责边界：只做机械信号检测与统计，不修改任何文件、不执行删除。
# 输出是疑似清单——信号是否成立由 agent 核实，如何处置由用户裁决。
#
# 兼容性：Python 3.9+（避免 match 语法），纯 stdlib；git 相关检测在非 git 仓库自动跳过。

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# walk 剪枝：重型产物/依赖目录，任何层级命中目录名即跳过
PRUNE_DIRS = {
    'node_modules', '.git', '.next', '.turbo', '__pycache__', 'coverage',
    '.pnpm-store', 'dist', 'out', 'build', '.cache', 'Library',
}


def is_pruned(dirname, extra=()):
    """venv 系目录名允许变体（.venv-svg 等），统一前缀匹配。"""
    return dirname in PRUNE_DIRS or dirname in extra or dirname.startswith('.venv') or dirname == 'venv'
# 空壳目录判定：目录内容若为此集合的子集（或为空）即为空壳；
# .gitkeep/.keep 是有意的空目录占位声明，不算空壳
SHELL_ONLY_FILES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}

# 会再生的标准产物路径：ignore 条目指向它们、当前树上不存在属正常，不做化石判定
KNOWN_REGEN = {'dist', 'out', 'build', 'coverage', '.next', '.turbo', '.cache',
               '.env', '.env.local', '.vscode', '.idea', '.wrangler', 'node_modules'}

SCRIPT_EXTS = {'.mjs', '.cjs', '.js', '.mts', '.ts', '.cts', '.py', '.sh'}
SCRIPT_DIR_CANDIDATES = ['scripts', 'tooling', 'tools', 'bin']
# 过程产物区默认候选；仓库使用其他位置时用 --areas=路径1,路径2 覆盖
PROCESS_AREAS = ['docs/temp', '.zcode/plans', '.claude/plans', '.codex/plans',
                 'tmp', '.tmp', 'output']

# 无入口脚本的引用语料：包清单、构建/CI 定义、README（文档提及 = 可发现）
CORPUS_FILES = {'package.json', 'pyproject.toml', 'setup.py', 'setup.cfg', 'tox.ini',
                'makefile', 'justfile', 'taskfile.yml', 'readme.md', '.gitlab-ci.yml'}

STATUS_RE = re.compile(r'(status|state|状态)\s*[:：]', re.IGNORECASE)
GLOB_CHARS = set('*?[')


def gitignored_top_dirs(root):
    """从 .gitignore 提取被忽略的一级目录（无 glob、无层级路径），供 walk 剪枝。
    被 ignore 的目录树内容不是仓库资产，不参与空壳/无入口/悬空扫描；
    PROCESS_AREAS 的首段豁免——它们是过程产物检测的显式对象。"""
    exempt = {area.split('/')[0] for area in PROCESS_AREAS}
    ignored = set()
    gitignore = root / '.gitignore'
    if not gitignore.exists():
        return ignored
    for raw in gitignore.read_text(errors='replace').splitlines():
        line = raw.strip().lstrip('/').rstrip('/')
        if not line or line.startswith('#') or line.startswith('!'):
            continue
        if any(c in line for c in GLOB_CHARS) or '/' in line:
            continue
        if line not in exempt:
            ignored.add(line)
    return ignored


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return '%.1f%s' % (n, unit) if unit != 'B' else '%dB' % n
        n /= 1024.0


def is_git_repo(root):
    r = subprocess.run(['git', '-C', str(root), 'rev-parse', '--is-inside-work-tree'],
                       capture_output=True)
    return r.returncode == 0


def load_repo_config(root):
    """仓库自声明 .repo-hygiene.json：仓库把自己的特异性知识（过程区位置、
    额外剪枝、跳过的检测项）声明在仓库内，脚本读声明而非预设枚举去追所有仓库。
    支持键：process_areas(list, 覆盖默认)、extra_prune(list, 并入剪枝)、skip_checks(list, 如 ["5"])。"""
    cfg_path = root / '.repo-hygiene.json'
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(errors='replace'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def repo_profile(root, extra=(), top_n=8):
    """一级目录体量 top N。过程产物区的本质特征是体量大、churn 高，
    枚举已知目录名会过期，测量不会——异常目录自己在轮廓上浮出来。"""
    stats = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_pruned(d, extra)]
        rel = os.path.relpath(dirpath, root)
        first = '.' if rel == '.' else rel.split(os.sep)[0]
        count, size = stats.get(first, (0, 0))
        for name in filenames:
            try:
                sz = (Path(dirpath) / name).stat().st_size
            except OSError:
                sz = 0
            count += 1
            size += sz
        stats[first] = (count, size)
    return sorted(stats.items(), key=lambda kv: kv[1][1], reverse=True)[:top_n]


# --- 检测 1: gitignore 反向漏（被追踪但命中 ignore 规则）---

def check_tracked_but_ignored(root):
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'],
                             capture_output=True).stdout
    if not tracked:
        return []
    out = subprocess.run(
        ['git', '-C', str(root), 'check-ignore', '--stdin', '--no-index', '-v', '-z'],
        input=tracked, capture_output=True).stdout
    # -v -z 记录格式: source\0 linenum\0 pattern\0 pathname\0 循环
    fields = out.split(b'\0')
    hits = []
    i = 0
    while i + 3 < len(fields):
        source = fields[i].decode(errors='replace')
        lineno = fields[i + 1].decode(errors='replace')
        pattern = fields[i + 2].decode(errors='replace')
        path = fields[i + 3].decode(errors='replace')
        if path and not pattern.startswith('!'):
            # 否定规则（!.gitignore 等）命中是"明确要追踪"的声明，不算反向漏
            hits.append((path, pattern, '%s:%s' % (source, lineno)))
        i += 4
    return hits


# --- 检测 2/3: 化石与重复 ignore 条目 ---

def check_ignore_entries(root):
    gitignore = root / '.gitignore'
    if not gitignore.exists():
        return [], []
    fossils, dups = [], []
    seen = {}
    for lineno, raw in enumerate(gitignore.read_text(errors='replace').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith('!'):
            continue
        norm = line.lstrip('/').rstrip('/')
        if norm in seen:
            dups.append((lineno, line, seen[norm]))
        else:
            seen[norm] = lineno
        if norm in KNOWN_REGEN:
            continue  # 标准产物路径当前不存在属正常，不做化石判定（重复检测不受影响）
        if any(c in line for c in GLOB_CHARS):
            continue  # 通配规则无法静态判定存在性，跳过
        # 不带斜杠的 pattern 匹配任意层级，这里只查根层（启发式，输出标注疑似）
        candidate = root / norm
        if not os.path.lexists(str(candidate)):
            fossils.append((lineno, line))
    return fossils, dups


# --- 检测 4: 空壳目录 ---

def walk_dirs(root, extra_prune=()):
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_pruned(d, extra_prune)]
        yield dirpath, dirnames


def check_shell_dirs(root):
    shells = []
    for dirpath, _ in walk_dirs(root, gitignored_top_dirs(root)):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            entries = set(os.listdir(dirpath))
        except OSError:
            continue
        if not entries or entries <= SHELL_ONLY_FILES:
            shells.append(str(p.relative_to(root)) + '/')
    return shells


# --- 检测 5: 无入口脚本（疑似） ---

def collect_reference_corpus(root):
    """walk 全仓收集语料（剪枝后），适配任意 monorepo 布局与非 JS 生态；
    若用固定 glob（apps/*/packages/*/）会漏掉其他布局，导致无入口检测在
    非 JS 仓库误报爆炸。"""
    corpus = []
    prune = PRUNE_DIRS | gitignored_top_dirs(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in prune]
        for name in filenames:
            lower = name.lower()
            is_ci = 'workflows' in dirpath and lower.endswith(('.yml', '.yaml'))
            if lower in CORPUS_FILES or is_ci:
                f = Path(dirpath) / name
                try:
                    if f.stat().st_size <= 1024 * 1024:
                        corpus.append(f.read_text(errors='replace'))
                except OSError:
                    pass
    return '\n'.join(corpus)


def check_orphan_scripts(root):
    extra = gitignored_top_dirs(root)
    candidates = []
    for dirname in SCRIPT_DIR_CANDIDATES:
        base = root / dirname
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not is_pruned(d, extra)]
            for name in filenames:
                f = Path(dirpath) / name
                if f.suffix not in SCRIPT_EXTS or name.endswith('.d.ts'):
                    continue
                # 测试文件由运行器按 glob 发现，无需入口引用
                if '__tests__' in f.parts or '.test.' in name or '.spec.' in name:
                    continue
                candidates.append(f)
    if not candidates:
        return []
    corpus = collect_reference_corpus(root)
    # 库文件豁免：basename 被其他候选脚本内容引用的，是被 import 的工具库而非入口脚本
    contents = {}
    for f in candidates:
        try:
            if f.stat().st_size <= 512 * 1024:
                contents[f] = f.read_text(errors='replace')
        except OSError:
            pass
    orphans = []
    for f in candidates:
        rel = str(f.relative_to(root))
        if f.name in corpus or rel in corpus:
            continue
        # TS/JS import 常省略扩展名：按 import 路径形态匹配 stem（'./shared'、"@/dir/shared"）
        stem_re = re.compile(
            r'[\'"`](?:\.{1,2}/|@/)?(?:[\w-]+/)*' + re.escape(f.stem) + r'[\'"`]')
        if any(f.name in body or stem_re.search(body)
               for g, body in contents.items() if g != f):
            continue
        orphans.append(rel)
    return orphans


# --- 检测 6: 悬空 $schema 引用 ---

def check_dangling_schema(root):
    dangling = []
    extra = gitignored_top_dirs(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not is_pruned(d, extra)]
        for name in filenames:
            if not name.endswith('.json') or 'lock' in name:
                continue
            f = Path(dirpath) / name
            try:
                if f.stat().st_size > 1024 * 1024:
                    continue
                data = json.loads(f.read_text(errors='replace'))
            except (OSError, ValueError):
                continue
            schema = data.get('$schema') if isinstance(data, dict) else None
            if isinstance(schema, str) and schema.startswith('.'):
                target = (f.parent / schema).resolve()
                if not target.exists():
                    dangling.append((str(f.relative_to(root)), schema))
    return dangling


# --- 检测 7: 过程产物堆积 ---

def file_stem_key(name):
    stem = Path(name).stem.lower()
    # 主题在 plan 标记之前：xxx-global-plan / xxx-sub-plan-N-描述 / xxx-plan
    key = re.split(r'[-_ ](?:global[-_ ]?plan|sub[-_ ]?plan|plan)', stem)[0]
    return key.strip('-_ ')


def check_process_areas(root, now, areas):
    reports = []
    for area in areas:
        base = root / area
        if not base.is_dir():
            continue
        files = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not is_pruned(d)]
            for name in filenames:
                f = Path(dirpath) / name
                try:
                    st = f.stat()
                except OSError:
                    continue
                files.append((f, st))
        if not files:
            continue
        total = sum(st.st_size for _, st in files)
        age_buckets = {'<7d': 0, '7-30d': 0, '>30d': 0}
        no_status = 0
        clusters = {}
        for f, st in files:
            age_days = (now - st.st_mtime) / 86400.0
            if age_days < 7:
                age_buckets['<7d'] += 1
            elif age_days < 30:
                age_buckets['7-30d'] += 1
            else:
                age_buckets['>30d'] += 1
            if f.suffix == '.md':
                try:
                    head = f.read_text(errors='replace')[:3000]
                except OSError:
                    head = ''
                if not STATUS_RE.search(head):
                    no_status += 1
                key = file_stem_key(f.name)
                # 聚类语义是"plan 同主题重攻"，非 plan 命名（如每任务目录同构的 manifest.md）不参与
                if key and 'plan' in f.name.lower():
                    clusters.setdefault(key, []).append(f.name)
        big_clusters = {k: v for k, v in clusters.items() if len(v) >= 3}
        reports.append({
            'area': area, 'count': len(files), 'size': total,
            'ages': age_buckets, 'no_status': no_status, 'clusters': big_clusters,
        })
    return reports


# --- 报告组织 ---

def section(lines, title, items, formatter, empty_note='无'):
    lines.append('## %s' % title)
    lines.append('')
    if not items:
        lines.append(empty_note)
    else:
        for it in items:
            lines.append(formatter(it))
        lines.append('')
        lines.append('**小计：%d**' % len(items))
    lines.append('')


def main():
    args = sys.argv[1:]
    cli_areas = None
    root_arg = None
    for a in args:
        if a.startswith('--areas='):
            cli_areas = [p.strip() for p in a[len('--areas='):].split(',') if p.strip()]
        elif not a.startswith('--'):
            root_arg = a
    root = Path(root_arg or '.').resolve()

    cfg = load_repo_config(root)
    # 优先级：CLI --areas > 仓库自声明 process_areas > 默认表
    if cli_areas is not None:
        areas = cli_areas
    elif isinstance(cfg.get('process_areas'), list):
        areas = [str(p) for p in cfg['process_areas']]
    else:
        areas = list(PROCESS_AREAS)
    cfg_prune = set(str(p) for p in cfg.get('extra_prune', [])) if isinstance(cfg.get('extra_prune'), list) else set()
    skip_checks = set(str(c) for c in cfg.get('skip_checks', [])) if isinstance(cfg.get('skip_checks'), list) else set()

    now = time.time()
    lines = ['# 仓库卫生巡检信号', '',
             '- 仓库：`%s`' % root,
             '- 性质：机械信号疑似清单，是否成立需核实，如何处置由用户裁决']
    if cfg:
        lines.append('- 仓库自声明：已加载 `.repo-hygiene.json`（%s）'
                     % '、'.join(sorted(cfg.keys())))
    lines.append('')

    extra = gitignored_top_dirs(root) | cfg_prune
    profile = repo_profile(root, extra)
    lines.append('## 0. 仓库轮廓（一级目录体量 top %d）' % len(profile))
    lines.append('')
    lines.append('| 目录 | 文件数 | 大小 |')
    lines.append('|---|---|---|')
    for name, (count, size) in profile:
        lines.append('| `%s` | %d | %s |' % (name, count, human_size(size)))
    lines.append('')
    lines.append('轮廓上的异常目录（体量大、陌生）即使无检测项命中，也应在核实阶段主动环顾判断。')
    lines.append('')

    if is_git_repo(root):
        if '1' not in skip_checks:
            hits = check_tracked_but_ignored(root)
            section(lines, '1. gitignore 反向漏（被追踪但命中 ignore 规则）', hits,
                    lambda h: '- `%s` ← 规则 `%s`（%s）' % (h[0], h[1], h[2]))
        if '2' not in skip_checks or '3' not in skip_checks:
            fossils, dups = check_ignore_entries(root)
            if '2' not in skip_checks:
                section(lines, '2. 化石 ignore 条目（指向路径不存在，疑似）', fossils,
                        lambda f: '- .gitignore:%d `%s`' % (f[0], f[1]))
            if '3' not in skip_checks:
                section(lines, '3. 重复 ignore 条目', dups,
                        lambda d: '- .gitignore:%d `%s`（与 :%d 等价）' % (d[0], d[1], d[2]))
    else:
        lines.append('## 1-3. git 相关检测')
        lines.append('')
        lines.append('跳过：当前目录不是 git 仓库。')
        lines.append('')

    if '4' not in skip_checks:
        shells = check_shell_dirs(root)
        # 按（祖父路径, 目录名）形态分组：脚手架生成的结构性空目录（如 packages/*/resources/）
        # 共享同一形态，≥3 折叠为一行，防淹没真信号
        by_shape = {}
        for s in shells:
            parts = s.rstrip('/').split('/')
            basename = parts[-1]
            grandparent = '/'.join(parts[:-2]) if len(parts) > 2 else '.'
            by_shape.setdefault((grandparent, basename), []).append(s)
        shell_lines = []
        for (grandparent, basename) in sorted(by_shape):
            group = by_shape[(grandparent, basename)]
            if len(group) >= 3:
                examples = ', '.join('`%s`' % g for g in group[:2])
                shell_lines.append('- `%s/*/%s/` 形态 %d 处（%s …）'
                                   % (grandparent, basename, len(group), examples))
            else:
                shell_lines.extend('- `%s`' % g for g in group)
        lines.append('## 4. 空壳目录（只含占位/系统文件或为空，同形态 ≥3 折叠）')
        lines.append('')
        if not shell_lines:
            lines.append('无')
        else:
            lines.extend(shell_lines)
            lines.append('')
            lines.append('**小计：%d**' % len(shells))
        lines.append('')

    if '5' not in skip_checks:
        orphans = check_orphan_scripts(root)
        section(lines, '5. 无入口脚本（不被 package.json / CI 引用，疑似）', orphans,
                lambda s: '- `%s`' % s)

    if '6' not in skip_checks:
        dangling = check_dangling_schema(root)
        section(lines, '6. 悬空 $schema 引用（指向文件不存在）', dangling,
                lambda d: '- `%s` → `$schema: %s`' % (d[0], d[1]))

    if '7' not in skip_checks:
        lines.append('## 7. 过程产物堆积（plan/temp 区）')
        lines.append('')
        reports = check_process_areas(root, now, areas)
        if not reports:
            lines.append('无（未发现过程产物区）')
            lines.append('')
        for r in reports:
            lines.append('### `%s/`' % r['area'])
            lines.append('')
            lines.append('- 文件 %d 个，共 %s；年龄分布：<7d %d / 7-30d %d / >30d %d'
                         % (r['count'], human_size(r['size']),
                            r['ages']['<7d'], r['ages']['7-30d'], r['ages']['>30d']))
            lines.append('- 无状态头（status/状态 字段）的 md：%d 个' % r['no_status'])
            if r['clusters']:
                lines.append('- 同主题聚类（≥3 份，疑似反复重攻）：')
                for key, names in sorted(r['clusters'].items()):
                    lines.append('  - 主题 `%s`：%d 份（%s）'
                                 % (key, len(names), ', '.join(sorted(names)[:4])
                                    + (' …' if len(names) > 4 else '')))
            lines.append('')

    print('\n'.join(lines))


if __name__ == '__main__':
    main()
