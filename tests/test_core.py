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


if __name__ == '__main__':
    unittest.main()


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
