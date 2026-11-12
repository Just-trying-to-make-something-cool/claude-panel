"""Панель управления папками Claude: окно в терминале (Textual). Данные и запуск — в core.py.

Два режима, Tab переключает.

Папки — с него окно открывается. Дерево ~/claude, только имена: раскрыт KVANT LAB, остальные разделы
свёрнуты. В разделе сверху папки, где работа шла за две недели, остальное свёрнуто в «давно не
открывались». Справа описание папки, сколько в ней сессий и последние из них, в том числе запущенные
из раздела выше. Enter — новая сессия (спросит, о чём; на разделе — раскрыть), c — продолжить
последнюю, → — к сессиям папки, q — выход. Мышь работает.

Сессии — строка поиска, под ней все ваши сессии из всех папок ~/claude: ждущие ответа первыми,
дальше свежие выше. Справа — что внутри выбранной: где запущена и где работала, когда, первый
и последний запрос, последний ответ. Печатайте слова из названия, запроса или имени папки —
список сужается, ниже появляются папки, где можно начать новую сессию. ↑↓ выбрать, Enter открыть,
Esc очистить поиск, ещё раз — выход. Прогоны без человека (claude -p) не показываются.
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
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.content import Content  # noqa: E402
from textual.theme import Theme  # noqa: E402
from textual.widgets import Button, ContentSwitcher, Input, OptionList, Static, Tree  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402

SEG_ORDER = ['kvant-lab', 'clients', 'infra', 'personal', 'work', 'claude-settings']
SEG_NAMES = c.SEG_NAMES
ATTN = 'bold #f5c542'     # то, что ждёт человека
GO = 'bold #7bd88f'       # идёт прямо сейчас
STATUS = {'ЖДЁТ': f'[{ATTN}]● ждёт ответа[/]', 'работает': f'[{GO}]● идёт[/]', 'живая': '[dim]○ открыта[/]', '': ''}
DOT = {'ЖДЁТ': f'[{ATTN}]●[/]', 'работает': f'[{GO}]●[/]', 'живая': '[dim]○[/]', '': ' '}
THEME = os.environ.get('C_THEME', 'pult')
PULT = Theme(name='pult', dark=True, primary='#4c7dff', secondary='#8a7dff', accent='#6ea8ff',
             foreground='#e6e9ef', background='#0e1117', surface='#151a23', panel='#1c2230',
             success='#7bd88f', warning='#f5c542', error='#ff6b6b', boost='#1f2a40')
WORK_LIMIT = 8
BROKEN = ('ошибка входа', 'ошибка API', 'лимит')
OPEN_SEG = 'kvant-lab'    # раскрыт при открытии, как в первой версии окна
KEY = '[bold reverse] {} [/] {}'
HINTS = {'sessions': '   '.join(KEY.format(k, v) for k, v in (
             ('⏎', 'открыть'), ('↑↓', 'выбрать'), ('аб', 'печатайте, чтобы искать'), ('Tab', 'к папкам'), ('Esc', 'выход'))),
         'folders': '   '.join(KEY.format(k, v) for k, v in (
             ('⏎', 'новая сессия'), ('C', 'продолжить'), ('→', 'сессии папки'), ('↑↓', 'папки'),
             ('Tab', 'поиск по всем сессиям'), ('Q', 'выход')))}


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


def short_what(what, n=30):
    """Первая смысловая часть описания: «Подсказчик созвона» из «„Подсказчик созвона“: окно поверх…»."""
    t = ' '.join(str(what).split())
    t = re.split(r'(?<=\S)[:;.(]\s| — | – |, ', t, maxsplit=1)[0].strip(' «»"„“')
    return c._cut(t, n) if t else ''


def tree_label(r):
    """Точка состояния (жёлтая — ждёт ответа, зелёная — идёт), имя и тусклая подпись «что это».
    Даты и счётчики — в карточке справа: в дереве они делали строки пёстрыми."""
    st = c._status(r)
    if r.depth < 2:
        name = f'[bold]{esc(nice_name(r))}[/]'
        return f'{name}  {STATUS[st]}' if st else name
    name = esc(r.label)
    if not (r.what or r.sessions) and r.depth == 2:
        name = f'[dim]{name}[/]'
    sub = short_what(r.what) if r.what else ''
    return f'{DOT[st]} {name}' + (f'  [dim]{esc(sub)}[/]' if sub else '')


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
        t.highlight_words(words, 'bold underline', case_sensitive=False)
    return t


def live_word(s):
    """Одно слово для живой сессии — то же правило, что у дерева (core._status)."""
    if s.get('blocked'):
        return 'ждёт ответа'
    return 'идёт' if s.get('state') in ('busy', 'working') else 'открыта'


def live_style(live):
    return ATTN if live.get('blocked') else GO if live_word(live) == 'идёт' else 'dim'


def unmd(s):
    """Ответ Claude без разметки Markdown: звёздочки, обратные кавычки, решётки заголовков, линии."""
    s = re.sub(r'\*\*|__|`', '', str(s))
    s = re.sub(r'(?m)^\s*(#{1,6}\s+|[-—─=]{3,}\s*$|>\s?)', '', s)
    return s


def first_sentence(s, n):
    s = ' '.join(str(s).split())
    m = re.match(r'(.{20,}?[.!?])\s', s)
    return c._cut(m.group(1) if m else s, n)


def same(a, b):
    """Запрос повторяет название (название часто и есть первая строка запроса)."""
    a, b = _line(a, 400).rstrip('…'), _line(b, 400).rstrip('…')
    k = min(len(a), len(b), 40)
    return k > 0 and a[:k] == b[:k]


def session_line(item, words=(), here=None, d=None, lines=2):
    """Карточка сессии: имя (у гостя — откуда запущена), справа состояние и когда; ниже тусклым
    последний запрос человека, а если стенограмма уже прочитана — первая фраза ответа Claude."""
    b = item['brief']
    name = _lit(item['name'], words)
    name.stylize('bold')
    if here is not None and item['row'] is not here:
        name.append(f'  · из {nice_name(item["row"])}', 'dim')
    live, tags = item['live'] or {}, Text(no_wrap=True)
    tags.append('  ')
    if live:
        tags.append('● ' + live_word(live) + '  ', live_style(live))
    if b['auto']:
        tags.append('робот  ', 'dim')
    tags.append(c.when(b['last']), 'dim')
    t = Table.grid(expand=True)
    t.add_column(ratio=1, no_wrap=True, overflow='ellipsis')
    t.add_column(no_wrap=True, justify='right')
    t.add_row(name, tags)
    asked = (d or {}).get('last_user') or b['last_user'] or b['first']
    if lines >= 2 and asked and not same(asked, item['name']):
        t.add_row(Text.assemble(('  ты      ', 'dim bold'), (_line(asked, 400), 'dim')), '')
    if lines >= 3 and d and d.get('last_answer'):
        t.add_row(Text.assemble(('  Claude  ', 'dim bold'), (first_sentence(unmd(d['last_answer']), 400), 'dim italic')), '')
    if lines >= 2:
        t.add_row('', '')                  # воздух между карточками
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
    t.add_column(style='bold dim', no_wrap=True, min_width=16)
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
    if b['first']:
        add('первый запрос', _line(b['first'], 300))
    last_user = (d or {}).get('last_user') or b['last_user']
    if last_user and _line(last_user, 300) != _line(b['first'], 300):
        add('последний запрос', _line(last_user, 300))
    if live and live.get('blocked'):
        add('сейчас', 'ждёт вашего ответа', ATTN)
    elif live and live.get('kind') == 'interactive':
        add('сейчас', 'открыта в другом терминале — переключитесь туда')
    elif live and live_word(live) == 'идёт':
        add('сейчас', 'идёт прямо сейчас')
    elif live:
        add('сейчас', 'открыта в фоне, сейчас ничего не делает')
    elif d and d['error'] == 'ошибка входа':
        add('чем кончилась', 'оборвалась на ошибке входа — откройте, выполните /login и напишите «продолжи»', ATTN)
    elif d and d['error'] == 'лимит':
        add('чем кончилась', 'оборвалась на лимите — когда лимит обновится, откройте и напишите «продолжи»', ATTN)
    elif d and d['error'] in BROKEN:
        add('чем кончилась', f'оборвалась: {d["error"]} — откройте и напишите «продолжи»', ATTN)
    elif d and d['error'] == 'без ответа':
        add('чем кончилась', 'последний запрос остался без ответа')
    if d is None:
        add('', 'читаю стенограмму…', 'dim')
    elif d['last_answer']:
        add('последний ответ', _line(d['last_answer'], 400))
    head = Text(c._cut(item['name'], 140), 'bold')
    if live:
        head.append('   ● ' + live_word(live), live_style(live))
    head.append(f'   {b["id"][:8]}', 'dim')
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
    Screen { layout: vertical; background: $background; }
    #top { height: 3; padding: 1 2 0 2; background: $panel; }
    #brand { width: auto; color: $accent; text-style: bold; margin-right: 3; }
    #modes { width: auto; height: 1; }
    #summary { width: 1fr; text-align: right; color: $text-muted; padding-right: 1; }
    #switch { height: 1fr; }
    #sessions { padding: 0 1; }
    #q { margin: 1 1 0 1; border: round $accent 50%; background: $surface; }
    #q:focus { border: round $accent; }
    #sbody { height: 1fr; margin-top: 1; }
    #list { width: 55%; border: round $panel-lighten-2; padding: 0 1; background: $surface; }
    #list > .option-list--option { padding: 0 0 1 0; }
    #detail { width: 1fr; padding: 1 2; margin-left: 1; border: round $panel-lighten-2; }
    #folders { padding: 1 1 0 1; }
    #tree { width: 40%; padding: 1 1; background: $surface; border: round $panel-lighten-2; overflow-x: hidden; scrollbar-size-vertical: 1; }
    #tree:focus { border: round $accent 70%; }
    #tree > .tree--cursor { background: $accent 30%; text-style: none; }
    #tree:focus > .tree--cursor { background: $accent 45%; }
    #tree > .tree--guides, #tree > .tree--guides-hover, #tree > .tree--guides-selected { color: $panel-lighten-1; }
    #card { width: 1fr; padding: 1 2; margin-left: 1; border: round $panel-lighten-2; scrollbar-size-vertical: 1; }
    #title { height: auto; }
    #what { margin-top: 1; }
    #meta { color: $text-muted; margin-top: 1; }
    .sec { margin-top: 1; color: $accent; text-style: bold; }
    #last { height: auto; padding: 0 1; border-left: thick $accent 60%; background: $boost; }
    #buttons { height: auto; margin-top: 1; margin-bottom: 1; }
    #buttons Button { margin-right: 1; min-width: 0; padding: 0 2; height: 3; border: round $accent 60%; background: transparent; color: $text; text-style: bold; }
    #buttons Button:hover { background: $accent 25%; border: round $accent; }
    #buttons #new { background: $accent; color: $background; border: round $accent; }
    #buttons #new:hover { background: $accent-lighten-1; }
    #work_h { margin-top: 1; }
    #work { height: auto; max-height: 1fr; border: none; padding: 0; background: transparent; }
    #work > .option-list--option { padding: 0 0 1 0; }
    #name_box { height: auto; padding: 1 2; border-top: thick $accent; background: $panel; }
    #name { border: round $accent; }
    #hint { height: 1; margin: 0 1; padding: 0 1; background: $panel; color: $text-muted; }
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
        with Horizontal(id='top'):
            yield Static('◆ Claude', id='brand')
            yield Static(self.modes('folders'), id='modes')
            yield Static(self.summary(), id='summary')
        with ContentSwitcher(initial='folders', id='switch'):
            with Vertical(id='sessions'):
                yield Input(placeholder='найти: слово из названия, запроса или имени папки', id='q')
                with Horizontal(id='sbody'):
                    yield OptionList(id='list')
                    yield Static('', id='detail')
            with Horizontal(id='folders'):
                yield self.tree()
                with VerticalScroll(id='card'):
                    yield Static('', id='title')
                    yield Static('', id='what')
                    yield Static('', id='meta')
                    with Horizontal(id='buttons'):
                        yield Button('⏎  Новая сессия', id='new')
                        yield Button('C  Продолжить', id='continue')
                        yield Button('→  Все сессии', id='all')
                    yield Static('Где остановились', id='last_h', classes='sec')
                    yield Static('', id='last')
                    yield Static('', id='work_h', classes='sec')
                    yield OptionList(id='work')
        with Vertical(id='name_box'):
            yield Static('', id='name_label')
            yield Input(placeholder='о чём сессия, например «бизнес» (можно пусто)', id='name')
        yield Static(HINTS['folders'], id='hint')

    def tree(self):
        tree = FolderTree(tree_label(self.rows[0]), data=self.rows[0], id='tree')
        tree.auto_expand = False         # раскрытие решает on_tree_node_selected
        tree.guide_depth = 3
        tree.root.expand()
        by_path = {self.rows[0].path: tree.root}
        stale = {r.path for r in self.rows if r.depth == 2 and not c.is_fresh(r, self.now)}
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
            by_path[r.path] = parent.add(tree_label(r), data=r, expand=(r.depth == 1 and r.label == OPEN_SEG),
                                         allow_expand=False)
        for node in by_path.values():
            if node.children:
                node.allow_expand = True
        return tree

    def modes(self, mode):
        on, off = '[bold reverse] {} [/]', '[dim] {} [/]'
        f, s = (on, off) if mode == 'folders' else (off, on)
        return f'{f.format("▤ Папки")}  {s.format("☰ Все сессии")}   [dim]Tab — переключить[/]'

    def summary(self):
        """Справа вверху: сколько сессий ждут ответа и сколько идут — по всем папкам."""
        seen, wait, run = set(), 0, 0
        for r in self.rows:
            for s in r.live:
                sid = s.get('sessionId') or s.get('id')
                if sid in seen:
                    continue
                seen.add(sid)
                wait += bool(s.get('blocked'))
                run += not s.get('blocked') and live_word(s) == 'идёт'
        parts = [f'[{ATTN}]● ждут ответа: {wait}[/]' if wait else '', f'[{GO}]● идут: {run}[/]' if run else '']
        return '   '.join(p for p in parts if p) or 'все сессии спокойны'

    def on_mount(self):
        self.register_theme(PULT)
        try:
            self.theme = THEME
        except Exception:
            pass
        for b in self.query(Button):
            b.can_focus = False
        self.query_one('#list').can_focus = False     # клик выбирает строку, а буквы по-прежнему идут в поиск
        self.query_one('#name_box').display = False
        self.show_folder(self.rows[0])
        self.fill_list()
        self.query_one('#tree').focus()
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
        action = c.open_action(x['brief']['id'], [x['live']] if x['live'] else [])
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
        path = r.path.replace(c.H, '~')
        st = c._status(r)
        title = f'[bold $accent]{esc(nice_name(r))}[/]' + (f'   {STATUS[st]}' if st else '')
        if path != nice_name(r):
            title += f'\n[dim]{esc(path)}[/]'
        self.query_one('#title', Static).update(title)
        what = self.query_one('#what', Static)
        what.update(esc(r.what))
        what.display = bool(r.what)
        meta = [f'где живёт: {esc(r.where)}'] if r.where else []
        if self.items is None:
            n, last = r.sessions, r.last
        else:                              # прогоны робота не в счёт: их нет и в списке ниже
            own = self.own_sessions(r)
            n, last = len(own), max((i['brief']['last'] for i in own), default=0)
        if n:
            meta.append(f'{sessions_word(n)}, последняя {c._ago(last)}')
        self.query_one('#meta', Static).update('\n'.join(meta))
        self.query_one('#meta').display = bool(meta)
        guests = set(r.visitors)
        mine = [i for i in (self.items or []) if i['row'] is r or i['brief']['file'] in guests]
        shown = mine[:WORK_LIMIT]
        latest = self.latest_own(r)
        self.query_one('#continue', Button).display = bool(n or latest)
        self.query_one('#all', Button).display = bool(shown)
        self.fill_last(r, mine)
        work = self.query_one('#work', OptionList)
        work.clear_options()
        self.work_picks = {f'w{n}': ('s', it) for n, it in enumerate(shown)}
        work.add_options([Option(session_line(it, here=r, d=self.details.get(it['brief']['file']), lines=3), id=f'w{n}')
                          for n, it in enumerate(shown)])
        if self.items is None:
            head = 'Сессии в этой папке  [dim]читаю…[/]'
        elif len(mine) > len(shown):
            head = f'Сессии в этой папке  [dim]{len(shown)} из {len(mine)}, остальные — Tab, поиск[/]'
        elif mine:
            head = f'Сессии в этой папке  [dim]{len(mine)}[/]'
        else:
            head = 'Сессий здесь пока не было  [dim]⏎ — начать первую[/]'
        self.query_one('#work_h', Static).update(head)
        need = [it for it in shown if it['brief']['file'] not in self.details]
        if need:
            self.load_folder_details(r, need)

    def latest_own(self, r):
        """Что продолжает C: последняя человеческая сессия папки, а если своих нет — последняя
        зашедшая сюда из раздела выше (откроется там, где запущена)."""
        own = self.own_sessions(r)
        if not own:
            guests = set(r.visitors)
            own = [i for i in (self.items or []) if i['brief']['file'] in guests and not i['brief']['auto']]
        return max(own, key=lambda i: i['brief']['last']) if own else None

    def fill_last(self, r, mine):
        """«Где остановились»: последняя сессия папки — о чём, когда, твой последний запрос и ответ Claude."""
        it = mine[0] if mine else None
        box, head = self.query_one('#last', Static), self.query_one('#last_h', Static)
        box.display = head.display = it is not None
        if it is None:
            return
        b, d = it['brief'], self.details.get(it['brief']['file'])
        t = Table.grid(padding=(0, 2))
        t.add_column(style='bold dim', no_wrap=True)
        t.add_column(ratio=1)
        top = Text(c._cut(it['name'], 80), 'bold')
        when = Text(c.when(b['last']))
        if it['live']:
            when.append('   ● ' + live_word(it['live']), live_style(it['live']))
        t.add_row('когда', when)
        asked = (d or {}).get('last_user') or b['last_user'] or b['first']
        if asked and not same(asked, it['name']):
            t.add_row('ты', Text(_line(asked, 170)))
        if d is None:
            t.add_row('Claude', Text('читаю стенограмму…', 'dim'))
        elif d.get('error') in BROKEN:
            t.add_row('Claude', Text(f'оборвалась: {d["error"]} — открой и напиши «продолжи»', ATTN))
        elif d.get('last_answer'):
            t.add_row('Claude', Text(_line(unmd(d['last_answer']), 240), 'italic'))
        box.update(Group(top, t))

    @work(thread=True, exclusive=True, group='fdetail')
    def load_folder_details(self, r, items):
        got = {}
        for it in items:
            try:
                got[it['brief']['file']] = c.session_detail(it['brief']['file'])
            except OSError:
                pass
        try:
            self.call_from_thread(self.fill_folder_details, r, got)
        except RuntimeError:
            pass

    def fill_folder_details(self, r, got):
        self.details.update(got)
        if self.current is r and self.mode == 'folders':
            hi = self.query_one('#work', OptionList).highlighted
            self.show_folder(r)
            if hi is not None:
                self.query_one('#work', OptionList).highlighted = hi

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

    def own_sessions(self, r):
        """Человеческие сессии, запущенные в самой папке (без гостей и прогонов робота)."""
        return [i for i in (self.items or []) if i['row'] is r and not i['brief']['auto']]

    def continue_here(self):
        """Последняя человеческая сессия папки. `claude -c` взял бы самую свежую стенограмму —
        в корне это утренний прогон робота; он остаётся, только пока список сессий не прочитан."""
        r = self.current
        if self.items is None:
            if r.sessions:
                self.finish(r, 'continue')
            return
        latest = self.latest_own(r)
        if latest:
            self.open_pick(('s', latest))

    def action_go_continue(self):
        if self._in_folders():
            self.continue_here()

    def action_go_new(self):
        if self._in_folders():
            self.ask_name(self.current)

    def action_quit(self):
        if self._in_folders():                 # в «Сессиях» q — буква поиска, выход там — Esc
            self.exit(None)

    def on_button_pressed(self, ev: Button.Pressed):
        if ev.button.id == 'new':
            self.ask_name(self.current)
        elif ev.button.id == 'continue':
            self.continue_here()
        elif ev.button.id == 'all':
            self.query_one('#tree').focus()
            self.action_to_work()


def main():
    rows = c.add_activity(c.add_stats(c.discover()))
    result = Pult(rows).run()
    if result:
        row, action, name = result
        c.launch(row, action, name)


if __name__ == '__main__':
    main()
