"""Панель управления папками Claude: данные, список мест запуска, запуск. Окно — tui.py.

c                 шаг 1: выбрать проект (fzf) → шаг 2: выбрать действие словами
c --list          таблица мест запуска текстом, без интерфейса
c --dry PATH [continue|new|resume] [имя]   показать команду запуска, не запуская
c --preview PATH  правая панель (служебное)

Шаг 1: проекты по сегментам, у каждого описание, число сессий, дата последней, статус живых.
Шаг 2: «Продолжить последнюю», «Новая сессия» (спросит имя), «Старые сессии», части проекта
(рабочие копии .claude/worktrees/* и подпапки со своим CLAUDE.md), «Назад».

Список строится из дерева ~/claude без конфига; описания из таблиц «| папка | что | где |»
в CLAUDE.md родителя. Внутри уже открытой сессии тот же переезд делает /cd <путь>.
"""
import dataclasses, glob, json, os, re, subprocess, sys, threading, time

H = os.path.expanduser('~')
ROOT = os.environ.get('C_ROOT', H + '/claude')
PROJECTS = H + '/.claude/projects'
SKIP = {'archive', 'node_modules'}
AGENT_WT = re.compile(r'^agent-[0-9a-f]{12,}$')   # служебные копии субагентов

# цвета
DIM, BOLD, RST = '\033[2m', '\033[1m', '\033[0m'
SEG, OK, WAIT, RUN = '\033[36m', '\033[32m', '\033[33m', '\033[34m'


def encode(path):
    """Имя папки стенограмм в ~/.claude/projects для данного cwd."""
    return re.sub(r'[^A-Za-z0-9]', '-', path)


def _clean(cell):
    cell = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', cell)
    return cell.replace('`', '').replace('**', '').strip()


def parse_table(md):
    """{имя папки: (что это, где живёт)} из строк таблиц markdown."""
    out = {}
    for line in md.splitlines():
        if not line.startswith('|') or set(line.replace('|', '').strip()) <= set('-: '):
            continue
        cells = [_clean(x) for x in line.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        name = cells[0].rstrip('/').split()[0] if cells[0].strip() else ''
        if not name or name in ('папка', 'бот', 'folder') or '/' in name:
            continue
        out[name] = (cells[1], cells[2] if len(cells) > 2 else '')
    return out


def _table_of(dirpath):
    try:
        with open(os.path.join(dirpath, 'CLAUDE.md'), encoding='utf-8') as fh:
            return parse_table(fh.read())
    except OSError:
        return {}


@dataclasses.dataclass
class Row:
    path: str
    depth: int          # 0 корень, 1 сегмент, 2 проект, 3 часть
    label: str
    what: str = ''
    where: str = ''
    project: str = ''   # имя проекта для имени сессии
    sessions: int = 0
    last: float = 0.0
    live: list = dataclasses.field(default_factory=list)


def _subdirs(d):
    try:
        return sorted(e.name for e in os.scandir(d)
                      if e.is_dir(follow_symlinks=False) and not e.name.startswith('.')
                      and e.name not in SKIP)
    except OSError:
        return []


def _is_part(d):
    return os.path.exists(os.path.join(d, 'CLAUDE.md')) or os.path.exists(os.path.join(d, '.git'))


def discover(root=ROOT):
    rows = [Row(root, 0, os.path.basename(root.rstrip('/')), 'корень: разбор задач, разовое', '', 'root')]
    seg_desc = _table_of(root)
    for seg in _subdirs(root):
        sp = os.path.join(root, seg)
        what, where = seg_desc.get(seg, ('', ''))
        rows.append(Row(sp, 1, seg, what, where, seg))
        proj_desc = _table_of(sp)
        for proj in _subdirs(sp):
            pp = os.path.join(sp, proj)
            what, where = proj_desc.get(proj, ('', ''))
            rows.append(Row(pp, 2, proj, what, where, proj))
            part_desc = _table_of(pp)
            for wt in _subdirs(os.path.join(pp, '.claude', 'worktrees')):
                rows.append(Row(os.path.join(pp, '.claude', 'worktrees', wt), 3, wt,
                                'рабочая копия', '', proj))
            for sub in _subdirs(pp):
                d = os.path.join(pp, sub)
                if _is_part(d):
                    what, where = part_desc.get(sub, ('', ''))
                    rows.append(Row(d, 3, sub, what, where, proj))
    return rows


def visible(r):
    """Третий уровень показываем, если он описан (CLAUDE.md), это рабочая копия или в нём были сессии."""
    if r.depth < 3:
        return True
    if AGENT_WT.match(r.label):
        return False
    return r.sessions > 0 or r.what == 'рабочая копия' or os.path.exists(os.path.join(r.path, 'CLAUDE.md'))


def session_name(row, query):
    base = row.project if row.depth < 3 else f'{row.project} · {row.label}'
    return f'{base} · {query}' if query else base


GENERIC_NAME = re.compile(r'^claude-\d+$')   # так claude agents зовёт сессию без имени


def group_live(agents, blocked=()):
    """{cwd: [живые сессии]} — по одной записи на сессию. Одна сессия бывает открыта в двух
    процессах (фоновая джоба и `claude --resume` в терминале), и claude agents отдаёт обе.
    Фоновая запись главнее в любом порядке: её короткий id нужен для `claude attach`."""
    out, by_id = {}, {}
    for s in agents:
        sid = s.get('sessionId')
        state = s.get('state') or s.get('status') or ''
        e = dict(s, state=state, blocked=sid in blocked or state == 'blocked')
        old = by_id.get(sid) if sid else None
        if old is None:
            if sid:
                by_id[sid] = e
            out.setdefault(s.get('cwd'), []).append(e)
            continue
        old['blocked'] = old['blocked'] or e['blocked']
        if state in ('busy', 'working'):
            old['state'] = state
        if e.get('kind') == 'background' and e.get('id'):
            old['kind'], old['id'] = 'background', e['id']
        if GENERIC_NAME.match(old.get('name') or '') and e.get('name'):
            old['name'] = e['name']
    return out


def open_action(sid, live, kind='session'):
    """Как открыть сессию: живую фоновую — `claude attach <id>`; открытую в другом терминале — никак
    (`busy:`): `claude -r` запустил бы второй процесс той же сессии; остальные — `claude -r`."""
    s = next((s for s in live if s.get('sessionId') == sid), None)
    if s and s.get('kind') == 'background' and s.get('id'):
        return f'bg:{s["id"]}'
    if s and s.get('kind') == 'interactive':
        return f'busy:{sid}'
    return f'{kind}:{sid}'


def add_stats(rows):
    agents = []
    try:
        out = subprocess.run(['claude', 'agents', '--json'], capture_output=True, text=True, timeout=8).stdout
        agents = json.loads(out or '[]')
    except Exception:
        pass
    blocked = set()
    for f in glob.glob(H + '/.claude/jobs/*/state.json'):
        try:
            with open(f) as fh:
                s = json.load(fh)
            if s.get('state') == 'blocked':
                blocked.add(s.get('sessionId'))
        except Exception:
            pass
    live = group_live(agents, blocked)
    for r in rows:
        stamps = [m for m in map(_mtime, glob.glob(os.path.join(PROJECTS, encode(r.path), '*.jsonl'))) if m]
        r.sessions = len(stamps)
        r.last = max(stamps, default=0.0)
        r.live = live.get(r.path, [])
    return rows


def session_names(path, n=6):
    """Имена последних сессий папки, свежие первыми; у безымянной — начало первого запроса."""
    names = []
    for f in folder_sessions(path, n):
        try:
            b = session_brief(f)
        except OSError:
            continue
        names.append(b['title'] or _cut(b['first'].split('\n')[0], 50) or 'без имени')
    return names


# ---------- что внутри сессии ----------
# Стенограммы бывают по 90 МБ: название и первый запрос берём из начала и хвоста файла,
# последний обмен — из хвоста, «где работала» — проходом по сырым байтам кусками. Кэш — по mtime.

HEAD, TAIL, HEAD_MAX, TAIL_MAX, CHUNK = 256 * 1024, 64 * 1024, 2 * 1024 * 1024, 8 * 1024 * 1024, 4 * 1024 * 1024
FIRST_MAX = 8 * 1024 * 1024   # третье окно: сводка продолжения бывает на ~4 МБ (1 файл из 1000)
CONTINUED = 'продолжение прошлой сессии: та упёрлась в предел контекста'
CONTINUATION = 'This session is being continued'
SKIP_PROMPT = ('<command-', '<local-command', '<task-notification', '<system-reminder', '<bash-',
               '<user-prompt-submit-hook', 'Caveat:', '[Request interrupted', CONTINUATION)
_TITLE = re.compile(rb'"customTitle":\s*"((?:[^"\\]|\\.)*)"')
_AGENT = re.compile(rb'"agentName":\s*"((?:[^"\\]|\\.)*)"')
_TS = re.compile(rb'"timestamp":\s*"([^"]+)"')
_CWD = re.compile(rb'"cwd":\s*"((?:[^"\\]|\\.)*)"')
_USER = re.compile(rb'"type":\s*"user"')
_cache, _locks, _guard = {}, {}, threading.Lock()


def _user_body(d):
    if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain'):
        return ''
    body = (d.get('message') or {}).get('content')
    if isinstance(body, list):
        body = '\n'.join(p.get('text', '') for p in body if isinstance(p, dict) and p.get('type') == 'text')
    return re.sub(r'</?pasted_content[^>]*>', '', body).strip() if isinstance(body, str) else ''


def user_text(d):
    """Реплика человека из строки стенограммы; служебное (команды, уведомления, сводки) — ''."""
    t = _user_body(d)
    return '' if not t or t.startswith(SKIP_PROMPT) else t


def _answer_text(d):
    if d.get('type') != 'assistant' or d.get('isSidechain'):
        return ''
    body = (d.get('message') or {}).get('content') or []
    return '\n'.join(p.get('text', '') for p in body if isinstance(p, dict) and p.get('type') == 'text').strip()


def _failure(d, text):
    """Вид обрыва, если запись — сообщение об ошибке API; иначе ''. Старые стенограммы без флага — по тексту."""
    if d.get('type') != 'assistant' or not (d.get('isApiErrorMessage') or text.startswith(('API Error', 'Please run /login'))):
        return ''
    code = str(d.get('error') or '')
    if code == 'rate_limit':
        return 'лимит'
    if code.startswith(('authentication', 'oauth')) or (not code and any(k in text for k in ('/login', '401', '403', 'OAuth'))):
        return 'ошибка входа'
    return 'ошибка API'


def _read(f, start, size):
    with open(f, 'rb') as fh:
        fh.seek(start)
        return fh.read(size)


def _records(blob, cut_first, only=None):
    """Строки-объекты JSONL из окна файла; обрезанные края окна пропускаются. only — сырой фильтр до разбора."""
    lines = blob.split(b'\n')
    if cut_first:
        lines = lines[1:]
    for line in lines:
        if not line.strip() or (only is not None and not only.search(line)):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            yield d


def _unq(raw):
    try:
        return json.loads(b'"' + raw + b'"')
    except ValueError:
        return raw.decode('utf-8', 'ignore')


def _epoch(iso):
    import datetime
    try:
        return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def _mtime(f):
    try:
        return os.path.getmtime(f)
    except OSError:              # стенограмму удалили между glob и stat
        return 0.0


def _cached(kind, f, build):
    """Один результат на файл и вид, пересчёт при изменении файла. Параллельные запросы одного
    файла (список и выбранная сессия) ждут один расчёт, а не читают файл дважды."""
    with _guard:
        lock = _locks.setdefault((kind, f), threading.Lock())
    with lock:
        st = os.stat(f)
        hit = _cache.get((kind, f))
        if hit is None or hit[0] != (st.st_mtime, st.st_size):
            hit = ((st.st_mtime, st.st_size), build(st))
            _cache[(kind, f)] = hit
        return hit[1]


def folder_sessions(path, limit=None, projects=None):
    """Файлы стенограмм сессий, запущенных из этой папки, свежие первыми."""
    stamped = [(m, f) for f in glob.glob(os.path.join(projects or PROJECTS, encode(path), '*.jsonl'))
               for m in [_mtime(f)] if m]
    files = [f for _, f in sorted(stamped, reverse=True)]
    return files[:limit] if limit else files


def _first_prompt(blob):
    """Первый запрос человека; если раньше него идёт сводка продолжения — CONTINUED."""
    for d in _records(blob, False, _USER):
        if user_text(d):
            return user_text(d)
        if _user_body(d).startswith(CONTINUATION):
            return CONTINUED
    return ''


def session_brief(f):
    """{id, file, title, first, started, last}: название, первый запрос, начало и последняя запись."""
    def build(st):
        head = _read(f, 0, HEAD)
        tail = _read(f, max(0, st.st_size - TAIL), TAIL) if st.st_size > HEAD else b''
        titles = _TITLE.findall(tail) or _TITLE.findall(head) or _AGENT.findall(tail) or _AGENT.findall(head)
        first, seen = _first_prompt(head), HEAD
        for span in (HEAD_MAX, FIRST_MAX):     # дальше читаем, только если предыдущее окно не накрыло файл
            if first or st.st_size <= seen:
                break
            first, seen = _first_prompt(_read(f, 0, span)), span
        ts = _TS.search(head)
        return {'id': os.path.basename(f)[:-6], 'file': f, 'title': _unq(titles[-1]) if titles else '',
                'first': first, 'started': _epoch(ts.group(1).decode()) if ts else 0.0, 'last': st.st_mtime}
    return _cached('brief', f, build)


def _place(cwd, root):
    if cwd == root:
        return '~/claude'
    if cwd.startswith(root + '/'):
        return '/'.join(cwd[len(root) + 1:].split('/')[:2])
    return cwd.replace(H, '~')


def _places(f, root):
    """[(проект, доля %)] по полям cwd, файл читается кусками по CHUNK."""
    counts, carry = {}, b''
    with open(f, 'rb') as fh:
        while True:
            chunk = fh.read(CHUNK)
            blob = carry + chunk
            cut = len(blob) if not chunk else blob.rfind(b'\n') + 1   # недописанная строка — в следующий кусок
            carry, blob = blob[cut:], blob[:cut]
            for raw in _CWD.findall(blob):
                p = _place(_unq(raw), root)
                counts[p] = counts.get(p, 0) + 1
            if not chunk:
                break
    total = sum(counts.values()) or 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [(p, round(100 * n / total)) for p, n in ranked[:3] if 100 * n / total >= 3]


def session_detail(f, root=ROOT):
    """{last_user, last_answer, error, branch, places}: чем сессия закончилась и в каких проектах шла работа."""
    def build(st):
        size, span = st.st_size, 256 * 1024
        while True:
            recs = list(_records(_read(f, max(0, size - span), span), size > span))
            last_user = last_answer = branch = failure = ''
            iu = ib = ie = -1          # ib — последнее действие Claude: текст или вызов инструмента
            for i, d in enumerate(recs):
                t = user_text(d)
                if t:
                    iu, last_user = i, t
                a = _answer_text(d)
                kind = _failure(d, a)
                if kind:
                    ie, failure = i, kind
                elif d.get('type') == 'assistant' and not d.get('isSidechain'):
                    ib, last_answer = i, a or last_answer
                branch = d.get('gitBranch') or branch
            if last_user or span >= size or span >= TAIL_MAX:
                break
            span = min(span * 4, TAIL_MAX)
        error = failure if ie > max(ib, iu) else 'без ответа' if iu > ib else ''
        return {'last_user': last_user, 'last_answer': last_answer, 'error': error, 'branch': branch,
                'places': _places(f, root)}
    return _cached('detail', f, build)

def when(ts, now=None):
    """«сегодня 09:05», «вчера 21:26», «03.10 16:18»."""
    if not ts:
        return ''
    now = now or time.time()
    lt = time.localtime(ts)
    if lt[:3] == time.localtime(now)[:3]:
        day = 'сегодня'
    elif lt[:3] == time.localtime(now - 86400)[:3]:
        day = 'вчера'
    else:
        day = time.strftime('%d.%m', lt)
    return f'{day} {time.strftime("%H:%M", lt)}'


def _ago(ts):
    if not ts:
        return ''
    d = (time.time() - ts) / 86400
    if d < 1:
        return 'сегодня'
    if d < 2:
        return 'вчера'
    return time.strftime('%d.%m', time.localtime(ts))


def _cut(s, n):
    return s if len(s) <= n else s[:n - 1] + '…'


def _status(r):
    if not r.live:
        return ''
    if any(s['blocked'] for s in r.live):
        return 'ЖДЁТ'
    if any(s.get('state') in ('busy', 'working') for s in r.live):
        return 'работает'
    return 'живая'


def _status_c(r):
    s = _status(r)
    return {'ЖДЁТ': WAIT + BOLD, 'работает': RUN, 'живая': OK}.get(s, '') + s + (RST if s else '')


def _sess(r):
    if not r.sessions:
        return ''
    return f'{r.sessions} сесс. · {_ago(r.last)}'


# ---------- шаг 1: проекты ----------

def place_lines(rows):
    """Строки шага 1: путь \\t видимая строка. Сегменты как заголовки, проекты под ними."""
    lines = []
    for r in rows:
        if r.depth == 3:
            continue
        if r.depth == 0:
            vis = f'{BOLD}{_cut("~/claude", 26):<26}{RST} {DIM}{_cut(r.what, 40):<40}{RST} {_sess(r):<20} {_status_c(r)}'
        elif r.depth == 1:
            vis = f'{SEG}{BOLD}{_cut(r.label + "/", 26):<26}{RST} {DIM}{_cut(r.what, 40):<40}{RST} {_sess(r):<20} {_status_c(r)}'
        else:
            dim = DIM if not (r.what or r.sessions) else ''
            vis = f'  {dim}{_cut(r.label, 24):<24}{RST} {_cut(r.what, 40):<40} {_sess(r):<20} {_status_c(r)}'
        lines.append(f'{r.path}\t{vis}')
    return lines


def plain(lines):
    return [re.sub(r'\033\[[0-9;]*m', '', l.split('\t', 1)[1]) for l in lines]


# ---------- шаг 2: действия ----------

def menu_items(row, rows):
    """[(код, видимая строка)] для выбранного места."""
    items = []
    if row.sessions:
        last = session_names(row.path, 1)
        items.append(('continue', f'▶  Продолжить последнюю сессию  {DIM}«{last[0] if last else ""}», {_ago(row.last)}{RST}'))
    items.append(('new', '✚  Новая сессия  ' + DIM + '(спрошу имя)' + RST))
    if row.sessions:
        items.append(('resume', f'↺  Старые сессии этой папки  {DIM}({row.sessions}){RST}'))
    for s in row.live:
        tag = 'ждёт ответа' if s['blocked'] else (s.get('state') or '')
        items.append((open_action(s.get('sessionId'), row.live, 'attach'), f'⟲  Подключиться к живой: {s.get("name")}  {DIM}{tag}{RST}'))
    parts = [p for p in rows if p.depth == row.depth + 1 and p.path.startswith(row.path + '/') and visible(p)]
    if parts:
        items.append(('sep', DIM + '── ' + ('части' if row.depth >= 2 else 'внутри') + ' ──' + RST))
        for p in parts:
            items.append((f'go:{p.path}', f'   {_cut(p.label, 24):<24} {DIM}{_cut(p.what, 36):<36}{RST} {_sess(p):<20} {_status_c(p)}'))
    items.append(('back', DIM + '←  Назад' + RST))
    return items


def preview(path):
    rows = {r.path: r for r in add_stats([r for r in discover() if r.path == path])}
    r = rows.get(path)
    print(BOLD + path.replace(H, '~') + RST)
    if r and r.what:
        print(r.what)
    if r and r.where:
        print('где живёт:', r.where)
    print(f'сессий: {r.sessions if r else 0}' + (f', последняя {_ago(r.last)}' if r and r.last else ''))
    for s in (r.live if r else []):
        print(f'  живая: {s.get("name")} [{"ждёт ответа" if s["blocked"] else s.get("state")}]')
    names = session_names(path)
    if names:
        print('\nпоследние сессии:')
        for n in names:
            print('  ', n)
    print(f'\n{DIM}в открытой сессии: /cd {path}{RST}')
    md = os.path.join(path, 'CLAUDE.md')
    if os.path.exists(md):
        print('\n--- CLAUDE.md ---')
        with open(md, encoding='utf-8', errors='ignore') as fh:
            for i, line in enumerate(fh):
                if i >= 20:
                    break
                print(line.rstrip()[:110])


def fzf(lines, prompt, header, query='', preview=True, height='80%'):
    """Возвращает путь/код первой колонки выбранной строки или ''."""
    me = os.path.abspath(__file__)
    args = ['fzf', '--delimiter=\t', '--with-nth=2', '--ansi', '--no-sort', '--layout=reverse',
            f'--height={height}', '--border=rounded', '--info=hidden', '--cycle',
            f'--prompt={prompt}', f'--header={header}', '--color=header:italic:dim,prompt:bold']
    if preview:
        args += ['--preview', f'python3 {me} --preview {{1}}', '--preview-window=right,42%,wrap,border-left']
    if query:
        args += ['--select-1', '--query', query]
    r = subprocess.run(args, input='\n'.join(lines), text=True, capture_output=True)
    return r.stdout.strip().split('\t', 1)[0] if r.returncode == 0 and r.stdout.strip() else ''


def launch(row, action, name=''):
    os.chdir(row.path)
    if action == 'resume':
        args = ['claude', '-r']
    elif action.startswith('busy:'):
        print('Эта сессия уже открыта в другом терминале — переключитесь туда.', file=sys.stderr)
        return
    elif action.startswith('bg:'):
        args = ['claude', 'attach', action[3:]]
    elif action.startswith(('attach:', 'session:')):
        args = ['claude', '-r', action.split(':', 1)[1]]
    elif action == 'new':
        args = ['claude', '-n', name or session_name(row, '')]
    else:
        args = ['claude', '-c'] if row.sessions else ['claude', '-n', session_name(row, '')]
    print(f'{DIM}→ {row.path.replace(H, "~")}  claude {" ".join(args[1:])}{RST}', file=sys.stderr)
    if os.environ.get('C_DRY'):
        return
    os.execvp('claude', args)


def ask_name(row):
    base = session_name(row, '')
    try:
        extra = input(f'Имя сессии: {base} · ').strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return f'{base} · {extra}' if extra else base


def main(argv):
    if '--preview' in argv:
        return preview(argv[argv.index('--preview') + 1])
    rows = add_stats(discover())
    if '--list' in argv:
        print('\n'.join(plain(place_lines(rows))))
        return
    if '--dry' in argv:
        i = argv.index('--dry')
        row = next(r for r in rows if r.path == os.path.abspath(argv[i + 1]))
        os.environ['C_DRY'] = '1'
        return launch(row, argv[i + 2] if len(argv) > i + 2 else 'continue', argv[i + 3] if len(argv) > i + 3 else '')

    q1, q2 = os.environ.get('C_QUERY', ''), os.environ.get('C_QUERY2', '')
    path = fzf(place_lines(rows), 'Куда? › ', '↑↓ выбрать · набери часть названия · Enter · Esc выход', q1)
    while path:
        row = next(r for r in rows if r.path == path)
        items = menu_items(row, rows)
        title = row.path.replace(H, '~') + (f'  —  {row.what}' if row.what else '')
        code = fzf([f'{c}\t{v}' for c, v in items], f'{row.label} › ', title, q2, preview=False,
                   height=str(min(len(items) + 4, 20)))
        if not code or code == 'back':
            path = '' if (not code and q1) else fzf(place_lines(rows), 'Куда? › ', '↑↓ выбрать · Enter · Esc выход')
            continue
        if code == 'sep':
            continue
        if code.startswith('go:'):
            path = code[3:]
            continue
        name = ''
        if code == 'new':
            name = ask_name(row) if not os.environ.get('C_DRY') else ''
            if name is None:
                continue
        return launch(row, code, name)


if __name__ == '__main__':
    main(sys.argv[1:])
