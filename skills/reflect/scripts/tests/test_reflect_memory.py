#!/usr/bin/env python3
"""reflect-memory.py 的回归测试（标准库 unittest，Python 3.9+）。

运行:
  python3 -m unittest discover -s reflect/scripts/tests -v

测试分两层：
- CLI 层：subprocess 跑真实命令，验证退出码与落盘结果；
- 单元层：importlib 直接加载脚本，验证解析器与正则契约。
每个用例用独立临时仓库，互不依赖。
"""

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'reflect-memory.py'
SKILL_ROOT = Path(__file__).resolve().parents[3]


def load_module():
    spec = importlib.util.spec_from_file_location('reflect_memory_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = load_module()


class RepoCase(unittest.TestCase):
    """临时仓库 + CLI 调用封装。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / '.git').mkdir()
        self.mem = self.root / 'memory'

    def tearDown(self):
        self._tmp.cleanup()

    # --- CLI ---

    def cli(self, *args, stdin=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin,
            text=True,
            capture_output=True,
            cwd=str(self.root),
        )

    def init(self):
        result = self.cli('init', str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def add(self, **overrides):
        fields = {
            'file': 'dependencies.md',
            '主题': '测试条目',
            'id': 'test-entry',
            '类型': '隐藏依赖',
            '作用域': 'project',
            '触发': '测试触发',
            '证据': '本轮对话',
            '捕获于': '2026-10-24',
            '失效条件': '测试结束',
            '内容': '测试内容。',
        }
        fields.update(overrides)
        return self.cli('add', '-', str(self.root), stdin=self.json_payload(fields))

    def stale_add(self, **overrides):
        fields = {'file': 'dependencies.md', 'id': 'test-entry', 'evidence': '已失效'}
        fields.update(overrides)
        return self.cli('stale-add', '-', str(self.root), stdin=self.json_payload(fields))

    def inbox_add(self, **overrides):
        fields = {
            'source': '/tmp/source.md:1',
            'missing': '触发',
            'title': '待补标题',
            'summary': '一句话内容',
        }
        fields.update(overrides)
        return self.cli('inbox-add', '-', str(self.root), stdin=self.json_payload(fields))

    def check(self):
        return self.cli('check', str(self.root))

    def certify(self):
        return self.cli('certify', str(self.root))

    def index(self):
        return self.cli('index', str(self.root))

    # --- helpers ---

    @staticmethod
    def json_payload(data):
        return json.dumps(data, ensure_ascii=False)

    def read(self, name='MEMORY.md'):
        return (self.mem / name).read_text(encoding='utf-8')

    def write(self, name, text):
        path = self.mem / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def append(self, name, text):
        path = self.mem / name
        path.write_text(path.read_text(encoding='utf-8') + text, encoding='utf-8')

    def snapshots(self):
        return {
            str(p.relative_to(self.mem)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.mem.rglob('*'))
            if p.is_file()
        }

    def certified_repo(self):
        self.init()
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.certify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def set_marker(self, value):
        text = self.read()
        text = re.sub(r'<!--\s*memory-schema:\s*\d+\s*-->', f'<!-- memory-schema: {value} -->', text)
        self.write('MEMORY.md', text)

    def drop_marker(self):
        self.write('MEMORY.md', re.sub(r'<!--\s*memory-schema:\s*\d+\s*-->\n?', '', self.read()))


# ---------------------------------------------------------------------------
# 主链与初始化
# ---------------------------------------------------------------------------

class TestInitAndHappyPath(RepoCase):
    def test_init_creates_skeleton_without_marker(self):
        self.init()
        self.assertIn('## 条目', self.read())
        self.assertNotIn('<!-- memory-schema', self.read())
        for name in ('stale.md', 'inbox.md', 'dependencies.md', 'pitfalls.md',
                     'decisions.md', 'preferences.md', 'facts.md'):
            self.assertTrue((self.mem / name).exists(), name)
        self.assertTrue((self.mem / 'proposals' / '.gitkeep').exists())
        self.assertIn('未认证', self.check().stdout)

    def test_empty_skeleton_certifies(self):
        self.init()
        result = self.certify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('<!-- memory-schema: 3 -->', self.read())
        self.assertIn('OK:', self.check().stdout)

    def test_add_then_certify_then_check_ok(self):
        self.init()
        result = self.add()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('→ dependencies.md#test-entry', self.read())
        self.assertEqual(self.certify().returncode, 0)
        out = self.check().stdout
        self.assertIn('OK:', out)
        self.assertIn('memory-schema 3', out)

    def test_init_is_idempotent(self):
        self.init()
        before = self.snapshots()
        result = self.init()
        self.assertEqual(result.returncode, 0)
        self.assertIn('无改动', result.stdout)
        self.assertEqual(before, self.snapshots())

    def test_init_repairs_missing_memory_md(self):
        self.certified_repo()
        (self.mem / 'MEMORY.md').unlink()
        self.init()
        self.assertTrue((self.mem / 'MEMORY.md').exists())
        self.assertNotIn('不是已知的记忆布局', self.check().stdout)
        # 重建后的骨架是空的，条目还在主题文件里：由 index/certify 重建。
        self.assertEqual(self.certify().returncode, 0)
        self.assertIn('dependencies.md#test-entry', self.read())

    def test_init_repairs_proposals_and_topic_file(self):
        self.init()
        (self.mem / 'proposals' / '.gitkeep').unlink()
        (self.mem / 'proposals').rmdir()
        (self.mem / 'facts.md').unlink()
        result = self.init()
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.mem / 'proposals' / '.gitkeep').exists())
        self.assertTrue((self.mem / 'facts.md').exists())

    def test_check_without_memory(self):
        result = self.check()
        self.assertEqual(result.returncode, 0)
        self.assertIn('无 memory/ 目录', result.stdout)

    def test_schema_contract(self):
        result = self.cli('schema')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['schema_version'], 3)
        self.assertIn('field_line_rule', data)
        self.assertIn('topic_filename_rule', data)
        self.assertIn('id', data['required_fields'])
        self.assertEqual(data['stale_line'], MOD.STALE_TEMPLATE)
        self.assertEqual(data['inbox_line'], MOD.INBOX_TEMPLATE)

    def test_init_preserves_existing_memory_md(self):
        self.certified_repo()
        before = self.read()
        self.init()
        self.assertEqual(before, self.read())

    def test_check_memory_without_index_does_not_crash(self):
        self.mem.mkdir()
        result = self.check()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('不是已知的记忆布局', result.stdout)

    def test_certify_without_memory_md_fails(self):
        self.init()
        (self.mem / 'MEMORY.md').unlink()
        result = self.certify()
        self.assertEqual(result.returncode, 1)
        self.assertIn('MEMORY.md 不存在', result.stdout)


class TestAddValidation(RepoCase):
    def setUp(self):
        super().setUp()
        self.init()

    def assert_rejected(self, result, needle, entry_id):
        self.assertEqual(result.returncode, 1)
        self.assertIn(needle, result.stderr)
        self.assertNotIn(entry_id, self.read('dependencies.md'))

    def test_missing_required_field(self):
        self.assert_rejected(self.add(内容=''), '缺必填字段', 'test-entry')

    def test_hook_with_reserved_arrow(self):
        self.assert_rejected(self.add(钩子='a → b'), '不能包含索引分隔符', 'test-entry')

    def test_invalid_type(self):
        self.assert_rejected(self.add(类型='随便'), '类型必须是', 'test-entry')

    def test_invalid_scope(self):
        self.assert_rejected(self.add(作用域='global'), '作用域必须是', 'test-entry')

    def test_invalid_id(self):
        self.assert_rejected(self.add(id='中文ID'), 'id 必须是短 ASCII slug', '中文ID')

    def test_invalid_captured_date(self):
        self.assert_rejected(self.add(捕获于='2026/10/24'), '捕获于必须是 YYYY-MM-DD', 'test-entry')

    def test_non_string_file_does_not_crash(self):
        result = self.cli(
            'add', '-', str(self.root),
            stdin=self.json_payload({'file': ['x'], '主题': 't', 'id': 't1', '类型': '踩坑',
                                     '作用域': 'project', '触发': 'x', '证据': 'x',
                                     '捕获于': '2026-10-24', '失效条件': 'x', '内容': 'x'}),
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('file 必须是字符串', result.stderr)


class TestEntryRoundTrip(RepoCase):
    def test_multiline_content_is_preserved(self):
        self.init()
        content = '第一行\n- 类型: 内容里的项目符号\n- 证据: 不会被当字段\n第三行'
        result = self.add(内容=content)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.read('dependencies.md')
        self.assertIn('- 内容: 第一行', text)
        self.assertIn('  - 类型: 内容里的项目符号', text)
        self.assertIn('  - 证据: 不会被当字段', text)
        self.assertIn('  第三行', text)
        self.assertEqual(self.certify().returncode, 0)

    def test_hook_falls_back_to_trigger(self):
        self.init()
        result = self.add(触发='跑 notification 测试时', 钩子=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('跑 notification 测试时 → dependencies.md#test-entry', self.read())

    def test_add_preserves_existing_entries(self):
        self.certified_repo()
        result = self.add(id='second-entry', 主题='第二条', 触发='第二条触发')
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.read('dependencies.md')
        self.assertIn('- id: test-entry', text)
        self.assertIn('- id: second-entry', text)
        self.assertEqual(self.read().count('→ dependencies.md#'), 2)
        self.assertEqual(self.certify().returncode, 0)

    def test_stale_add_uses_given_discovery_date(self):
        self.certified_repo()
        result = self.stale_add(date='2026-01-02')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('- 2026-01-02 dependencies.md#test-entry', self.read('stale.md'))

    def test_inbox_title_with_pipe_is_parseable(self):
        self.init()
        result = self.inbox_add(title='A | B')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('无法解析的队列行', self.check().stdout)

    def test_index_preserves_proposal_section(self):
        self.certified_repo()
        text = self.read().replace(
            '## 待确认提案\n\n（无）',
            '## 待确认提案\n\n- [2026-10-24] 提案标题 → proposals/2026-10-24.md',
        )
        self.write('MEMORY.md', text)
        self.assertEqual(self.index().returncode, 0)
        self.assertIn('提案标题', self.read())

    def test_queue_line_with_leading_spaces_is_flagged(self):
        self.certified_repo()
        self.append('stale.md', '   2026-10-24 dependencies.md#test-entry — 缩进日期行\n')
        self.assertIn('无法解析的队列行', self.check().stdout)


# ---------------------------------------------------------------------------
# 字段解析（列首 / 全角冒号 / 内容续行 / 证据）
# ---------------------------------------------------------------------------

class TestFieldParsing(RepoCase):
    def test_content_bullets_that_look_like_fields_are_not_fields(self):
        self.init()
        result = self.add(内容='排查顺序：\n- 类型: 先看类型\n- 证据: 再看证据')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.certify().returncode, 0)
        text = self.read('dependencies.md')
        self.assertEqual(len(re.findall(r'^-\s*类型[:：]', text, re.M)), 1)
        self.assertIn('  - 类型: 先看类型', text)

    def test_fullwidth_colons_accepted_for_fields(self):
        self.certified_repo()
        text = self.read('dependencies.md')
        for name in ('id', '类型', '作用域', '触发', '证据', '捕获于', '失效条件', '内容'):
            text = text.replace(f'- {name}: ', f'- {name}：')
        self.write('dependencies.md', text)
        out = self.check().stdout
        self.assertNotIn('缺必填字段', out)
        self.assertNotIn('字段重复', out)

    def test_fullwidth_evidence_colon_still_checked(self):
        self.init()
        self.add(证据='src/ghost.ts:99')
        self.write('dependencies.md', self.read('dependencies.md').replace('- 证据: ', '- 证据：'))
        self.assertIn('疑似失效条目', self.check().stdout)
        self.assertEqual(self.certify().returncode, 1)

    def test_evidence_with_chinese_line_marker(self):
        self.init()
        self.add(证据='src/ghost.ts 第 12 行')
        self.assertIn('src/ghost.ts', self.check().stdout)

    def test_bare_path_is_not_flagged(self):
        self.init()
        result = self.add(证据='src/ghost.ts')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.check().stdout
        self.assertNotIn('疑似失效条目', out)

    def test_indented_evidence_in_content_is_not_scanned(self):
        self.init()
        result = self.add(内容='排查顺序：\n  - 证据: src/ghost.ts:99')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.check().stdout
        self.assertNotIn('疑似失效条目', out)

    def test_field_line_unit_rules(self):
        self.assertEqual(MOD.field_line('- 类型: 踩坑'), ('类型', '踩坑'))
        self.assertEqual(MOD.field_line('- 类型：踩坑'), ('类型', '踩坑'))
        self.assertIsNone(MOD.field_line('  - 类型: 踩坑'))
        self.assertIsNone(MOD.field_line('普通正文'))


# ---------------------------------------------------------------------------
# 队列严格性
# ---------------------------------------------------------------------------

class TestQueueStrictness(RepoCase):
    def test_date_prefix_line_blocks_certification(self):
        self.certified_repo()
        self.append('stale.md', '2026-10-24 dependencies.md#test-entry — 手写漏了破折号\n')
        self.assertIn('无法解析的队列行', self.check().stdout)
        self.assertEqual(self.certify().returncode, 1)

    def test_missing_dash_separator_blocks_certification(self):
        self.certified_repo()
        self.append('stale.md', '- 2026-10-24 dependencies.md#test-entry 缺破折号\n')
        self.assertIn('无法解析的队列行', self.check().stdout)
        self.assertEqual(self.certify().returncode, 1)

    def test_skeleton_placeholders_are_not_flagged(self):
        self.init()
        out = self.check().stdout
        self.assertNotIn('无法解析的队列行', out)
        self.assertEqual(self.certify().returncode, 0)

    def test_nonempty_queue_does_not_block_certification(self):
        self.certified_repo()
        result = self.stale_add()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('待清理条目', self.check().stdout)
        self.assertEqual(self.certify().returncode, 0)

    def test_legacy_stale_line_is_readable(self):
        self.certified_repo()
        self.append('stale.md', '- 2026-10-24 dependencies.md :: 测试条目 — 旧格式证据\n')
        out = self.check().stdout
        self.assertIn('待清理条目', out)
        self.assertNotIn('孤立行', out)
        self.assertEqual(self.certify().returncode, 0)

    def test_orphan_queue_lines_are_reported(self):
        self.certified_repo()
        self.append(
            'stale.md',
            '- 2026-10-24 dependencies.md#ghost — 不存在的 id\n'
            '- 2026-10-24 missing.md#test-entry — 不存在的文件\n',
        )
        out = self.check().stdout
        self.assertIn('孤立行', out)
        self.assertIn('ghost', out)
        self.assertIn('missing.md', out)

    def test_stale_add_rejects_dangling_id(self):
        self.certified_repo()
        before = self.snapshots()
        result = self.stale_add(id='no-such-id')
        self.assertEqual(result.returncode, 1)
        self.assertIn('拒绝写入悬空队列行', result.stderr)
        self.assertEqual(before, self.snapshots())

    def test_stale_add_non_string_file_does_not_crash(self):
        self.certified_repo()
        result = self.cli(
            'stale-add', '-', str(self.root),
            stdin=self.json_payload({'file': ['x'], 'id': 'test-entry', 'evidence': 'x'}),
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIn('file 必须是字符串', result.stderr)

    def test_stale_add_output_is_parseable(self):
        self.certified_repo()
        self.assertEqual(self.stale_add(evidence='读代码确认 seed 已自动化').returncode, 0)
        records = [line for line in self.read('stale.md').splitlines()
                   if line.startswith('- 2026-')]
        self.assertEqual(len(records), 1)
        self.assertRegex(records[0], MOD.STALE_LINE_RE)

    def test_inbox_source_with_spaces_roundtrip(self):
        self.init()
        result = self.inbox_add(source='/tmp/my notes/x.md:3')
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [line for line in self.read('inbox.md').splitlines()
                   if line.startswith('- [待补]') and '<来源路径>' not in line]
        self.assertEqual(len(records), 1)
        self.assertRegex(records[0], MOD.INBOX_LINE_RE)
        self.assertNotIn('无法解析的队列行', self.check().stdout)
        self.assertEqual(self.certify().returncode, 0)

    def test_inbox_add_requires_initialized_memory(self):
        result = self.inbox_add()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.mem.exists())

    def test_stale_add_requires_initialized_memory(self):
        result = self.stale_add()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.mem.exists())

    def test_date_prefix_regex_unit(self):
        self.assertTrue(MOD.DATE_PREFIX_RE.match('2026-10-24 rest'))
        self.assertFalse(MOD.DATE_PREFIX_RE.match('2026-10-240 rest'))


# ---------------------------------------------------------------------------
# 写入事务与写入器/解析器语法一致
# ---------------------------------------------------------------------------

class TestWriteTransactions(RepoCase):
    def test_add_refuses_broken_target_file_prospectively(self):
        self.certified_repo()
        before = self.read('dependencies.md')
        result = self.add(id='test-entry')  # 同文件 id 重复
        self.assertEqual(result.returncode, 1)
        self.assertIn('未落盘', result.stderr)
        self.assertEqual(before, self.read('dependencies.md'))

    def test_add_rolls_back_when_index_regeneration_fails(self):
        self.certified_repo()
        # 另一个主题文件里的坏条目会让全量索引重建失败，但新条目本身形状合法。
        self.append(
            'pitfalls.md',
            '\n## 2026-10-01 — 坏条目\n\n'
            '- id: broken\n- 类型: 踩坑\n- 类型: 踩坑\n- 作用域: project\n'
            '- 触发: x\n- 证据: 本轮对话\n- 捕获于: 2026-10-01\n'
            '- 失效条件: 无\n- 内容: x\n',
        )
        before = self.read('dependencies.md')
        result = self.add(id='new-entry', 主题='新条目')
        self.assertEqual(result.returncode, 1)
        self.assertIn('已回滚', result.stderr)
        self.assertEqual(before, self.read('dependencies.md'))
        self.assertNotIn('new-entry', self.read('dependencies.md'))

    def test_add_duplicate_id_rejected(self):
        self.certified_repo()
        result = self.add(id='test-entry', 主题='重复')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.read('dependencies.md').count('- id: test-entry'), 1)

    def test_add_rejects_topic_filename_with_space(self):
        self.init()
        self.write('my notes.md', '# 自定义\n')
        result = self.add(file='my notes.md', id='space-file')
        self.assertEqual(result.returncode, 1)
        self.assertIn('单段文件名', result.stderr)
        self.assertNotIn('space-file', self.read('my notes.md'))

    def test_add_rejects_topic_path(self):
        self.init()
        (self.mem / 'sub').mkdir()
        self.write('sub/notes.md', '# 子目录\n')
        result = self.add(file='sub/notes.md', id='path-file')
        self.assertEqual(result.returncode, 1)
        self.assertIn('单段文件名', result.stderr)

    def test_invalid_topic_filename_blocks_certify(self):
        self.init()
        self.write('my notes.md', '# 自定义\n')
        out = self.check().stdout
        self.assertIn('主题文件名', out)
        self.assertEqual(self.certify().returncode, 1)

    def test_stale_add_rejects_space_filename(self):
        self.certified_repo()
        self.write('my notes.md', '# 自定义\n')
        result = self.stale_add(file='my notes.md')
        self.assertEqual(result.returncode, 1)
        self.assertIn('单段文件名', result.stderr)


# ---------------------------------------------------------------------------
# 格式版本写保护
# ---------------------------------------------------------------------------

class TestVersionGuards(RepoCase):
    def test_newer_schema_blocks_every_write_command(self):
        self.certified_repo()
        self.set_marker(4)
        before = self.snapshots()
        self.assertNotEqual(self.add(id='x').returncode, 0)
        self.assertNotEqual(self.index().returncode, 0)
        self.assertNotEqual(self.stale_add().returncode, 0)
        self.assertNotEqual(self.inbox_add().returncode, 0)
        self.assertEqual(before, self.snapshots())
        self.assertIn('高于当前技能支持', self.check().stdout)

    def test_malformed_marker_blocks_writes(self):
        self.certified_repo()
        text = re.sub(r'<!--\s*memory-schema:\s*\d+\s*-->', '<!-- memory-schema: x -->', self.read())
        self.write('MEMORY.md', text)
        before = self.snapshots()
        self.assertEqual(self.add(id='x').returncode, 1)
        self.assertEqual(self.index().returncode, 1)
        self.assertEqual(before, self.snapshots())

    def test_older_schema_allows_add_then_upgrades(self):
        self.certified_repo()
        self.set_marker(2)
        result = self.add(id='newer-entry', 主题='旧格式仓库新增')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('低于当前', result.stderr)
        self.assertEqual(self.certify().returncode, 0)
        self.assertIn('<!-- memory-schema: 3 -->', self.read())

    def test_missing_marker_allows_add_then_certify(self):
        self.certified_repo()
        self.drop_marker()
        self.assertEqual(self.add(id='no-marker', 主题='无标记').returncode, 0)
        self.assertEqual(self.certify().returncode, 0)
        self.assertIn('<!-- memory-schema: 3 -->', self.read())

    def test_prose_mentioning_marker_is_missing_not_malformed(self):
        self.certified_repo()
        self.drop_marker()
        self.write('MEMORY.md', self.read().replace('# MEMORY', '# MEMORY\n\n本文提到 memory-schema 但没有标记。', 1))
        result = self.add(id='prose-entry', 主题='正文提到标记')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('无法识别', result.stderr)


# ---------------------------------------------------------------------------
# 标题与索引
# ---------------------------------------------------------------------------

ENTRY_TEMPLATE = (
    '\n## 2026-10-24 {sep} {topic}\n\n'
    '- id: {eid}\n- 类型: 情境事实\n- 作用域: project\n'
    '- 触发: 测试\n- 证据: 本轮对话\n- 捕获于: 2026-10-24\n'
    '- 失效条件: 无\n- 内容: 内容。\n'
)


class TestHeadingsAndIndex(RepoCase):
    def test_en_dash_heading_is_indexed(self):
        self.init()
        self.append('facts.md', ENTRY_TEMPLATE.format(sep='–', topic='en dash', eid='en1'))
        result = self.index()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('facts.md#en1', self.read())
        self.assertEqual(self.certify().returncode, 0)

    def test_hyphen_heading_is_indexed(self):
        self.init()
        self.append('facts.md', ENTRY_TEMPLATE.format(sep='-', topic='hyphen', eid='hy1'))
        self.assertEqual(self.index().returncode, 0)
        self.assertIn('facts.md#hy1', self.read())

    def test_malformed_heading_is_reported_and_blocks(self):
        self.init()
        self.append('facts.md', '\n## 2026-10-24 没有分隔符\n\n- id: bad\n')
        out = self.check().stdout
        self.assertIn('疑似条目标题但无法解析', out)
        self.assertEqual(self.certify().returncode, 1)
        self.assertEqual(self.index().returncode, 1)

    def test_legacy_index_line_rebuilt_with_anchor(self):
        self.certified_repo()
        text = re.sub(
            r'^- \[隐藏依赖\] .*$',
            '- [隐藏依赖] 2026-10-24 测试触发 → dependencies.md',
            self.read(),
            flags=re.M,
        )
        self.write('MEMORY.md', text)
        out = self.check().stdout
        self.assertTrue('不一致' in out or '缺锚点' in out)
        self.assertEqual(self.certify().returncode, 0)
        self.assertIn('dependencies.md#test-entry', self.read())

    def test_orphan_proposal_is_reported(self):
        self.certified_repo()
        (self.mem / 'proposals' / '2026-10-24.md').write_text('# 提案\n', encoding='utf-8')
        self.assertIn('失联提案', self.check().stdout)


# ---------------------------------------------------------------------------
# 文档同步（机械断言，防止迭代把口径改回去）
# ---------------------------------------------------------------------------

class TestDocConsistency(unittest.TestCase):
    def read_doc(self, relative):
        return (SKILL_ROOT / relative).read_text(encoding='utf-8')

    def test_receipt_does_not_append_second_arrow(self):
        text = self.read_doc('project-entry/SKILL.md')
        self.assertNotIn('<逐字引用命中的索引行原文> → <file>', text)
        self.assertIn('不要再补一层', text)

    def test_reflect_does_not_teach_manual_index_edits(self):
        text = self.read_doc('reflect/SKILL.md')
        for phrase in (
            '补索引行',
            '改正索引行的',
            '同步删除 `MEMORY.md` 对应索引行',
            '同步清理 `MEMORY.md` 索引对应行',
        ):
            self.assertNotIn(phrase, text)

    def test_format_authority_points_to_schema_output(self):
        text = self.read_doc('reflect/references/memory-conversion.md')
        self.assertIn('reflect-memory.py schema', text)
        self.assertNotIn('以 `SKILL.md` 的「记忆条目格式」「存储布局」为准', text)

    def test_init_doc_says_marker_comes_from_certify(self):
        text = self.read_doc('reflect/SKILL.md')
        self.assertIn('不由 `init` 预写', text)


if __name__ == '__main__':
    unittest.main()
