"""Безголовые тесты окна: .venv/bin/python -m unittest discover tests"""
import json, os, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c, tui as c_tui  # noqa: E402

DAY = 86400


def jsonl(path, lines, age_days):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for x in lines:
            fh.write(json.dumps(x, ensure_ascii=False) + '\n')
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))
    return os.path.basename(path)[:-6]


def say(text, cwd, robot=False):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}, 'cwd': cwd,
            'timestamp': '2026-11-08T10:00:00.000Z', 'entrypoint': 'sdk-cli' if robot else 'cli'}


def reply(text, cwd):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]},
            'cwd': cwd, 'timestamp': '2026-11-08T10:01:00.000Z'}


class World:
    """~/claude во временной папке и стенограммы к нему: сессия про лиды из KVANT LAB, работавшая в kvant-radar,
    сессия в takt, сессия в автоворонке без названия, прогон робота из корня."""

    def __init__(self, extra=()):
        self.root, self.projects = tempfile.mkdtemp(), tempfile.mkdtemp()
        for p in ('kvant-lab/takt', 'kvant-lab/kvant-radar', 'kvant-lab/autovoronka/.claude/worktrees/prod', 'clients/sova'):
            os.makedirs(os.path.join(self.root, p))
        with open(os.path.join(self.root, 'kvant-lab', 'CLAUDE.md'), 'w') as fh:
            fh.write('| папка | что | где |\n|---|---|---|\n| `takt/` | таск-менеджер | VPS |\n'
                     '| `kvant-radar/` | агент горячих лидов | дизайн |\n')
        p = lambda folder: os.path.join(self.projects, c.encode(os.path.join(self.root, folder) if folder else self.root))
        radar = os.path.join(self.root, 'kvant-lab', 'kvant-radar')
        self.leads = jsonl(p('kvant-lab') + '/leads.jsonl',
                           [say('оцени письма', self.root + '/kvant-lab'), {'type': 'custom-title', 'customTitle': 'kvant-lab · горячие лиды личка'}]
                           + [reply('ок', radar)] * 5, 0.1)
        self.takt = jsonl(p('kvant-lab/takt') + '/takt.jsonl',
                          [say('план на неделю', self.root + '/kvant-lab/takt'), {'type': 'custom-title', 'customTitle': 'takt · бизнес'}], 1)
        self.rop = jsonl(p('kvant-lab/autovoronka') + '/rop.jsonl',
                         [say('почему РОП пишет про проблему с лидами', self.root + '/kvant-lab/autovoronka')], 3)
        self.robot = jsonl(p('') + '/robot.jsonl', [say('проверь сайты', self.root, robot=True)], 0)
        for folder, name, lines in extra:
            jsonl(p(folder) + f'/{name}.jsonl', lines, 2)
        self.saved, c.PROJECTS = c.PROJECTS, self.projects
        self.rows = c.discover(self.root)
        for r in self.rows:
            stamps = [c._mtime(f) for f in c.folder_sessions(r.path)]
            r.sessions, r.last = len(stamps), max(stamps, default=0.0)
        c.add_activity(self.rows, projects=self.projects, cache=os.path.join(tempfile.mkdtemp(), 'places.json'))

    def row(self, label):
        return next(r for r in self.rows if r.label == label)

    def close(self):
        c.PROJECTS = self.saved


async def ready(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def shown(app):
    """Строки списка сессий как текст: (id опции, текст)."""
    lst = app.query_one('#list')
    return [(o.id, str(o.prompt) if isinstance(o.prompt, str) else c_tui.plain(o.prompt)) for o in lst.options]


class Markup(unittest.TestCase):
    def test_esc_survives_any_text(self):
        from textual.content import Content
        for raw in ['скажи [Im', 'arr[i', 'C:\\', 'a\\[b', '[bold]x', 'см. [1', '[/]', 'x]']:
            plain = Content.from_markup(f'[bold]{c_tui.esc(raw)}[/]  [dim]y[/]').plain
            self.assertIn(raw.replace('\\', '').rstrip('\\')[:3], plain)


class Order(unittest.TestCase):
    def test_kvant_lab_first_then_clients(self):
        w = World()
        w.close()
        segs = [r.label for r in c_tui.ordered(w.rows) if r.depth == 1]
        self.assertEqual(segs, ['kvant-lab', 'clients'])


class Sessions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    async def test_opens_on_sessions_with_search_focused_robots_hidden(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            self.assertEqual(app.query_one('#switch').current, 'sessions')
            self.assertEqual(app.focused.id, 'q')
            texts = [t for _, t in shown(app)]
            self.assertEqual(len(texts), 3)
            self.assertIn('горячие лиды личка', texts[0])
            self.assertIn('бизнес', texts[1])
            self.assertIn('почему РОП', texts[2])
            self.assertFalse(any('проверь сайты' in t for t in texts))

    async def test_typing_narrows_and_offers_folder(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press(*'лид')
            await pilot.pause()
            texts = [t for _, t in shown(app)]
            self.assertIn('горячие лиды личка', texts[0])
            self.assertIn('почему РОП', texts[1])
            self.assertIn('Новая сессия в папке', texts[2])
            self.assertIn('kvant-radar', texts[3])
            self.assertEqual(len(texts), 4)

    async def test_clearing_query_restores_full_list(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press(*'лид', 'backspace', 'backspace', 'backspace')
            await pilot.pause()
            self.assertEqual(len(shown(app)), 3)
            self.assertEqual(app.query_one('#list').highlighted, 0)

    async def test_no_match_says_so_and_enter_does_nothing(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press(*'zzz', 'enter')
            await pilot.pause()
            self.assertIn('ничего не нашлось', shown(app)[0][1])
            self.assertIsNone(app.return_value)
            self.assertTrue(app.is_running)

    async def test_enter_opens_highlighted_from_its_folder(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('kvant-lab', f'session:{self.w.leads}'))

    async def test_down_then_enter_opens_second(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('down', 'enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('takt', f'session:{self.w.takt}'))

    async def test_detail_follows_highlight(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            detail = lambda: c_tui.plain(app.query_one('#detail').content)
            self.assertIn('горячие лиды личка', detail())
            self.assertIn('оцени письма', detail())
            await pilot.press('down')
            await ready(app, pilot)
            self.assertIn('план на неделю', detail())

    async def test_escape_clears_then_quits(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('x', 'escape')
            await pilot.pause()
            self.assertEqual(app.query_one('#q').value, '')
            self.assertTrue(app.is_running)
            await pilot.press('escape')
            await pilot.pause()
        self.assertIsNone(app.return_value)

    async def test_letters_go_to_search_not_to_commands(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press(*'qnrc')
            await pilot.pause()
            self.assertEqual(app.query_one('#q').value, 'qnrc')
            self.assertTrue(app.is_running)

    async def test_live_background_session_attaches(self):
        self.w.row('takt').live = [{'sessionId': self.w.takt, 'kind': 'background', 'id': 'a4ff9cb7', 'blocked': False}]
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('down', 'enter')
        self.assertEqual(app.return_value[1], 'bg:a4ff9cb7')

    async def test_session_open_in_other_terminal_warns(self):
        self.w.row('kvant-lab').live = [{'sessionId': self.w.leads, 'kind': 'interactive', 'blocked': False}]
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('enter')
            await pilot.pause()
            self.assertTrue(app.is_running)
        self.assertIsNone(app.return_value)

    async def test_waiting_session_is_on_top_and_marked(self):
        self.w.row('autovoronka').live = [{'sessionId': self.w.rop, 'kind': 'background', 'id': 'b1', 'blocked': True}]
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            first = shown(app)[0][1]
            self.assertIn('почему РОП', first)
            self.assertIn('ждёт ответа', first)

    async def test_enter_on_folder_asks_name_then_starts_new(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press(*'лид', 'down', 'down', 'enter')
            await pilot.pause()
            self.assertTrue(app.query_one('#name_box').display)
            self.assertEqual(app.focused.id, 'name')
            await pilot.press(*'карточки', 'enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action, name), ('kvant-radar', 'new', 'kvant-radar · карточки'))


class Brackets(unittest.IsolatedAsyncioTestCase):
    async def test_bracket_in_names_does_not_crash(self):
        w = World(extra=[('kvant-lab/takt', 'br', [say('скажи [Im', '/x'), {'type': 'custom-title', 'customTitle': 'a [b'}])])
        try:
            app = c_tui.Pult(w.rows)
            async with app.run_test() as pilot:
                await ready(app, pilot)
                await pilot.press('down', 'down')
                await ready(app, pilot)
                self.assertTrue(any('a [b' in t for _, t in shown(app)))
        finally:
            w.close()


class Folders(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    async def go(self, app, pilot, label):
        await ready(app, pilot)
        await pilot.press('tab')
        await pilot.pause()
        tree = app.query_one('#tree')
        node = next(n for n in c_tui.walk(tree.root) if n.data is not None and n.data.label == label)
        tree.move_cursor(node)
        await pilot.pause()

    async def test_tab_switches_modes_and_focus(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('tab')
            await pilot.pause()
            self.assertEqual((app.query_one('#switch').current, app.focused.id), ('folders', 'tree'))
            await pilot.press('tab')
            await pilot.pause()
            self.assertEqual((app.query_one('#switch').current, app.focused.id), ('sessions', 'q'))

    async def test_enter_on_project_asks_name_and_starts_new(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'takt')
            await pilot.press('enter')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'name')
            await pilot.press(*'бизнес', 'enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action, name), ('takt', 'new', 'takt · бизнес'))

    async def test_escape_closes_name_box_back_to_tree(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'takt')
            await pilot.press('enter', 'escape')
            await pilot.pause()
            self.assertFalse(app.query_one('#name_box').display)
            self.assertEqual(app.focused.id, 'tree')
            self.assertTrue(app.is_running)

    async def test_c_continues_last_session_here(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'takt')
            await pilot.press('c')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('takt', 'continue'))

    async def test_enter_on_segment_toggles(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'kvant-lab')
            node = app.query_one('#tree').cursor_node
            was = node.is_expanded
            await pilot.press('enter')
            await pilot.pause()
            self.assertNotEqual(node.is_expanded, was)
            self.assertIsNone(app.return_value)

    async def test_folder_work_shows_guest_session_and_opens_it_from_its_folder(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'kvant-radar')
            work = app.query_one('#work')
            texts = [c_tui.plain(o.prompt) for o in work.options]
            self.assertEqual(len(texts), 1)
            self.assertIn('горячие лиды личка', texts[0])
            self.assertIn('из KVANT LAB', texts[0])
            await pilot.press('right')
            await pilot.pause()
            self.assertEqual(app.focused.id, 'work')
            await pilot.press('enter')
        row, action, name = app.return_value
        self.assertEqual((row.label, action), ('kvant-lab', f'session:{self.w.leads}'))

    async def test_q_quits_here(self):
        app = c_tui.Pult(self.w.rows)
        async with app.run_test() as pilot:
            await self.go(app, pilot, 'takt')
            await pilot.press('q')
            await pilot.pause()
        self.assertIsNone(app.return_value)
        self.assertFalse(app.is_running)


class Fresh(unittest.IsolatedAsyncioTestCase):
    def rows(self):
        root = tempfile.mkdtemp()
        for p in ('kvant-lab/takt', 'kvant-lab/autovoronka', 'kvant-lab/old/.claude/worktrees/w', 'kvant-lab/zold',
                  'clients/sova'):
            os.makedirs(os.path.join(root, p))
        rows, now = c.discover(root), time.time()
        for r in rows:
            r.active = {'takt': now - 3600, 'autovoronka': now - 3 * 86400, 'old': now - 40 * 86400}.get(r.label, 0.0)
        return rows

    async def test_fresh_first_newest_on_top_rest_folded(self):
        app = c_tui.Pult(self.rows())
        async with app.run_test():
            kl, cl = app.query_one('#tree').root.children[:2]
            names = [n.data.label if n.data else str(n.label) for n in kl.children]
            self.assertEqual(names, ['takt', 'autovoronka', 'давно не открывались · 2'])   # свежее выше, не по алфавиту
            old = kl.children[2]
            self.assertFalse(old.is_expanded)
            self.assertEqual([n.data.label for n in old.children], ['old', 'zold'])
            self.assertEqual([n.data.label for n in old.children[0].children], ['w'])   # части не теряются
            self.assertTrue(kl.is_expanded)
            self.assertFalse(cl.is_expanded)                  # в «Клиентах» свежего нет — сегмент свёрнут
            self.assertEqual(str(cl.children[0].label), 'давно не открывались · 1')

    async def test_enter_on_folded_group_opens_it(self):
        app = c_tui.Pult(self.rows())
        async with app.run_test() as pilot:
            await ready(app, pilot)
            await pilot.press('tab')
            tree = app.query_one('#tree')
            old = tree.root.children[0].children[2]
            tree.move_cursor(old)
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            self.assertTrue(old.is_expanded)
            self.assertIsNone(app.return_value)

    async def test_no_emoji_in_tree(self):
        app = c_tui.Pult(self.rows())
        async with app.run_test():
            labels = ' '.join(str(n.label) for n in c_tui.walk(app.query_one('#tree').root))
            self.assertFalse(any(ord(ch) > 0x2600 for ch in labels), labels)


if __name__ == '__main__':
    unittest.main()
