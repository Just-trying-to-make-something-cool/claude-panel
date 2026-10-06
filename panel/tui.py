"""Панель управления папками Claude: окно в терминале (Textual). Данные и запуск — в core.py.

Слева дерево ~/claude: сегменты → проекты → части, у проекта число сессий и когда была последняя.
Справа карточка выбранного: описание, где живёт, файл памяти, последние сессии (имя или первая
реплика — видно, о чём она; Enter или клик — продолжить именно её), живые сессии, кнопки
«Продолжить», «Новая сессия», «Старые сессии», «Claude + Codex». Мышь работает.

Клавиши: ↑↓ по дереву · Enter продолжить · n новая · r старые · p пара с Codex · q / Esc выход.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402

from rich.markup import escape  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.widgets import Button, Footer, Input, OptionList, Static, Tree  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402

SEG_ORDER = ['kvant-lab', 'kvant-media', 'clients', 'infra', 'personal', 'work', 'claude-settings']
SEG_NAMES = {'kvant-lab': 'KVANT LAB', 'clients': 'Клиенты', 'infra': 'Инфра', 'personal': 'Личное',
             'work': 'Разовые задачи', 'claude-settings': 'Настройки Claude'}
DOT = {'ЖДЁТ': '[bold yellow]●[/]', 'работает': '[blue]●[/]', 'живая': '[green]●[/]', '': ''}


def status_text(r):
    s = c._status(r)
    return f'{DOT[s]} {s}' if s else ''


def seg_name(r):
    """Имя сегмента: заголовок его CLAUDE.md, иначе словарь, иначе имя папки."""
    return c.title_of(r.path, SEG_NAMES.get(r.label, r.label)) if os.path.isdir(r.path) else SEG_NAMES.get(r.label, r.label)


def tree_label(r):
    dot = DOT[c._status(r)]
    if r.depth == 1:
        return f'[bold $accent]{escape(seg_name(r))}[/]'
    name = escape(r.label)
    if not (r.what or r.sessions) and r.depth == 2:
        name = f'[dim]{name}[/]'
    tail = f' [dim]· {r.sessions} сесс. · {c._ago(r.last)}[/]' if r.sessions else ''
    return f'{name}{tail} {dot}'.rstrip()


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
    #body { height: 1fr; }
    #tree { width: 38%; min-width: 30; border: round $accent; padding: 0 1; }
    #tree:focus { border: round $accent-lighten-2; }
    #card { width: 1fr; border: round $secondary; padding: 0 1; background: $surface; }
    #title { text-style: bold; color: $accent-lighten-2; }
    #what { margin-top: 1; }
    #meta { color: $text-muted; }
    #buttons { height: auto; margin: 1 0; }
    #buttons Button { margin-right: 1; min-width: 14; }
    #name_box { height: auto; display: none; }
    #name_box.show { display: block; }
    #recent_h, #live_h { margin-top: 1; text-style: bold; color: $text-muted; }
    #live_h { color: $warning; }
    #recent, #live { height: auto; max-height: 9; border: none; }
    #hint { color: $text-muted; margin-top: 1; }
    """
    BINDINGS = [
        Binding('q', 'quit', 'выход'), Binding('escape', 'quit', 'выход', show=False),
        Binding('enter', 'go_continue', 'продолжить', priority=False),
        Binding('n', 'go_new', 'новая сессия'), Binding('r', 'go_resume', 'старые сессии'),
        Binding('p', 'go_pair', 'пара с Codex'),
    ]

    def __init__(self, rows):
        super().__init__()
        self.rows = ordered(rows)
        self.current = self.rows[0]

    def compose(self) -> ComposeResult:
        with Horizontal(id='body'):
            tree = Tree('~/claude', data=self.rows[0], id='tree')
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
                    yield Button('Продолжить', id='continue', variant='success')
                    yield Button('Новая сессия', id='new', variant='primary')
                    yield Button('Старые сессии', id='resume')
                    yield Button('Claude + Codex', id='pair', variant='warning')
                with Vertical(id='name_box'):
                    yield Static('', id='name_label')
                    yield Input(placeholder='направление, например «бизнес» (можно пусто)', id='name')
                yield Static('Последние сессии  [dim]Enter — продолжить именно её[/]', id='recent_h')
                yield OptionList(id='recent')
                yield Static('Живые сессии', id='live_h')
                yield OptionList(id='live')
                yield Static('', id='hint')
        yield Footer()

    def on_mount(self):
        self.show(self.rows[0])
        self.query_one('#tree').focus()

    # ---------- карточка ----------
    def show(self, r):
        self.current = r
        title = escape(seg_name(r)) if r.depth == 1 else escape(r.label)
        self.query_one('#title', Static).update(f'{title}  [dim]{escape(r.path.replace(c.H, "~"))}[/]')
        self.query_one('#what', Static).update(escape(r.what) or '[dim]описания нет: добавь строку в таблицу CLAUDE.md сегмента[/]')
        meta = []
        if r.where:
            meta.append(f'где живёт: {escape(r.where)}')
        if r.memo:
            meta.append(f'память: {escape(r.memo)}')
        meta.append(f'сессий: {r.sessions}' + (f', последняя {c._ago(r.last)}' if r.last else ''))
        self.query_one('#meta', Static).update('\n'.join(meta))
        self.query_one('#continue', Button).label = 'Продолжить' if r.sessions else 'Начать здесь'
        self.query_one('#resume', Button).display = bool(r.sessions)
        recent = self.query_one('#recent', OptionList)
        recent.clear_options()
        infos = c.session_info(r.path, 6) if r.sessions else []
        for sid, name, when in infos:
            recent.add_option(Option(f'[dim]{escape(when):>8}[/]  {escape(name)}', id=f'attach:{sid}'))
        self.query_one('#recent_h').display = bool(infos)
        recent.display = bool(infos)
        live = self.query_one('#live', OptionList)
        live.clear_options()
        for s in r.live:
            tag = 'ждёт ответа' if s['blocked'] else (s.get('state') or '')
            live.add_option(Option(f'{DOT["ЖДЁТ" if s["blocked"] else "живая"]} {escape(s.get("name") or "")}  [dim]{tag}[/]',
                                   id=f'attach:{s.get("sessionId")}'))
        self.query_one('#live_h').display = bool(r.live)
        live.display = bool(r.live)
        self.query_one('#hint', Static).update(f'в открытой сессии: /cd {escape(r.path)}')
        self.query_one('#name_box').remove_class('show')

    def on_tree_node_highlighted(self, ev: Tree.NodeHighlighted):
        if ev.node.data is not None:
            self.show(ev.node.data)

    def on_tree_node_selected(self, ev: Tree.NodeSelected):
        if ev.node.data is not None and ev.node.data.depth >= 2:
            self.finish('continue')

    # ---------- действия ----------
    def finish(self, action, name=''):
        self.exit((self.current, action, name))

    def action_go_continue(self):
        if self.focused is not None and self.focused.id in ('name', 'live', 'recent'):
            return
        if self.current.depth >= 2 or self.current.depth == 0:
            self.finish('continue')

    def action_go_new(self):
        if self.focused is not None and self.focused.id == 'name':
            return
        box = self.query_one('#name_box')
        box.add_class('show')
        base = c.session_name(self.current, '')
        self.query_one('#name_label', Static).update(f'Имя новой сессии: [bold]{escape(base)} · …[/]   Enter — запустить, Esc — отмена')
        inp = self.query_one('#name', Input)
        inp.value = ''
        inp.focus()

    def action_go_resume(self):
        if self.focused is not None and self.focused.id == 'name':
            return
        if self.current.sessions:
            self.finish('resume')

    def action_go_pair(self):
        if self.focused is not None and self.focused.id == 'name':
            return
        if self.current.depth >= 2 or self.current.depth == 0:
            self.finish('pair')

    def action_quit(self):
        if self.query_one('#name_box').has_class('show'):
            self.query_one('#name_box').remove_class('show')
            self.query_one('#tree').focus()
            return
        self.exit(None)

    def on_button_pressed(self, ev: Button.Pressed):
        {'continue': self.action_go_continue, 'new': self.action_go_new, 'resume': self.action_go_resume,
         'pair': self.action_go_pair}[ev.button.id]()

    def on_input_submitted(self, ev: Input.Submitted):
        self.finish('new', c.session_name(self.current, ev.value.strip()))

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected):
        if ev.option.id:
            self.finish(ev.option.id)


def main():
    rows = c.add_stats(c.discover())
    result = Pult(rows).run()
    if result:
        row, action, name = result
        c.launch(row, action, name)


if __name__ == '__main__':
    main()
