"""Безголовые тесты окна: .venv/bin/python -m unittest discover tests"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c, tui as c_tui  # noqa: E402


def make_tree():
    root = tempfile.mkdtemp()
    mk = lambda *p: os.makedirs(os.path.join(root, *p), exist_ok=True)
    mk('kvant-lab', 'takt'); mk('kvant-lab', 'autovoronka', '.claude', 'worktrees', 'prod'); mk('clients', 'sova')
    with open(os.path.join(root, 'kvant-lab', 'CLAUDE.md'), 'w') as fh:
        fh.write('| папка | что | где |\n|---|---|---|\n| `takt/` | таск-менеджер | VPS |\n')
    rows = c.discover(root)
    for r in rows:
        if r.label == 'autovoronka':
            r.sessions, r.last = 3, 1.0
            r.live = [{'sessionId': 'abc', 'name': 'rop', 'state': 'busy', 'blocked': False}]
    return root, rows


class Order(unittest.TestCase):
    def test_kvant_lab_first_then_clients(self):
        root, rows = make_tree()
        segs = [r.label for r in c_tui.ordered(rows) if r.depth == 1]
        self.assertEqual(segs, ['kvant-lab', 'clients'])


class Tui(unittest.IsolatedAsyncioTestCase):
    async def test_enter_on_project_without_sessions_starts_new(self):
        root, rows = make_tree()
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree')
            tree.select_node(next(n for n in tree.root.children[0].children if n.data.label == 'takt'))
            await pilot.pause()
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('takt', 'continue'))

    async def test_n_opens_name_box_and_enter_submits(self):
        root, rows = make_tree()
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree')
            tree.move_cursor(next(n for n in tree.root.children[0].children if n.data.label == 'takt'))
            await pilot.pause()
            await pilot.press('n')
            self.assertTrue(app.query_one('#name_box').has_class('show'))
            self.assertEqual(app.query_one('#name').value, '')
            await pilot.press(*'бизнес', 'enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action, name), ('takt', 'new', 'takt · бизнес'))

    async def test_resume_and_live_attach(self):
        root, rows = make_tree()
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree')
            tree.move_cursor(next(n for n in tree.root.children[0].children if n.data.label == 'autovoronka'))
            await pilot.pause()
            self.assertTrue(app.query_one('#live').display)
            self.assertTrue(app.query_one('#resume').display)
            await pilot.press('r')
        self.assertEqual(app.return_value[1], 'resume')

    async def test_q_quits_without_result(self):
        root, rows = make_tree()
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            await pilot.press('q')
        self.assertIsNone(app.return_value)
