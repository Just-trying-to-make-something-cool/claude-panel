"""Безголовые тесты окна: .venv/bin/python -m unittest discover tests"""
import io, json, os, sys, tempfile, unittest

from rich.console import Console

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


def segment_with_sessions(rows):
    seg = next(r for r in rows if r.depth == 1 and r.label == 'kvant-lab')
    seg.sessions, seg.last = 11, 1.0
    return seg


class Segments(unittest.IsolatedAsyncioTestCase):
    async def test_segment_label_shows_its_sessions(self):
        root, rows = make_tree()
        segment_with_sessions(rows)
        app = c_tui.Pult(rows)
        async with app.run_test():
            node = app.query_one('#tree').root.children[0]
            self.assertIn('11 сесс', str(node.label))

    async def test_enter_on_segment_toggles_and_continue_button_resumes_there(self):
        root, rows = make_tree()
        segment_with_sessions(rows)
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree')
            seg = tree.root.children[0]
            tree.move_cursor(seg)
            await pilot.pause()
            was = seg.is_expanded
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsNone(app.return_value)       # Enter раскрывает сегмент, а не запускает claude
            self.assertNotEqual(seg.is_expanded, was)
            self.assertTrue(app.query_one('#continue').display)
            await pilot.click('#continue')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('kvant-lab', 'continue'))

    async def test_segment_without_sessions_hides_continue(self):
        root, rows = make_tree()
        app = c_tui.Pult(rows)
        async with app.run_test() as pilot:
            tree = app.query_one('#tree')
            tree.move_cursor(tree.root.children[1])   # clients, сессий нет
            await pilot.pause()
            self.assertFalse(app.query_one('#continue').display)


class SessionList(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root, self.rows = make_tree()
        self.projects, self.saved = tempfile.mkdtemp(), c.PROJECTS
        c.PROJECTS = self.projects
        self.takt = next(r for r in self.rows if r.label == 'takt')
        folder = os.path.join(self.projects, c.encode(self.takt.path))
        os.makedirs(folder)
        for i, (sid, title, prompt) in enumerate([('old1', '', 'сделай ролик про кейс'),
                                                  ('new2', 'takt · оценка', 'оцени ТЗ на ERP')]):
            with open(os.path.join(folder, sid + '.jsonl'), 'w', encoding='utf-8') as fh:
                if title:
                    fh.write(json.dumps({'type': 'custom-title', 'customTitle': title}, ensure_ascii=False) + '\n')
                fh.write(json.dumps({'type': 'user', 'message': {'content': prompt}, 'cwd': self.takt.path,
                                     'timestamp': '2026-10-23T13:18:58Z'}, ensure_ascii=False) + '\n')
            os.utime(os.path.join(folder, sid + '.jsonl'), (1000 + i, 1000 + i))
        self.takt.sessions, self.takt.last = 2, 1001.0

    def tearDown(self):
        c.PROJECTS = self.saved

    async def open_takt(self, app, pilot):
        tree = app.query_one('#tree')
        tree.move_cursor(next(n for n in tree.root.children[0].children if n.data.label == 'takt'))
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_lists_sessions_newest_first_with_details(self):
        app = c_tui.Pult(self.rows)
        async with app.run_test(size=(140, 45)) as pilot:
            await self.open_takt(app, pilot)
            lst = app.query_one('#sessions')
            self.assertEqual(lst.option_count, 2)
            self.assertIn('takt · оценка', str(lst.get_option_at_index(0).prompt))
            self.assertIn('сделай ролик', str(lst.get_option_at_index(1).prompt))   # безымянная — по первому запросу
            con = Console(width=120, record=True, file=io.StringIO())
            con.print(app.query_one('#detail').content)
            self.assertIn('оцени ТЗ на ERP', con.export_text())

    async def test_enter_on_session_opens_exactly_it(self):
        app = c_tui.Pult(self.rows)
        async with app.run_test(size=(140, 45)) as pilot:
            await self.open_takt(app, pilot)
            await pilot.press('tab')
            self.assertEqual(app.focused.id, 'sessions')
            await pilot.press('down', 'enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('takt', 'session:old1'))

    async def test_live_session_waiting_for_answer_is_said_so(self):
        self.takt.live = [{'sessionId': 'new2', 'name': 'takt · оценка', 'state': 'blocked', 'blocked': True}]
        app = c_tui.Pult(self.rows)
        async with app.run_test(size=(140, 45)) as pilot:
            await self.open_takt(app, pilot)
            con = Console(width=120, record=True, file=io.StringIO())
            con.print(app.query_one('#detail').content)
            self.assertIn('ждёт вашего ответа', con.export_text())

    async def test_escape_from_sessions_goes_back_to_tree(self):
        app = c_tui.Pult(self.rows)
        async with app.run_test(size=(140, 45)) as pilot:
            await self.open_takt(app, pilot)
            await pilot.press('tab', 'escape')
            self.assertEqual(app.focused.id, 'tree')
            self.assertIsNone(app.return_value)
