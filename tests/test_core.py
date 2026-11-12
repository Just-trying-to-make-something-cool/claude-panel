"""Тесты ядра: python3 -m unittest discover tests"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402


class Encode(unittest.TestCase):
    def test_path_to_projects_dir(self):
        self.assertEqual(c.encode('/Users/albert/claude/kvant-lab/takt'),
                         '-Users-albert-claude-kvant-lab-takt')

    def test_dot_becomes_dash_too(self):
        self.assertEqual(
            c.encode('/Users/albert/claude/kvant-lab/autovoronka/.claude/worktrees/prod'),
            '-Users-albert-claude-kvant-lab-autovoronka--claude-worktrees-prod')


class Table(unittest.TestCase):
    md = """# X
| папка | что это | где живёт |
|---|---|---|
| `takt/` | таск-менеджер на двоих | VPS, https://takt.ipeffer.online |
| `bots/` | Секретарь, Хомяк, Эскиз | VPS, `/home/agent/<бот>` |
| sova | одностраничник СОВА, статика | Vercel |
| `kvant-lab/` | Студия: `autovoronka/` и `takt/` |
"""

    def test_finds_description_by_folder_name(self):
        t = c.parse_table(self.md)
        self.assertEqual(t['takt'][0], 'таск-менеджер на двоих')
        self.assertEqual(t['takt'][1], 'VPS, https://takt.ipeffer.online')

    def test_strips_backticks_and_slash(self):
        t = c.parse_table(self.md)
        self.assertIn('bots', t)
        self.assertEqual(t['bots'][1], 'VPS, /home/agent/<бот>')

    def test_plain_name_and_two_column_table(self):
        t = c.parse_table(self.md)
        self.assertEqual(t['sova'][0], 'одностраничник СОВА, статика')
        self.assertEqual(t['kvant-lab'], ('Студия: autovoronka/ и takt/', ''))


class Discover(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        mk = lambda *p: os.makedirs(os.path.join(self.root, *p), exist_ok=True)
        mk('kvant-lab', 'takt')
        mk('kvant-lab', 'autovoronka', '.claude', 'worktrees', 'prod')
        mk('kvant-lab', 'bots', 'sekretar')
        mk('kvant-lab', 'bots', 'homyak', '.git')
        mk('clients', 'sova')
        mk('archive', 'old')
        mk('.hidden')
        with open(os.path.join(self.root, "kvant-lab", "CLAUDE.md"), "w") as fh: fh.write(
            '| папка | что | где |\n|---|---|---|\n| `takt/` | таск-менеджер | VPS |\n')
        with open(os.path.join(self.root, "kvant-lab", "bots", "sekretar", "CLAUDE.md"), "w") as fh: fh.write("# s\n")

    def paths(self, rows):
        return [os.path.relpath(r.path, self.root) for r in rows]

    def test_levels_root_segments_projects_parts(self):
        rows = c.discover(self.root)
        p = self.paths(rows)
        self.assertEqual(p[0], '.')
        self.assertIn('kvant-lab', p)
        self.assertIn('kvant-lab/takt', p)
        self.assertIn('kvant-lab/autovoronka/.claude/worktrees/prod', p)
        self.assertIn('kvant-lab/bots/sekretar', p)   # есть CLAUDE.md
        self.assertIn('kvant-lab/bots/homyak', p)     # есть .git
        self.assertIn('clients/sova', p)

    def test_skips_archive_hidden_and_plain_subfolders(self):
        p = self.paths(c.discover(self.root))
        self.assertNotIn('archive', p)
        self.assertNotIn('archive/old', p)
        self.assertNotIn('.hidden', p)
        self.assertNotIn('kvant-lab/autovoronka/.claude', p)

    def test_description_and_depth(self):
        rows = {os.path.relpath(r.path, self.root): r for r in c.discover(self.root)}
        self.assertEqual(rows['kvant-lab/takt'].what, 'таск-менеджер')
        self.assertEqual(rows['kvant-lab/takt'].where, 'VPS')
        self.assertEqual(rows['kvant-lab'].depth, 1)
        self.assertEqual(rows['kvant-lab/takt'].depth, 2)
        self.assertEqual(rows['kvant-lab/autovoronka/.claude/worktrees/prod'].depth, 3)
        self.assertEqual(rows['kvant-lab/autovoronka/.claude/worktrees/prod'].label, 'prod')

    def test_visible_filters_third_level_noise(self):
        rows = {os.path.relpath(r.path, self.root): r for r in c.discover(self.root)}
        self.assertTrue(c.visible(rows['kvant-lab/takt']))                                  # проект всегда
        self.assertTrue(c.visible(rows['kvant-lab/autovoronka/.claude/worktrees/prod']))    # рабочая копия
        self.assertTrue(c.visible(rows['kvant-lab/bots/sekretar']))                         # есть CLAUDE.md
        self.assertFalse(c.visible(rows['kvant-lab/bots/homyak']))                          # только .git, сессий нет
        rows['kvant-lab/bots/homyak'].sessions = 2
        self.assertTrue(c.visible(rows['kvant-lab/bots/homyak']))
        agent = c.Row(self.root + '/x/.claude/worktrees/agent-a31d7c8adec9c4246', 3, 'agent-a31d7c8adec9c4246', 'рабочая копия')
        self.assertFalse(c.visible(agent))

    def test_session_name_default(self):
        rows = {os.path.relpath(r.path, self.root): r for r in c.discover(self.root)}
        self.assertEqual(c.session_name(rows['kvant-lab/takt'], ''), 'takt')
        self.assertEqual(c.session_name(rows['kvant-lab/takt'], 'бизнес'), 'takt · бизнес')
        self.assertEqual(c.session_name(rows['kvant-lab/autovoronka/.claude/worktrees/prod'], ''),
                         'autovoronka · prod')


class Menu(unittest.TestCase):
    def setUp(self):
        self.rows = c.discover(Discover.setUp.__globals__ and tempfile.mkdtemp())

    def test_menu_without_sessions_offers_new_and_back_only(self):
        r = c.Row('/x/p', 2, 'p', 'd', '', 'p')
        codes = [k for k, _ in c.menu_items(r, [r])]
        self.assertEqual(codes, ['new', 'back'])

    def test_menu_with_sessions_and_parts(self):
        r = c.Row('/x/p', 2, 'p', 'd', '', 'p', sessions=3, last=1.0)
        part = c.Row('/x/p/.claude/worktrees/prod', 3, 'prod', 'рабочая копия', '', 'p')
        hidden = c.Row('/x/p/.claude/worktrees/agent-a31d7c8adec9c4246', 3, 'agent-a31d7c8adec9c4246', 'рабочая копия', '', 'p')
        codes = [k for k, _ in c.menu_items(r, [r, part, hidden])]
        self.assertEqual(codes, ['continue', 'new', 'resume', 'sep', 'go:/x/p/.claude/worktrees/prod', 'back'])

    def test_live_session_gets_attach_item(self):
        r = c.Row('/x/p', 2, 'p', 'd', '', 'p', live=[{'sessionId': 'abc', 'name': 'n', 'state': 'idle', 'blocked': True}])
        codes = [k for k, _ in c.menu_items(r, [r])]
        self.assertIn('attach:abc', codes)

    def test_plain_strips_colors(self):
        self.assertEqual(c.plain(['/p\t\033[1mx\033[0m y']), ['x y'])


class Live(unittest.TestCase):
    def test_same_session_in_two_processes_is_one_entry(self):
        # фоновая джоба и `claude --resume` той же сессии в терминале: claude agents отдаёт обе
        agents = [{'cwd': '/c', 'sessionId': 'x', 'name': 'root · линкедин', 'state': 'blocked', 'kind': 'background'},
                  {'cwd': '/c', 'sessionId': 'x', 'name': 'claude-41', 'status': 'busy', 'kind': 'interactive'},
                  {'cwd': '/c', 'sessionId': 'y', 'name': 'rop', 'state': 'working'}]
        live = c.group_live(agents)
        self.assertEqual([s['sessionId'] for s in live['/c']], ['x', 'y'])
        self.assertEqual(live['/c'][0]['name'], 'root · линкедин')
        self.assertTrue(live['/c'][0]['blocked'])
        self.assertFalse(live['/c'][1]['blocked'])

    def test_generic_name_replaced_and_interactive_busy_is_working(self):
        agents = [{'cwd': '/c', 'sessionId': 'z', 'name': 'claude-7', 'status': 'busy'},
                  {'cwd': '/c', 'sessionId': 'z', 'name': 'takt · оценка', 'state': 'idle'}]
        live = c.group_live(agents)
        self.assertEqual(live['/c'][0]['name'], 'takt · оценка')
        self.assertEqual(c._status(c.Row('/c', 2, 'c', live=live['/c'])), 'работает')

    def test_interactive_listed_first_still_attaches_to_background(self):
        agents = [{'cwd': '/c', 'sessionId': 'x', 'name': 'claude-41', 'status': 'busy', 'kind': 'interactive', 'pid': 3},
                  {'cwd': '/c', 'sessionId': 'x', 'id': 'x1', 'name': 'root · линкедин', 'state': 'blocked', 'kind': 'background'}]
        live = c.group_live(agents)
        self.assertEqual(len(live['/c']), 1)
        self.assertEqual(c.open_action('x', live['/c']), 'bg:x1')
        self.assertEqual(live['/c'][0]['name'], 'root · линкедин')

    def test_blocked_from_job_state(self):
        live = c.group_live([{'cwd': '/c', 'sessionId': 'q', 'name': 'n', 'state': 'working'}], blocked={'q'})
        self.assertTrue(live['/c'][0]['blocked'])

class OpenSession(unittest.TestCase):
    def test_live_background_session_is_attached_not_resumed(self):
        live = [{'sessionId': 'a4ff9cb7-e4fe', 'id': 'a4ff9cb7', 'kind': 'background', 'blocked': False}]
        self.assertEqual(c.open_action('a4ff9cb7-e4fe', live), 'bg:a4ff9cb7')

    def test_interactive_or_finished_session_is_resumed(self):
        live = [{'sessionId': 'x', 'id': None, 'kind': 'background', 'blocked': False}]   # фоновая без id
        self.assertEqual(c.open_action('x', live), 'session:x')
        self.assertEqual(c.open_action('y', live), 'session:y')
        self.assertEqual(c.open_action('x', live, 'attach'), 'attach:x')

    def test_session_open_in_another_terminal_is_not_reopened(self):
        live = [{'sessionId': 'x', 'id': None, 'kind': 'interactive', 'pid': 3280, 'blocked': False}]
        self.assertEqual(c.open_action('x', live), 'busy:x')

    def test_launch_busy_does_not_start_claude(self):
        import contextlib, io
        err = io.StringIO()
        os.environ['C_DRY'] = '1'          # страховка: без неё ошибка в launch выполнила бы exec claude
        try:
            with contextlib.redirect_stderr(err):
                c.launch(c.Row(tempfile.mkdtemp(), 2, 'p'), 'busy:x')
        finally:
            os.environ.pop('C_DRY')
        self.assertIn('уже открыта', err.getvalue())
        self.assertNotIn('claude -', err.getvalue())

    def test_launch_bg_runs_claude_attach(self):
        import contextlib, io
        d = tempfile.mkdtemp()
        err = io.StringIO()
        os.environ['C_DRY'] = '1'
        try:
            with contextlib.redirect_stderr(err):
                c.launch(c.Row(d, 2, 'p'), 'bg:a4ff9cb7')
        finally:
            os.environ.pop('C_DRY')
        self.assertIn('claude attach a4ff9cb7', err.getvalue())


class Live(unittest.TestCase):
    def test_same_session_in_two_windows_listed_once(self):
        """Одна сессия, открытая в двух окнах, приходит из `claude agents` дважды: в списке живых она одна."""
        import json, subprocess, types
        two = [{'sessionId': 'a1', 'cwd': '/p', 'name': 'x', 'pid': 1}, {'sessionId': 'a1', 'cwd': '/p', 'name': 'x', 'pid': 2},
               {'sessionId': 'b2', 'cwd': '/p', 'name': 'y', 'pid': 3}]
        real = subprocess.run
        subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=json.dumps(two), returncode=0)
        try:
            row = types.SimpleNamespace(path='/p')
            c.add_stats([row])
        finally:
            subprocess.run = real
        self.assertEqual([s['sessionId'] for s in row.live], ['a1', 'b2'])


def _dry_launch(row, action='continue', **env):
    """Команда запуска, которую напечатал бы launch, — без exec. env подменяет переменные на время вызова."""
    import contextlib, io
    env = dict({'C_DRY': '1', 'C_PAIR': '0', 'C_PLAIN': None, 'ZELLIJ': None}, **env)
    old = {k: os.environ.get(k) for k in env}
    err = io.StringIO()
    try:
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        with contextlib.redirect_stderr(err):
            c.launch(row, action)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return err.getvalue()


class ContinueById(unittest.TestCase):
    """«Продолжить» открывает последнюю человеческую сессию папки по id, а не `claude -c`: тот сразу
    выходит, когда последняя сессия идёт в фоне, и берёт самую свежую стенограмму — прогон робота."""

    def setUp(self):
        import json
        self.json, self.old = json, c.PROJECTS
        c.PROJECTS = tempfile.mkdtemp()
        self.dir = tempfile.mkdtemp()
        self.row = c.Row(self.dir, 2, 'p', project='p')

    def tearDown(self):
        c.PROJECTS = self.old

    def session(self, sid, mtime, robot=False):
        d = os.path.join(c.PROJECTS, c.encode(self.dir))
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, sid + '.jsonl')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(self.json.dumps({'type': 'user', 'message': {'content': 'задача ' + sid}, 'cwd': self.dir,
                                      'entrypoint': 'sdk-cli' if robot else 'cli'}) + '\n')
        os.utime(f, (mtime, mtime))
        self.row.sessions += 1
        return f

    def test_last_human_session_by_id(self):
        self.session('aaaa-old', 1000)
        self.session('bbbb-new', 2000)
        self.session('cccc-robot', 3000, robot=True)     # свежее всех, но это claude -p
        out = _dry_launch(self.row)
        self.assertIn('claude -r bbbb-new', out)
        self.assertNotIn('claude -c', out)

    def test_only_robot_runs_take_newest(self):
        self.session('r1', 1000, robot=True)
        self.session('r2', 2000, robot=True)
        self.assertIn('claude -r r2', _dry_launch(self.row))

    def test_background_session_is_attached(self):
        self.session('bbbb-new', 2000)
        self.row.live = [{'sessionId': 'bbbb-new', 'kind': 'background', 'id': 'f00d', 'blocked': False}]
        self.assertIn('claude attach f00d', _dry_launch(self.row))

    def test_open_in_other_terminal_is_not_started_again(self):
        self.session('bbbb-new', 2000)
        self.row.live = [{'sessionId': 'bbbb-new', 'kind': 'interactive', 'blocked': False}]
        out = _dry_launch(self.row)
        self.assertIn('уже открыта', out)
        self.assertNotIn('claude -', out)

    def test_no_sessions_starts_new(self):
        self.assertIn('claude -n p', _dry_launch(self.row))


class Pair(unittest.TestCase):
    """Пара с Codex: `rev --here` из claude-setup, флаг ~/.claude/pair-codex или C_PAIR."""

    def setUp(self):
        self.bin, self.home, self.old = tempfile.mkdtemp(), tempfile.mkdtemp(), (c.H, os.environ.get('PATH'))
        rev = os.path.join(self.bin, 'rev')
        with open(rev, 'w') as fh:
            fh.write('#!/bin/sh\nexit 0\n')
        os.chmod(rev, 0o755)
        os.makedirs(os.path.join(self.home, '.claude'))
        c.H = self.home
        os.environ['PATH'] = self.bin + os.pathsep + '/usr/bin:/bin'

    def tearDown(self):
        c.H, os.environ['PATH'] = self.old

    def on(self, **env):
        env = dict({'C_PAIR': None, 'C_PLAIN': None, 'ZELLIJ': None}, **env)
        old = {k: os.environ.get(k) for k in env}
        try:
            for k, v in env.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            return c.pair_on()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_flag_file_turns_pair_on(self):
        self.assertFalse(self.on())
        open(os.path.join(self.home, '.claude', 'pair-codex'), 'w').close()
        self.assertTrue(self.on())
        self.assertFalse(self.on(C_PAIR='0'))            # C_PAIR главнее файла

    def test_env_turns_pair_on(self):
        self.assertTrue(self.on(C_PAIR='1'))

    def test_without_our_rev_no_pair(self):
        os.environ['PATH'] = '/usr/bin:/bin'             # там только системная rev, переворачивающая строки
        self.assertFalse(self.on(C_PAIR='1'))

    def test_plain_or_inside_zellij_no_pair(self):
        self.assertFalse(self.on(C_PAIR='1', C_PLAIN='1'))
        self.assertFalse(self.on(C_PAIR='1', ZELLIJ='0'))

    def test_launch_goes_through_rev_here(self):
        out = _dry_launch(c.Row(tempfile.mkdtemp(), 2, 'p', project='p'), 'session:abc', C_PAIR='1')
        self.assertIn('rev --here · claude -r abc', out)
        self.assertNotIn('rev --here', _dry_launch(c.Row(tempfile.mkdtemp(), 2, 'p', project='p'), 'session:abc'))


if __name__ == '__main__':
    unittest.main()
