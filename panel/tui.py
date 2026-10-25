"""Панель управления папками Claude: окно в терминале (Textual). Данные и запуск — в core.py.

Слева дерево ~/claude: корень, сегменты → проекты → части. У каждого видно, когда была последняя сессия,
у корня и сегментов — сколько сессий запущено прямо из них. Справа карточка выбранного: описание,
где живёт, кнопки «Продолжить», «Новая сессия», «Все сессии», живые сессии и список сессий папки.
Под списком — что внутри выбранной сессии: первый и последний запрос, чем закончилась, где шла работа.

Клавиши: ↑↓ по дереву · Enter продолжить (на сегменте — раскрыть) · Tab к списку сессий, Enter открыть
выбранную · n новая · r все сессии · Esc назад к дереву, ещё раз — выход · q выход. Мышь работает.
"""
import os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402

from rich.console import Group  # noqa: E402
from rich.markup import escape as rich_escape  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.widgets import Button, Footer, Input, OptionList, Static, Tree  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402
from textual.worker import get_current_worker  # noqa: E402

SEG_ORDER = ['kvant-lab', 'clients', 'infra', 'personal', 'work', 'claude-settings']
SEG_NAMES = {'kvant-lab': 'KVANT LAB', 'clients': 'Клиенты', 'infra': 'Инфра', 'personal': 'Личное',
             'work': 'Разовые задачи', 'claude-settings': 'Настройки Claude'}
SEG_ICONS = {'kvant-lab': '🧪', 'clients': '🤝', 'infra': '🧰', 'personal': '🌿', 'work': '📌', 'claude-settings': '🔧'}
DOT = {'ЖДЁТ': '[bold yellow]●[/]', 'работает': '[blue]●[/]', 'живая': '[green]●[/]', '': ''}
THEME = os.environ.get('C_THEME', 'catppuccin-mocha')
LIST_LIMIT = 30                     # в папках автоворонки по 1300 сессий: показываем свежие
BROKEN = ('ошибка входа', 'ошибка API', 'лимит')
STATES = {'working': 'работает', 'busy': 'работает', 'idle': 'свободна'}


def esc(s):
    """Текст с диска для разметки Textual: экранируется каждая «[». Штатный escape пропускает
    незакрытые, и обрезанное «…скажи [Im…» роняло окно с MarkupError."""
    return re.sub(r'\\+(?=\[)', '', str(s)).rstrip('\\').replace('[', '\\[')


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


def status_text(r):
    s = c._status(r)
    return f'{DOT[s]} {s}' if s else ''


def tree_label(r):
    """У корня и сегментов — число своих сессий, у проектов — когда была последняя."""
    if r.depth == 0:
        name = '[bold]~/claude[/]'
    elif r.depth == 1:
        name = f'{SEG_ICONS.get(r.label, "•")} [bold]{esc(nice_name(r))}[/]'
    else:
        name = esc(r.label)
        if not (r.what or r.sessions) and r.depth == 2:
            name = f'[dim]{name}[/]'
    tail = ''
    if r.sessions:
        tail = f'[dim]{sessions_word(r.sessions)} · {c._ago(r.last)}[/]' if r.depth < 2 else f'[dim]{c._ago(r.last)}[/]'
    return '  '.join(x for x in (name, DOT[c._status(r)], tail) if x)


def greeting(rows, now=None):
    """Верхняя строка: приветствие по времени суток, живые сессии, где работали последний раз."""
    h = time.localtime(now or time.time()).tm_hour
    hi = 'Доброй ночи' if h < 5 else 'Доброе утро' if h < 12 else 'Добрый день' if h < 18 else 'Добрый вечер'
    parts = [f'[bold]{hi}![/]']
    rows = [r for r in rows if c.visible(r)]
    live = [s for r in rows for s in r.live]
    if live:
        wait = sum(1 for s in live if s.get('blocked'))
        parts.append(f'живых сессий в ~/claude: {len(live)}' + (f', [bold yellow]ждут ответа: {wait}[/]' if wait else ''))
    last = max(rows, key=lambda r: r.last)
    if last.last:
        names = c.session_names(last.path, 1)
        title = f'«{esc(names[0])}» ' if names else ''
        parts.append(f'последняя работа: {title}в {esc(last.path.replace(c.H, "~"))}, {c.when(last.last)}')
    return '   '.join(parts)


def _line(s, n):
    return c._cut(' '.join(s.split()), n)


def session_line(b, d=None, here='', live=None):
    """Строка списка: метка, название (у безымянной — первый запрос), когда, куда уходила работа."""
    title = c._cut(b['title'], 56) if b['title'] else _line(b['first'], 48) or 'без имени'
    live = live or {}
    if b['id'] in live:
        mark = '[bold yellow]●[/]' if live[b['id']] else '[green]●[/]'
    else:
        mark = '[yellow]⚠[/]' if d and d['error'] in BROKEN else ' '
    line = f'{mark} {esc(title)}  [dim]{c.when(b["last"])}[/]'
    away = [p for p, n in (d or {}).get('places', []) if p != here and n >= 20]
    if away:
        line += f'  [dim italic]→ {esc(away[0])}[/]'
    return line


def detail_view(b, d, live=None):
    """Что внутри сессии: даты, где работала, первый и последний запрос, чем закончилась."""
    t = Table.grid(padding=(0, 2))
    t.add_column(style='dim', no_wrap=True)
    t.add_column(ratio=1)
    add = lambda k, v: t.add_row(k, Text.from_markup(v))
    when = [f'начата {c.when(b["started"])}' if b['started'] else '', f'последняя запись {c.when(b["last"])}']
    if d and d['branch'] not in ('', 'HEAD'):
        when.append(f'ветка {rich_escape(d["branch"])}')
    add('когда', ' · '.join(x for x in when if x))
    if d and d['places']:
        add('где работала', ' · '.join(f'{rich_escape(p)} [dim]{n}%[/]' for p, n in d['places']))
    if b['first']:
        add('первый запрос', rich_escape(_line(b['first'], 220)))
    if d is None:
        add('', '[dim]читаю стенограмму…[/]')
    else:
        if d['last_user'] and _line(d['last_user'], 220) != _line(b['first'], 220):
            add('последний запрос', rich_escape(_line(d['last_user'], 220)))
        if live and live.get('blocked'):
            add('сейчас', '[bold yellow]● ждёт вашего ответа[/]')
        elif live and live.get('kind') == 'interactive':
            add('сейчас', '[green]● открыта в другом терминале[/] — переключитесь туда')
        elif live:
            add('сейчас', '[green]● идёт прямо сейчас[/]')
        elif d['error'] == 'ошибка входа':
            add('чем кончилась', '[yellow]⚠ оборвалась на ошибке входа[/] — откройте, выполните /login и напишите «продолжи»')
        elif d['error'] == 'лимит':
            add('чем кончилась', '[yellow]⚠ оборвалась на лимите[/] — когда лимит обновится, откройте и напишите «продолжи»')
        elif d['error'] == 'ошибка API':
            add('чем кончилась', '[yellow]⚠ оборвалась на ошибке API[/] — откройте и напишите «продолжи»')
        elif d['error'] == 'без ответа':
            add('чем кончилась', '[yellow]⚠ последний запрос остался без ответа[/]')
        if d['last_answer']:
            add('последний ответ', rich_escape(_line(d['last_answer'], 260)))
    title = rich_escape(b['title'] or 'сессия без имени')
    return Group(Text.from_markup(f'[bold]{title}[/]  [dim]{b["id"][:8]}[/]'), Text(''), t,
                 Text.from_markup('\n[dim]Tab — к списку · Enter — открыть выбранную сессию[/]'))


def ordered(rows):
    """Сегменты в рабочем порядке (KVANT LAB первым), внутри — как на диске."""
    root = rows[0].path
    seg_of = lambda r: os.path.relpath(r.path, root).split('/')[0]
    segs = sorted({seg_of(r) for r in rows if r.depth >= 1},
                  key=lambda s: (SEG_ORDER.index(s) if s in SEG_ORDER else 99, s))
    out = [rows[0]]
    for seg in segs:
        out += [r for r in rows if r.depth >= 1 and seg_of(r) == seg]
    return out


class Pult(App):
    TITLE = 'Claude · пульт'
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #hello { height: auto; padding: 1 2 0 2; color: $text-muted; }
    #body { height: 1fr; padding: 1 1 0 1; }
    #tree { width: 40%; min-width: 34; padding: 0 1; background: $surface;
            border: round $primary 50%; border-title-color: $primary; border-title-style: bold; }
    #tree:focus { border: round $primary; }
    #card { width: 1fr; margin-left: 1; padding: 0 2; background: $surface;
            border: round $secondary 50%; border-title-color: $secondary; border-title-style: bold;
            border-subtitle-color: $text-muted; }
    #card:focus-within { border: round $secondary; }
    #title { color: $text-muted; margin-top: 1; }
    #what { margin-top: 1; }
    #meta { color: $text-muted; }
    #buttons { height: auto; margin: 1 0 0 0; }
    #buttons Button { margin-right: 2; padding: 0 1; }
    #new, #resume { background: $panel; }
    #name_box { height: auto; display: none; margin-top: 1; }
    #name_box.show { display: block; }
    .section { margin-top: 1; color: $accent; text-style: bold; }
    #live { height: auto; max-height: 6; border: none; padding: 0; background: $surface; }
    #sessions { height: 1fr; min-height: 3; border: none; padding: 0; background: $surface; }
    #detail { height: auto; max-height: 18; margin: 1 0; padding: 1 2; background: $boost;
              border-left: wide $accent; }
    """
    BINDINGS = [
        Binding('q', 'quit', 'выход'), Binding('escape', 'back', 'назад', show=False),
        Binding('enter', 'go_continue', 'продолжить', priority=False),
        Binding('n', 'go_new', 'новая сессия'), Binding('r', 'go_resume', 'все сессии'),
        Binding('tab', 'app.focus_next', 'папки ⇄ сессии', priority=True),
    ]

    def __init__(self, rows):
        super().__init__()
        self.rows = ordered(rows)
        self.current = self.rows[0]
        self.briefs, self.details = {}, {}

    def compose(self) -> ComposeResult:
        yield Static(greeting(self.rows), id='hello')
        with Horizontal(id='body'):
            tree = Tree(tree_label(self.rows[0]), data=self.rows[0], id='tree')
            tree.auto_expand = False     # раскрытие решает on_tree_node_selected: Enter на корне продолжает
            tree.root.expand()
            by_path = {self.rows[0].path: tree.root}
            for r in self.rows[1:]:
                if not c.visible(r):
                    continue
                parent = by_path.get(os.path.dirname(r.path.replace('/.claude/worktrees', '')))
                if parent is None:
                    continue
                node = parent.add(tree_label(r), data=r, expand=(r.depth == 1 and r.label == SEG_ORDER[0]), allow_expand=False)
                by_path[r.path] = node
            for node in by_path.values():
                if node.children:
                    node.allow_expand = True
            yield tree
            with Vertical(id='card'):
                yield Static('', id='title')
                yield Static('', id='what')
                yield Static('', id='meta')
                with Horizontal(id='buttons'):
                    yield Button('▶ Продолжить', id='continue', variant='primary', compact=True)
                    yield Button('＋ Новая сессия', id='new', compact=True)
                    yield Button('↺ Все сессии', id='resume', compact=True)
                with Vertical(id='name_box'):
                    yield Static('', id='name_label')
                    yield Input(placeholder='направление, например «бизнес» (можно пусто)', id='name')
                yield Static('Живые сессии', id='live_h', classes='section')
                yield OptionList(id='live')
                yield Static('', id='sess_h', classes='section')
                yield OptionList(id='sessions')
                yield Static('', id='detail')
        yield Footer()

    def on_mount(self):
        try:
            self.theme = THEME
        except Exception:
            pass
        for b in self.query(Button):
            b.can_focus = False         # Tab ходит только между деревом и списками
        self.query_one('#tree').border_title = ' Папки '
        self.show(self.rows[0])
        self.query_one('#tree').focus()

    # ---------- карточка ----------
    def show(self, r):
        self.current = r
        path = r.path.replace(c.H, '~')
        card = self.query_one('#card')
        card.border_title = f' {esc(nice_name(r))} '
        card.border_subtitle = f'в открытой сессии: /cd {esc(path)}'
        self.query_one('#title', Static).update(esc(path))
        self.query_one('#what', Static).update(esc(c._cut(r.what, 180 if r.depth < 2 else 300)) if r.what else '')
        self.query_one('#meta', Static).update(f'где живёт: {esc(r.where)}' if r.where else '')
        btn = self.query_one('#continue', Button)
        btn.label = '▶ Продолжить' if r.sessions else '▶ Начать здесь'
        btn.display = r.depth != 1 or r.sessions > 0
        self.query_one('#resume', Button).display = bool(r.sessions)
        live = self.query_one('#live', OptionList)
        live.clear_options()
        seen = set()
        for s in r.live:
            sid = s.get('sessionId')
            if sid and sid in seen:             # страховка: повтор id валит OptionList
                continue
            seen.add(sid)
            tag = 'ждёт ответа' if s['blocked'] else STATES.get(s.get('state'), s.get('state') or '')
            live.add_option(Option(f'{DOT["ЖДЁТ" if s["blocked"] else "живая"]} {esc(s.get("name") or "")}  [dim]{tag}[/]',
                                   id=c.open_action(sid, r.live, 'attach') if sid else None))
        self.query_one('#live_h').display = bool(r.live)
        live.display = bool(r.live)
        if r.sessions:
            more = f'  [dim]показаны последние {LIST_LIMIT}[/]' if r.sessions > LIST_LIMIT else ''
            head = f'Сессии · {r.sessions}{more}'
        else:
            head = 'Сессий здесь пока не было  [dim]«Начать здесь» или n — новая[/]' if r.depth != 1 else \
                   'Сессий, запущенных прямо отсюда, нет  [dim]они живут в проектах ниже[/]'
        self.query_one('#sess_h', Static).update(head)
        self.query_one('#sessions', OptionList).clear_options()
        self.query_one('#sessions').display = bool(r.sessions)
        self.query_one('#detail').display = False
        self.query_one('#name_box').remove_class('show')
        self.briefs, self.details = {}, {}
        if r.sessions:
            self.load_sessions(r)
        else:
            self.workers.cancel_group(self, 'sessions')

    def _here(self, r):
        return c._place(r.path, c.ROOT)

    def _post(self, fn, *args):
        try:
            self.call_from_thread(fn, *args)
            return True
        except RuntimeError:        # окно уже закрыто («App is not running»)
            return False

    @work(thread=True, exclusive=True, group='sessions')
    def load_sessions(self, r):
        worker = get_current_worker()
        briefs = []
        for f in c.folder_sessions(r.path, LIST_LIMIT):
            try:
                briefs.append(c.session_brief(f))
            except OSError:
                continue
        if worker.is_cancelled or not self._post(self.fill_sessions, r, briefs):
            return
        for b in briefs:
            if worker.is_cancelled:
                return
            try:
                d = c.session_detail(b['file'])
            except OSError:
                continue
            if not self._post(self.fill_detail, r, b['id'], d):
                return

    @work(thread=True, exclusive=True, group='one')
    def load_one(self, r, b):
        try:
            d = c.session_detail(b['file'])
        except OSError:
            return
        self._post(self.fill_detail, r, b['id'], d)

    def fill_sessions(self, r, briefs):
        if self.current is not r:
            return
        live = {s.get('sessionId'): s['blocked'] for s in r.live}
        lst = self.query_one('#sessions', OptionList)
        lst.clear_options()
        self.briefs = {b['id']: b for b in briefs}
        lst.add_options([Option(session_line(b, self.details.get(b['id']), self._here(r), live), id=b['id']) for b in briefs])
        if briefs:
            lst.highlighted = 0
            self.show_detail(briefs[0]['id'])

    def fill_detail(self, r, sid, d):
        if self.current is not r or sid not in self.briefs:
            return
        self.details[sid] = d
        lst = self.query_one('#sessions', OptionList)
        live = {s.get('sessionId'): s['blocked'] for s in r.live}
        lst.replace_option_prompt(sid, session_line(self.briefs[sid], d, self._here(r), live))
        hi = lst.highlighted_option
        if hi is not None and hi.id == sid:
            self.show_detail(sid)

    def show_detail(self, sid):
        b = self.briefs.get(sid)
        if b is None:
            return
        live = next((s for s in self.current.live if s.get('sessionId') == sid), None)
        det = self.query_one('#detail', Static)
        det.update(detail_view(b, self.details.get(sid), live))
        det.display = True
        if sid not in self.details:
            self.load_one(self.current, b)

    def on_tree_node_highlighted(self, ev: Tree.NodeHighlighted):
        if ev.node.data is not None:
            self.show(ev.node.data)

    def on_tree_node_selected(self, ev: Tree.NodeSelected):
        r = ev.node.data
        if r is None:
            return
        if r.depth >= 2 or (r.depth == 0 and r.sessions):
            self.finish('continue')
        else:
            ev.node.toggle()            # сегмент: Enter раскрывает, продолжает кнопка

    def on_option_list_option_highlighted(self, ev: OptionList.OptionHighlighted):
        if ev.option_list.id == 'sessions' and ev.option.id:
            self.show_detail(ev.option.id)

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected):
        if not ev.option.id:
            return
        sessions = ev.option_list.id == 'sessions'
        action = c.open_action(ev.option.id, self.current.live) if sessions else ev.option.id
        if action.startswith('busy:'):
            self.notify('Эта сессия уже открыта в другом терминале — переключитесь туда.', severity='warning')
            return
        self.finish(action)

    # ---------- действия ----------
    def finish(self, action, name=''):
        self.exit((self.current, action, name))

    def action_go_continue(self):
        if self.focused is not None and self.focused.id in ('name', 'live', 'sessions'):
            return
        if self.current.depth != 1 or self.current.sessions:
            self.finish('continue')

    def action_go_new(self):
        if self.focused is not None and self.focused.id == 'name':
            return
        box = self.query_one('#name_box')
        box.add_class('show')
        base = c.session_name(self.current, '')
        self.query_one('#name_label', Static).update(f'Имя новой сессии: [bold]{esc(base)} · …[/]   Enter — запустить, Esc — отмена')
        inp = self.query_one('#name', Input)
        inp.value = ''
        inp.focus()

    def action_go_resume(self):
        if self.focused is not None and self.focused.id == 'name':
            return
        if self.current.sessions:
            self.finish('resume')

    def _close_name_box(self):
        if self.query_one('#name_box').has_class('show'):
            self.query_one('#name_box').remove_class('show')
            self.query_one('#tree').focus()
            return True
        return False

    def action_quit(self):
        if not self._close_name_box():
            self.exit(None)

    def action_back(self):
        if self._close_name_box():
            return
        if self.focused is not None and self.focused.id != 'tree':
            self.query_one('#tree').focus()
            return
        self.exit(None)

    def on_button_pressed(self, ev: Button.Pressed):
        {'continue': self.action_go_continue, 'new': self.action_go_new, 'resume': self.action_go_resume}[ev.button.id]()

    def on_input_submitted(self, ev: Input.Submitted):
        self.finish('new', c.session_name(self.current, ev.value.strip()))


def main():
    rows = c.add_stats(c.discover())
    result = Pult(rows).run()
    if result:
        row, action, name = result
        c.launch(row, action, name)


if __name__ == '__main__':
    main()
