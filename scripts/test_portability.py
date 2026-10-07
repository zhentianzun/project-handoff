"""隔离验证跨项目、跨agent检查点及恢复边界，不触碰实际项目。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import init_project

rt = init_project.runtime


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='handoff_portable_')
        self.root = Path(self.tmp.name) / '中文 project'
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def setup_project(self, sources=None):
        init_project.initialize(self.root, '任意项目', sources, True)
        return rt.load(self.root)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(self.root / 'tools/handoff.py'), *args],
                              capture_output=True, text=True, encoding='utf-8')

    def test_dry_run_writes_nothing(self):
        plan = init_project.initialize(self.root, '项目')
        self.assertIn('create', plan)
        self.assertEqual([], list(self.root.iterdir()))

    def test_plain_non_git_project(self):
        state = self.setup_project()
        self.assertEqual('unversioned', state['local']['commit'])
        self.assertEqual([], rt.check(self.root, state)[0])
        self.assertEqual(0, self.run_tool('check').returncode)

    def test_git_project(self):
        rt.git(self.root, 'init', '-q')
        (self.root / 'src').mkdir()
        (self.root / 'src/a.py').write_text('x=1\n', encoding='utf-8')
        rt.git(self.root, 'add', 'src/a.py')
        rt.git(self.root, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
               '-c', 'commit.gpgsign=false', 'commit', '-qm', 'baseline')
        state = self.setup_project(['src'])
        self.assertEqual(40, len(state['local']['commit']))
        self.assertEqual(0, self.run_tool('check').returncode)

    def test_parent_git_is_not_project_baseline(self):
        rt.git(self.root.parent, 'init', '-q')
        self.assertEqual('unversioned', self.setup_project()['local']['commit'])

    def test_override_and_rules_preserved(self):
        (self.root / 'AGENTS.md').write_text('普通规则', encoding='utf-8')
        override = self.root / 'AGENTS.override.md'
        override.write_text('必须保留人工规则', encoding='utf-8')
        state = self.setup_project()
        self.assertEqual(['AGENTS.override.md'], state['project']['entry_files'])
        self.assertIn('必须保留人工规则', override.read_text(encoding='utf-8'))
        self.assertEqual('普通规则', (self.root / 'AGENTS.md').read_text(encoding='utf-8'))

    def test_repeated_init_does_not_overwrite(self):
        self.setup_project()
        before = (self.root / rt.STATE).read_bytes()
        with self.assertRaises(ValueError):
            init_project.initialize(self.root, '换个名字', apply=True)
        self.assertEqual(before, (self.root / rt.STATE).read_bytes())

    def test_name_collision_before_mutation(self):
        (self.root / 'tools').mkdir()
        target = self.root / 'tools/handoff.py'
        target.write_text('别人的工具', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.setup_project()
        self.assertFalse((self.root / 'docs').exists())
        self.assertEqual('别人的工具', target.read_text(encoding='utf-8'))

    def test_escape_source_refused(self):
        with self.assertRaises(ValueError):
            init_project.initialize(self.root, '项目', ['../outside'], True)
        self.assertFalse((self.root / 'docs').exists())

    def test_code_drift_and_new_file_are_visible(self):
        (self.root / 'src').mkdir()
        (self.root / 'src/a.py').write_text('x=1', encoding='utf-8')
        self.setup_project(['src'])
        (self.root / 'src/new.py').write_text('x=2', encoding='utf-8')
        self.assertNotEqual(0, self.run_tool('check').returncode)

    def test_binary_hash_does_not_normalize(self):
        (self.root / 'assets').mkdir()
        (self.root / 'assets/a.bin').write_bytes(b'a\r\nb')
        state = self.setup_project(['assets'])
        old = state['local']['source_hashes']['assets/a.bin']
        (self.root / 'assets/a.bin').write_bytes(b'a\nb')
        self.assertNotEqual(old, rt.source_hashes(self.root, state)['assets/a.bin'])

    def test_text_line_endings_do_not_fake_drift(self):
        (self.root / 'src').mkdir()
        (self.root / 'src/a.py').write_bytes(b'x=1\n')
        self.setup_project(['src'])
        (self.root / 'src/a.py').write_bytes(b'x=1\r\n')
        self.assertEqual(0, self.run_tool('check').returncode)

    def test_checkpoint_does_not_hide_uncommitted_code(self):
        (self.root / 'src').mkdir()
        (self.root / 'src/a.py').write_text('x=1', encoding='utf-8')
        before = self.setup_project(['src'])
        (self.root / 'src/a.py').write_text('x=2', encoding='utf-8')
        result = self.run_tool('checkpoint', '--owner', 'agent-A', '--summary', '修改尚未验证；下一步检查行为')
        self.assertEqual(0, result.returncode, result.stderr)
        after = rt.load(self.root)
        self.assertEqual(before['local']['source_hashes'], after['local']['source_hashes'])
        self.assertEqual('agent-A', after['checkpoint']['owner'])
        self.assertEqual('todo', after['tasks'][0]['status'])
        self.assertNotEqual(0, self.run_tool('check').returncode)

    def test_next_agent_reads_checkpoint(self):
        self.setup_project()
        self.assertEqual(0, self.run_tool('checkpoint', '--owner', 'agent-A', '--summary', '已查现状，下一步填决策').returncode)
        second = rt.load(self.root)
        self.assertEqual('已查现状，下一步填决策', second['checkpoint']['summary'])
        self.assertIn('下一步填决策', (self.root / 'AGENTS.md').read_text(encoding='utf-8'))
        self.assertEqual(0, self.run_tool('check').returncode)

    def test_stale_writer_cannot_clobber_next_agent(self):
        stale = self.setup_project()
        on_disk = json.loads((self.root / rt.STATE).read_text(encoding='utf-8'))
        on_disk['summary'] = '其他agent的新状态'
        (self.root / rt.STATE).write_text(json.dumps(on_disk), encoding='utf-8')
        stale['summary'] = '旧状态覆盖'
        with self.assertRaises(ValueError):
            rt.save(self.root, stale)
        self.assertEqual('其他agent的新状态', json.loads((self.root / rt.STATE).read_text(encoding='utf-8'))['summary'])

    def test_interrupted_state_write_is_detected(self):
        state = self.setup_project()
        (self.root / 'docs/交接状态.json.tmp').write_text('半成品', encoding='utf-8')
        self.assertTrue(any('中断草稿' in e for e in rt.check(self.root, state)[0]))

    def test_other_agent_lock_not_removed(self):
        state = self.setup_project()
        lock = self.root / 'docs/.handoff.lock'
        lock.write_text('other-agent', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            rt.save(self.root, state)
        self.assertEqual('other-agent', lock.read_text(encoding='utf-8'))

    def test_generated_drift_rejected(self):
        state = self.setup_project()
        (self.root / rt.BOARD).write_text('假通过', encoding='utf-8')
        self.assertTrue(rt.check(self.root, state)[0])

    def test_export_excludes_secrets_and_source(self):
        (self.root / 'src').mkdir()
        (self.root / 'src/.env').write_text('SECRET_SENTINEL', encoding='utf-8')
        (self.root / 'src/a.py').write_text('SOURCE_SENTINEL', encoding='utf-8')
        (self.root / 'src/users.db').write_text('DATABASE_SENTINEL', encoding='utf-8')
        state = self.setup_project(['src'])
        self.assertNotIn('src/.env', state['local']['source_hashes'])
        package = rt.export(self.root, state, self.root / '.handoff-export')
        text = package.read_text(encoding='utf-8')
        for value in ['SECRET_SENTINEL', 'SOURCE_SENTINEL', 'DATABASE_SENTINEL']:
            self.assertNotIn(value, text)

    def test_export_cannot_overwrite_source_or_escape(self):
        state = self.setup_project()
        for output in [self.root, self.root / 'docs/output', self.root / '.git/output', self.root.parent / 'out']:
            with self.assertRaises(ValueError):
                rt.export(self.root, state, output)

    def test_no_other_project_specific_facts(self):
        self.setup_project()
        text = '\n'.join(p.read_text(encoding='utf-8') for p in self.root.rglob('*.md'))
        for specific in ['81.70.243.244', 'saiboxuefu.com', 'codex_qa_20261005', 'deploy_ed25519']:
            self.assertNotIn(specific, text)

    def test_bad_entry_refuses_checkpoint_without_mutation(self):
        self.setup_project()
        before = (self.root / rt.STATE).read_bytes()
        board = (self.root / rt.BOARD).read_bytes()
        (self.root / 'AGENTS.md').write_text(rt.AUTO_START, encoding='utf-8')
        self.assertNotEqual(0, self.run_tool('checkpoint', '--owner', 'agent-B', '--summary', '继续').returncode)
        self.assertEqual(before, (self.root / rt.STATE).read_bytes())
        self.assertEqual(board, (self.root / rt.BOARD).read_bytes())

    def test_large_checkpoint_refuses_before_mutation(self):
        self.setup_project()
        before = (self.root / rt.STATE).read_bytes()
        self.assertNotEqual(0, self.run_tool('checkpoint', '--owner', 'agent-B', '--summary', '长' * 12000).returncode)
        self.assertEqual(before, (self.root / rt.STATE).read_bytes())

    def test_unknown_external_action_blocks_blind_resume(self):
        state = self.setup_project()
        state['operations'] = [{'operation_id': 'release-1', 'owner': 'agent-A', 'target': '测试交付',
                                'status': 'unknown', 'reconcile': '先查目标操作记录与文件指纹'}]
        rt.save(self.root, state)
        self.assertEqual(0, self.run_tool('render').returncode)
        result = self.run_tool('check')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('不能盲目重试', result.stderr)
        state = rt.load(self.root)
        state['operations'][0]['status'] = 'succeeded'
        rt.save(self.root, state)
        self.assertEqual(0, self.run_tool('render').returncode)
        self.assertEqual(0, self.run_tool('check').returncode)

    def test_invalid_state_reports_failure(self):
        state = self.setup_project()
        state['local'] = []
        rt.save(self.root, state)
        result = self.run_tool('record-local')
        self.assertNotEqual(0, result.returncode)
        self.assertIn('HANDOFF_CHECK=FAIL', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
