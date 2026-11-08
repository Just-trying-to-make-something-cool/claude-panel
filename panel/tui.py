"""Панель управления папками Claude: окно в терминале (Textual). Данные и запуск — в core.py.

Два режима, Tab переключает.

Сессии — с него окно открывается. Строка поиска, под ней все ваши сессии из всех папок ~/claude:
ждущие ответа первыми, дальше свежие выше. Справа — что внутри выбранной: где запущена и где работала,
когда, первый и последний запрос, последний ответ. Печатайте слова из названия, запроса или имени папки —
список сужается, ниже появляются папки, где можно начать новую сессию. ↑↓ выбрать, Enter открыть,
Esc очистить поиск, ещё раз — выход. Прогоны без человека (claude -p) не показываются.

Папки — дерево ~/claude: в разделе сверху папки, где работа шла за две недели, остальное свёрнуто
в «давно не открывались». Справа описание папки и работа над ней, в том числе сессии, запущенные
из раздела выше. Enter — новая сессия (спросит, о чём; на разделе — раскрыть), c — продолжить
последнюю, → — к сессиям папки, q — выход. Мышь работает.
"""
import io, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402

from rich.console import Console, Group  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.widgets import Button, ContentSwitcher, Input, OptionList, Static, Tree  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402

SEG_ORDER = ['kvant-lab', 'clients', 'infra', 'personal', 'work', 'claude-settings']
SEG_NAMES = {'kvant-lab': 'KVANT LAB', 'clients': 'Клиенты', 'infra': 'Инфра', 'personal': 'Личное',
             'work': 'Разовые задачи', 'claude-settings': 'Настройки Claude'}
STATUS = {'ЖДЁТ': '[bold yellow]ждёт ответа[/]', 'работает': '[green]идёт[/]', 'живая': '[green]открыта[/]', '': ''}
THEME = os.environ.get('C_THEME', 'nord')
WORK_LIMIT = 30
BROKEN = ('ошибка входа', 'ошибка API', 'лимит')
HINTS = {'sessions': 'Enter — открыть · ↑↓ — выбрать · печатайте, чтобы искать · Tab — папки · Esc — очистить / выход',
         'folders': 'Enter — новая сессия здесь (на разделе — раскрыть) · c — продолжить последнюю · → — сессии папки'
                    ' · Tab — сессии · q — выход'}


def esc(s):
    """Текст с диска для разметки Textual: экранируется каждая «[». Штатный escape пропускает
    незакрытые, и обрезанное «…скажи [Im…» роняло окно с MarkupError."""
    return re.sub(r'\\+(?=\[)', '', str(s)).rstrip('\\').replace('[', '\\[')


def plain(x):
    """Текст без оформления: разметка Textual, Content или что угодно из Rich."""
    if isinstance(x, str):
        return Content.from_markup(x).plain
    if isinstance(x, Content):
        return x.plain
    con = Console(width=200, file=io.StringIO(), color_system=None, record=True)
    con.print(x)
    return con.export_text()


def walk(node):
    yield node
    for ch in node.children:
        yield from walk(ch)


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def sessions_word(n):
    return f'{n} {plural(n, "сессия", "сессии", "сессий")}'


def nice_name(r):
    if r.depth == 0:
        return '~/claude'
    return SEG_NAMES.get(r.label, r.label) if r.depth == 1 else r.label


def tree_label(r):
    """У корня и разделов — число своих сессий, у проектов — когда в них последний раз работали."""
    if r.depth == 0:
        name = '[bold]~/claude[/]'
    elif r.depth == 1:
        name = f'[bold]{esc(nice_name(r))}[/]'
    else:
        name = esc(r.label)
        if not (r.what or r.sessions) and r.depth == 2:
            name = f'[dim]{name}[/]'
    tail = ''
    if r.depth < 2 and r.sessions:
        tail = f'[dim]{sessions_word(r.sessions)} · {c._ago(r.last)}[/]'
    elif r.depth >= 2 and r.active:
        tail = f'[dim]{c._ago(r.active)}[/]'
    return '  '.join(x for x in (name, STATUS[c._status(r)], tail) if x)


def ordered(rows, now=None):
    """Разделы в рабочем порядке (KVANT LAB первым). Внутри сначала проекты, где недавно шла работа,
    самые свежие выше, потом остальные как на диске; части идут за своим проектом."""
    root = rows[0].path
    rel = lambda r: os.path.relpath(r.path.replace('/.claude/worktrees', ''), root).split('/')
    segs = sorted({rel(r)[0] for r in rows if r.depth >= 1},
                  key=lambda s: (SEG_ORDER.index(s) if s in SEG_ORDER else 99, s))
    out = [rows[0]]
    for seg in segs:
        mine = [r for r in rows if r.depth >= 1 and rel(r)[0] == seg]
        out += [r for r in mine if r.depth == 1]
        for p in sorted((r for r in mine if r.depth == 2), key=lambda r: -r.active if c.is_fresh(r, now) else 1):
            out += [p] + [r for r in mine if r.depth == 3 and rel(r)[:2] == rel(p)[:2]]
    return out


def _line(s, n):
    return c._cut(' '.join(s.split()), n)


def _lit(text, words):
    t = Text(text)
    if words:
        t.highlight_words(words, 'bold yellow', case_sensitive=False)
    return t


def session_line(item, words=(), here=None):
    """Строка списка: имя (у гостя — откуда запущена), справа «ждёт ответа», «идёт» или «робот» и когда."""
    name = _lit(item['name'], words)
    if here is not None and item['row'] is not here:
        name.append(f'  · из {nice_name(item["row"])}', 'dim')
    live, tags = item['live'] or {}, Text(no_wrap=True)
    if live.get('blocked'):
        tags.append('ждёт ответа  ', 'bold yellow')
    elif live:
        tags.append('идёт  ', 'green')
    if item['brief']['auto']:
        tags.append('робот  ', 'dim')
    tags.append(c.when(item['brief']['last']), 'dim')
    t = Table.grid(expand=True)
    t.add_column(ratio=1, no_wrap=True, overflow='ellipsis')
    t.add_column(no_wrap=True, justify='right')
    t.add_row(name, tags)
    return t


def folder_line(r, words=()):
    t = _lit(nice_name(r), words)
    if r.what:
        t.append('  ' + _line(r.what, 200), 'dim')
    g = Table.grid(expand=True)            # таблица, а не Text: список переносит длинный Text, no_wrap не помогает
    g.add_column(ratio=1, no_wrap=True, overflow='ellipsis')
    g.add_row(t)
    return g


def detail_view(item, d):
    """Что внутри сессии: где запущена и где работала, когда, первый и последний запрос, чем кончилась."""
    b, live = item['brief'], item['live']
    t = Table.grid(padding=(0, 2))
    t.add_column(style='dim', no_wrap=True)
    t.add_column(ratio=1)
    add = lambda k, v, style='': t.add_row(k, Text(v, style))
    where = f'запущена в {nice_name(item["row"])}'
    if d and d['places']:
        where += ' · работала: ' + ', '.join(f'{p} {n}%' for p, n in d['places'])
    add('где', where)
    when = [f'начата {c.when(b["started"])}' if b['started'] else '', f'последняя запись {c.when(b["last"])}']
    if d and d['branch'] not in ('', 'HEAD'):
        when.append(f'ветка {d["branch"]}')
    add('когда', ' · '.join(x for x in when if x))
    if b['first'] and b['first'] != c.CONTINUED:
        add('первый запрос', _line(b['first'], 300))
    elif b['first'] == c.CONTINUED:
        add('первый запрос', c.CONTINUED)
    last_user = (d or {}).get('last_user') or b['last_user']
    if last_user and _line(last_user, 300) != _line(b['first'], 300):
        add('последний запрос', _line(last_user, 300))
    if live and live.get('blocked'):
        add('сейчас', 'ждёт вашего ответа', 'bold yellow')
    elif live and live.get('kind') == 'interactive':
        add('сейчас', 'открыта в другом терминале — переключитесь туда', 'green')
    elif live:
        add('сейчас', 'идёт прямо сейчас', 'green')
    elif d and d['error'] in BROKEN:
        add('чем кончилась', f'оборвалась: {d["error"]} — откройте и напишите «продолжи»', 'yellow')
    elif d and d['error'] == 'без ответа':
        add('чем кончилась', 'последний запрос остался без ответа', 'yellow')
    if d is None:
        add('', 'читаю стенограмму…', 'dim')
    elif d['last_answer']:
        add('последний ответ', _line(d['last_answer'], 400))
    head = Text(item['name'], 'bold')
    head.append(f'  {b["id"][:8]}', 'dim')
    return Group(head, Text(''), t)


def folder_view(r):
    parts = [Text(nice_name(r), 'bold')]
    if r.what:
        parts += [Text(''), Text(r.what)]
    if r.where:
        parts.append(Text(f'где живёт: {r.where}', 'dim'))
    parts += [Text(''), Text('Enter — новая сессия в этой папке', 'dim')]
    return Group(*parts)


class FolderTree(Tree):
    """Дерево папок: → ведёт к сессиям папки (у Tree стрелка вправо прокручивает вбок)."""
    BINDINGS = [Binding('right', 'app.to_work', show=False)]


class Pult(App):
    TITLE = 'Claude · пульт'
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #modes { height: 1; margin: 1 2 0 2; }
    #switch { height: 1fr; }
    #sessions { padding: 0 1; }
    #q { margin: 1 1 0 1; }
    #sbody { height: 1fr; margin-top: 1; }
    #list { width: 55%; border: none; padding: 0 1; background: $surface; }
    #detail { width: 1fr; padding: 0 2; border-left: solid $primary 40%; }
    #folders { padding: 1 1 0 1; }
    #tree { width: 40%; padding: 0 1; background: $surface; }
    #card { width: 1fr; padding: 0 2; border-left: solid $primary 40%; }
    #what { margin-top: 1; }
    #meta { color: $text-muted; }
    #buttons { height: auto; margin-top: 1; }
    #buttons Button { margin-right: 2; padding: 0 1; }
    #work_h { margin-top: 1; color: $accent; text-style: bold; }
    #work { height: 1fr; border: none; padding: 0; background: $surface; }
    #name_box { height: auto; padding: 0 2; border-top: solid $accent; }
    #hint { height: 1; margin: 0 2; color: $text-muted; }
    """
    BINDINGS = [
        Binding('tab', 'switch', 'сессии ⇄ папки', priority=True),
        Binding('escape', 'back', show=False),
        Binding('up', 'move(-1)', show=False), Binding('down', 'move(1)', show=False),
        Binding('pageup', 'move(-10)', show=False), Binding('pagedown', 'move(10)', show=False),
        Binding('c', 'go_continue', show=False), Binding('n', 'go_new', show=False), Binding('q', 'quit', show=False),
    ]

    def __init__(self, rows):
        super().__init__()
        self.now = time.time()
        self.rows = ordered(rows, self.now)
        self.current = self.rows[0]
        self.new_row = None
        self.items = None              # общий список сессий, читается в фоне
        self.picks, self.work_picks = {}, {}
        self.details = {}

    # ---------- раскладка ----------
    def compose(self) -> ComposeResult:
        yield Static(self.modes('sessions'), id='modes')
        with ContentSwitcher(initial='sessions', id='switch'):
            with Vertical(id='sessions'):
                yield Input(placeholder='найти: слово из названия, запроса или имени папки', id='q')
                with Horizontal(id='sbody'):
                    yield OptionList(id='list')
                    yield Static('', id='detail')
            with Horizontal(id='folders'):
                yield self.tree()
                with Vertical(id='card'):
                    yield Static('', id='title')
                    yield Static('', id='what')
                    yield Static('', id='meta')
                    with Horizontal(id='buttons'):
                        yield Button('Новая сессия здесь', id='new', variant='primary', compact=True)
                        yield Button('Продолжить последнюю', id='continue', compact=True)
                    yield Static('', id='work_h')
                    yield OptionList(id='work')
        with Vertical(id='name_box'):
            yield Static('', id='name_label')
            yield Input(placeholder='о чём сессия, например «бизнес» (можно пусто)', id='name')
        yield Static(HINTS['sessions'], id='hint')

    def tree(self):
        tree = FolderTree(tree_label(self.rows[0]), data=self.rows[0], id='tree')
        tree.auto_expand = False         # раскрытие решает on_tree_node_selected
        tree.root.expand()
        by_path = {self.rows[0].path: tree.root}
        stale = {r.path for r in self.rows if r.depth == 2 and not c.is_fresh(r, self.now)}
        busy = {os.path.dirname(r.path) for r in self.rows if r.depth == 2 and c.is_fresh(r, self.now)}
        old = {}                         # раздел → свёрнутый узел «давно не открывались»
        for r in self.rows[1:]:
            if not c.visible(r):
                continue
            up = os.path.dirname(r.path.replace('/.claude/worktrees', ''))
            parent = by_path.get(up)
            if parent is None:
                continue
            if r.path in stale:
                if up not in old:
                    n = sum(1 for s in stale if os.path.dirname(s) == up)
                    old[up] = parent.add(f'[dim]давно не открывались · {n}[/]', expand=False)
                parent = old[up]
            by_path[r.path] = parent.add(tree_label(r), data=r, expand=(r.depth == 1 and r.path in busy), allow_expand=False)
        for node in by_path.values():
            if node.children:
                node.allow_expand = True
        return tree

    def modes(self, mode):
        on, off = '[reverse bold] {} [/]', '[dim] {} [/]'
        s, f = (on, off) if mode == 'sessions' else (off, on)
        return f'{s.format("Сессии")} {f.format("Папки")}   [dim]Tab — переключить[/]'

    def on_mount(self):
        try:
            self.theme = THEME
        except Exception:
            pass
        for b in self.query(Button):
            b.can_focus = False
        self.query_one('#name_box').display = False
        self.show_folder(self.rows[0])
        self.fill_list()
        self.query_one('#q').focus()
        self.load_items()

    @work(thread=True, exclusive=True, group='items')
    def load_items(self):
        items = c.all_sessions(self.rows)
        try:
            self.call_from_thread(self.set_items, items)
        except RuntimeError:          # окно уже закрыто
            pass

    def set_items(self, items):
        self.items = items
        self.fill_list()
        self.show_folder(self.current)

    @property
    def mode(self):
        return self.query_one('#switch').current

    # ---------- сессии ----------
    def fill_list(self):
        lst = self.query_one('#list', OptionList)
        lst.clear_options()
        self.picks = {}
        if self.items is None:
            lst.add_option(Option(Text('читаю сессии…', 'dim'), disabled=True))
            return
        query = self.query_one('#q', Input).value
        words = c._words(query)
        found, dirs = c.find_sessions(self.items, query), c.find_folders(self.rows, query)
        opts = []
        for n, it in enumerate(found):
            self.picks[f's{n}'] = ('s', it)
            opts.append(Option(session_line(it, words), id=f's{n}'))
        if not found and not dirs:
            opts.append(Option(Text('ничего не нашлось' if words else 'сессий пока нет', 'dim'), disabled=True))
        if dirs:
            opts.append(Option(Text('Новая сессия в папке', 'bold'), disabled=True))
            for n, r in enumerate(dirs):
                self.picks[f'd{n}'] = ('d', r)
                opts.append(Option(folder_line(r, words), id=f'd{n}'))
        lst.add_options(opts)
        first = next((i for i, o in enumerate(opts) if not o.disabled), None)
        lst.highlighted = first
        if first is None:
            self.query_one('#detail', Static).update('')
        else:
            self.show_pick(opts[first].id)

    def show_pick(self, oid):
        pick = self.picks.get(oid)
        det = self.query_one('#detail', Static)
        if pick is None:
            return
        kind, x = pick
        if kind == 'd':
            det.update(folder_view(x))
            return
        f = x['brief']['file']
        det.update(detail_view(x, self.details.get(f)))
        if f not in self.details:
            self.load_detail(oid, x)

    @work(thread=True, exclusive=True, group='detail')
    def load_detail(self, oid, item):
        try:
            d = c.session_detail(item['brief']['file'])
        except OSError:
            return
        try:
            self.call_from_thread(self.fill_detail, oid, item, d)
        except RuntimeError:
            pass

    def fill_detail(self, oid, item, d):
        self.details[item['brief']['file']] = d
        lst = self.query_one('#list', OptionList)
        hi = lst.highlighted_option
        if hi is not None and hi.id == oid and self.picks.get(oid, (None, None))[1] is item:
            self.query_one('#detail', Static).update(detail_view(item, d))

    def open_pick(self, pick):
        kind, x = pick
        if kind == 'd':
            return self.ask_name(x)
        action = c.open_action(x['brief']['id'], x['row'].live)
        if action.startswith('busy:'):
            self.notify('Эта сессия уже открыта в другом терминале — переключитесь туда.', severity='warning')
            return
        self.finish(x['row'], action)

    def on_input_changed(self, ev: Input.Changed):
        if ev.input.id == 'q':
            self.fill_list()

    def on_input_submitted(self, ev: Input.Submitted):
        if ev.input.id == 'name':
            self.finish(self.new_row, 'new', c.session_name(self.new_row, ev.value.strip()))
            return
        hi = self.query_one('#list', OptionList).highlighted_option
        if hi is not None and hi.id in self.picks:
            self.open_pick(self.picks[hi.id])

    def on_option_list_option_highlighted(self, ev: OptionList.OptionHighlighted):
        if ev.option_list.id == 'list' and ev.option.id:
            self.show_pick(ev.option.id)

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected):
        picks = self.picks if ev.option_list.id == 'list' else self.work_picks
        if ev.option.id in picks:
            self.open_pick(picks[ev.option.id])

    # ---------- папки ----------
    def show_folder(self, r):
        self.current = r
        self.query_one('#title', Static).update(f'[bold]{esc(nice_name(r))}[/]  [dim]{esc(r.path.replace(c.H, "~"))}[/]')
        self.query_one('#what', Static).update(esc(r.what))
        self.query_one('#meta', Static).update(f'где живёт: {esc(r.where)}' if r.where else '')
        self.query_one('#continue', Button).display = bool(r.sessions)
        guests = set(r.visitors)
        mine = [i for i in (self.items or []) if i['row'] is r or i['brief']['file'] in guests][:WORK_LIMIT]
        work = self.query_one('#work', OptionList)
        work.clear_options()
        self.work_picks = {f'w{n}': ('s', it) for n, it in enumerate(mine)}
        work.add_options([Option(session_line(it, here=r), id=f'w{n}') for n, it in enumerate(mine)])
        if self.items is None:
            head = 'Работа над этой папкой  [dim]читаю сессии…[/]'
        elif mine:
            head = f'Работа над этой папкой · {len(mine)}'
        else:
            head = 'Работы здесь пока не было  [dim]Enter — начать[/]'
        self.query_one('#work_h', Static).update(head)

    def on_tree_node_highlighted(self, ev: Tree.NodeHighlighted):
        if ev.node.data is not None:
            self.show_folder(ev.node.data)

    def on_tree_node_selected(self, ev: Tree.NodeSelected):
        r = ev.node.data
        if r is None or r.depth == 1:     # «давно не открывались» и разделы: Enter раскрывает
            ev.node.toggle()
            return
        self.ask_name(r)

    # ---------- действия ----------
    def finish(self, row, action, name=''):
        self.exit((row, action, name))

    def ask_name(self, row):
        self.new_row = row
        base = c.session_name(row, '')
        self.query_one('#name_label', Static).update(
            f'Новая сессия в [bold]{esc(nice_name(row))}[/], имя «{esc(base)} · …»   [dim]Enter — начать, Esc — отмена[/]')
        self.query_one('#name', Input).value = ''
        self.query_one('#name_box').display = True
        self.query_one('#name', Input).focus()

    def _close_name_box(self):
        box = self.query_one('#name_box')
        if not box.display:
            return False
        box.display = False
        self.query_one('#q' if self.mode == 'sessions' else '#tree').focus()
        return True

    def action_switch(self):
        self._close_name_box()
        mode = 'folders' if self.mode == 'sessions' else 'sessions'
        self.query_one('#switch').current = mode
        self.query_one('#modes', Static).update(self.modes(mode))
        self.query_one('#hint', Static).update(HINTS[mode])
        self.query_one('#q' if mode == 'sessions' else '#tree').focus()

    def action_back(self):
        if self._close_name_box():
            return
        if self.mode == 'sessions':
            q = self.query_one('#q', Input)
            if q.value:
                q.value = ''
                q.focus()
                return
        elif self.focused is not None and self.focused.id == 'work':
            self.query_one('#tree').focus()
            return
        self.exit(None)

    def action_move(self, n):
        if self.mode != 'sessions' or self.focused is None or self.focused.id != 'q':
            return
        lst = self.query_one('#list', OptionList)
        for _ in range(abs(n)):
            lst.action_cursor_down() if n > 0 else lst.action_cursor_up()

    def action_to_work(self):
        work = self.query_one('#work', OptionList)
        if self.mode == 'folders' and self.focused is not None and self.focused.id == 'tree' and work.option_count:
            work.focus()
            work.highlighted = 0

    def _in_folders(self):
        return self.mode == 'folders'          # буквы в полях ввода до привязок окна не доходят

    def action_go_continue(self):
        if self._in_folders() and self.current.sessions:
            self.finish(self.current, 'continue')

    def action_go_new(self):
        if self._in_folders():
            self.ask_name(self.current)

    def action_quit(self):
        self.exit(None)

    def on_button_pressed(self, ev: Button.Pressed):
        if ev.button.id == 'new':
            self.ask_name(self.current)
        elif ev.button.id == 'continue':
            self.finish(self.current, 'continue')


def main():
    rows = c.add_activity(c.add_stats(c.discover()))
    result = Pult(rows).run()
    if result:
        row, action, name = result
        c.launch(row, action, name)


if __name__ == '__main__':
    main()
