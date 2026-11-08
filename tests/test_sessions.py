"""Тесты разбора стенограмм сессий: python3 -m unittest discover tests"""
import json, os, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402

ROOT = '/Users/x/claude'


def user(text, **kw):
    return dict({'type': 'user', 'message': {'role': 'user', 'content': text},
                 'timestamp': '2026-10-23T13:18:58.068Z', 'cwd': ROOT}, **kw)


def answer(text, **kw):
    return dict({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]},
                 'timestamp': '2026-10-24T21:25:23.026Z', 'cwd': ROOT, 'gitBranch': 'main'}, **kw)


def write(lines, d=None, name='s1'):
    d = d or tempfile.mkdtemp()
    p = os.path.join(d, name + '.jsonl')
    with open(p, 'w', encoding='utf-8') as fh:
        for x in lines:
            fh.write(json.dumps(x, ensure_ascii=False) + '\n')
    return p


class UserText(unittest.TestCase):
    def test_plain_prompt(self):
        self.assertEqual(c.user_text(user('оцени ТЗ')), 'оцени ТЗ')

    def test_skips_meta_commands_and_continuation(self):
        self.assertEqual(c.user_text(user('x', isMeta=True)), '')
        self.assertEqual(c.user_text(user('<command-name>/clear</command-name>')), '')
        self.assertEqual(c.user_text(user('<task-notification>готово</task-notification>')), '')
        self.assertEqual(c.user_text(user('This session is being continued from a previous conversation')), '')
        self.assertEqual(c.user_text(user([{'type': 'tool_result', 'content': 'ok'}])), '')

    def test_keeps_pasted_text_without_tags(self):
        self.assertEqual(c.user_text(user('<pasted_content id="ab12">\n4. Кейсы\n</pasted_content>')), '4. Кейсы')

    def test_text_parts_of_list_content(self):
        self.assertEqual(c.user_text(user([{'type': 'text', 'text': 'привет'}, {'type': 'image'}])), 'привет')


class Brief(unittest.TestCase):
    def test_title_from_head_when_tail_has_none(self):
        filler = [answer('ответ ' + 'х' * 200) for _ in range(400)]   # хвост длиннее окна чтения
        p = write([{'type': 'custom-title', 'customTitle': 'kvant-lab · оценка'},
                   user('оцени пожалуйста ERP запрос КП')] + filler)
        b = c.session_brief(p)
        self.assertEqual(b['title'], 'kvant-lab · оценка')
        self.assertEqual(b['first'], 'оцени пожалуйста ERP запрос КП')
        self.assertEqual(b['id'], 's1')

    def test_later_rename_in_tail_wins(self):
        p = write([{'type': 'custom-title', 'customTitle': 'старое'}, user('x'),
                   {'type': 'custom-title', 'customTitle': 'новое'}])
        self.assertEqual(c.session_brief(p)['title'], 'новое')

    def test_untitled_session_has_empty_title_and_first_prompt(self):
        p = write([{'type': 'mode', 'mode': 'normal'}, user('<command-name>/model</command-name>'),
                   user('сделай ролик про кейс')])
        b = c.session_brief(p)
        self.assertEqual(b['title'], '')
        self.assertEqual(b['first'], 'сделай ролик про кейс')
        self.assertGreater(b['started'], 0)


class Detail(unittest.TestCase):
    def test_last_exchange_branch_and_login_error(self):
        p = write([user('оцени ТЗ'), answer('Оценка готова.'), user('продолжи', timestamp='2026-10-24T21:25:19Z'),
                   answer('Please run /login · API Error: 401 OAuth access token has expired.')])
        d = c.session_detail(p, root=ROOT)
        self.assertEqual(d['last_user'], 'продолжи')
        self.assertEqual(d['branch'], 'main')
        self.assertEqual(d['error'], 'ошибка входа')
        self.assertEqual(d['last_answer'], 'Оценка готова.')   # последний настоящий ответ, не текст ошибки

    def test_error_followed_by_normal_answer_is_not_error(self):
        p = write([user('a'), answer('API Error: 500 overloaded'), user('продолжи'), answer('Продолжаю, готово.')])
        d = c.session_detail(p, root=ROOT)
        self.assertEqual((d['error'], d['last_answer']), ('', 'Продолжаю, готово.'))

    def test_answer_by_tool_call_is_not_unanswered(self):
        # автоматические прогоны кончаются вызовом инструмента без текста
        tool = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'StructuredOutput', 'input': {}}]}}
        result = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}
        p = write([user('Ситуация: лид ответил «давайте завтра»'), tool, result])
        self.assertEqual(c.session_detail(p, root=ROOT)['error'], '')

    def test_normal_ending_has_answer_and_no_error(self):
        p = write([user('оцени ТЗ'), answer('Оценка готова: этап А за 2 недели.')])
        d = c.session_detail(p, root=ROOT)
        self.assertEqual(d['error'], '')
        self.assertEqual(d['last_answer'], 'Оценка готова: этап А за 2 недели.')

    def test_unanswered_last_prompt(self):
        p = write([user('оцени ТЗ'), answer('готово'), user('а теперь ролик')])
        self.assertEqual(c.session_detail(p, root=ROOT)['error'], 'без ответа')

    def test_places_collapse_to_project_and_sort_by_share(self):
        lines = [user('x', cwd=ROOT)] * 2 + [answer('y', cwd=ROOT + '/kvant-lab/case-video/out/v4')] * 5 \
            + [answer('z', cwd=ROOT + '/kvant-lab/case-video')] * 1 + [answer('w', cwd=ROOT + '/kvant-lab/kp/.claude/worktrees/a')] * 2
        d = c.session_detail(write(lines), root=ROOT)
        self.assertEqual([p for p, _ in d['places']], ['kvant-lab/case-video', '~/claude', 'kvant-lab/kp'])
        self.assertEqual(d['places'][0][1], 60)


def api_error(text, code, **kw):
    return answer(text, isApiErrorMessage=True, error=code, **kw)


class Errors(unittest.TestCase):
    def test_rate_limit_by_field_keeps_last_real_answer(self):
        p = write([user('оцени ТЗ'), answer('Оценка готова.'), user('продолжи'),
                   api_error("You've hit your session limit · resets 3pm", 'rate_limit')])
        d = c.session_detail(p, root=ROOT)
        self.assertEqual((d['error'], d['last_answer']), ('лимит', 'Оценка готова.'))

    def test_auth_and_other_codes(self):
        p = write([user('a'), api_error('Your organization has disabled Claude subscription access', 'oauth_org_not_allowed')])
        self.assertEqual(c.session_detail(p, root=ROOT)['error'], 'ошибка входа')
        p = write([user('a'), api_error('model not found', 'model_not_found')])
        self.assertEqual(c.session_detail(p, root=ROOT)['error'], 'ошибка API')

    def test_answer_mentioning_api_error_is_normal(self):
        p = write([user('что в логе?'), answer('В логе есть API Error: 500 от Яндекса, это их сбой.')])
        d = c.session_detail(p, root=ROOT)
        self.assertEqual(d['error'], '')
        self.assertTrue(d['last_answer'].startswith('В логе есть API Error'))


class BigFiles(unittest.TestCase):
    """Окна чтения: файлы крупнее начального окна и хвоста."""
    filler = staticmethod(lambda n: [answer('x' * 1000) for _ in range(n)])   # ~1,2 КБ на строку

    def test_rename_in_tail_of_big_file_wins_over_head(self):
        p = write([{'type': 'custom-title', 'customTitle': 'старое'}, user('x')] + self.filler(700)
                  + [{'type': 'custom-title', 'customTitle': 'новое'}])
        self.assertGreater(os.path.getsize(p), 3 * c.HEAD)
        self.assertEqual(c.session_brief(p)['title'], 'новое')

    def test_title_between_head_and_tail_windows_is_found(self):
        # 256–320 КБ: раньше хвост не читался вовсе
        p = write([user('x')] + self.filler(225) + [{'type': 'custom-title', 'customTitle': 'середина'}] + self.filler(20))
        self.assertTrue(c.HEAD < os.path.getsize(p) < c.HEAD + c.TAIL + 40000)
        self.assertEqual(c.session_brief(p)['title'], 'середина')

    def test_first_prompt_after_head_window(self):
        p = write(self.filler(400) + [user('настоящий первый запрос')] + self.filler(10))
        self.assertEqual(c.session_brief(p)['first'], 'настоящий первый запрос')

    def test_continuation_session_says_so(self):
        p = write([user('This session is being continued from a previous conversation that ran out of context.')]
                  + self.filler(10))
        self.assertEqual(c.session_brief(p)['first'], c.CONTINUED)

    def test_continuation_summary_beyond_second_window(self):
        p = write(self.filler(1900) + [dict(user('This session is being continued from a previous conversation.'),
                                            isCompactSummary=True), user('продолжай')])
        self.assertGreater(os.path.getsize(p), c.HEAD_MAX)
        self.assertEqual(c.session_brief(p)['first'], c.CONTINUED)

    def test_detail_window_grows_to_reach_last_prompt(self):
        p = write([user('первый'), user('последний запрос')] + self.filler(700))
        self.assertEqual(c.session_detail(p, root=ROOT)['last_user'], 'последний запрос')

    def test_non_object_json_lines_do_not_crash(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 's.jsonl')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('[1, 2]\n"строка"\n42\n' + json.dumps(user('привет'), ensure_ascii=False) + '\n')
        self.assertEqual(c.session_brief(p)['first'], 'привет')
        self.assertEqual(c.session_detail(p, root=ROOT)['last_user'], 'привет')

    def test_cache_keeps_one_entry_per_file(self):
        p = write([user('a')])
        c.session_brief(p)
        with open(p, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(user('b'), ensure_ascii=False) + '\n')
        c.session_brief(p)
        self.assertEqual(sum(1 for k in c._cache if k[0] == 'brief' and k[1] == p), 1)


class Folder(unittest.TestCase):
    def test_vanished_file_is_skipped(self):
        projects = tempfile.mkdtemp()
        folder = os.path.join(projects, c.encode('/Users/x/claude/kvant-lab'))
        os.makedirs(folder)
        write([user('живая')], folder, 'ok')
        os.symlink(os.path.join(folder, 'нет.jsonl'), os.path.join(folder, 'gone.jsonl'))   # glob видит, stat падает
        files = c.folder_sessions('/Users/x/claude/kvant-lab', projects=projects)
        self.assertEqual([os.path.basename(f) for f in files], ['ok.jsonl'])

    def test_sessions_newest_first_with_limit(self):
        projects = tempfile.mkdtemp()
        folder = os.path.join(projects, c.encode('/Users/x/claude/kvant-lab'))
        os.makedirs(folder)
        for i, name in enumerate(['old', 'mid', 'new']):
            p = write([user(name)], folder, name)
            os.utime(p, (1000 + i, 1000 + i))
        files = c.folder_sessions('/Users/x/claude/kvant-lab', limit=2, projects=projects)
        self.assertEqual([os.path.basename(f) for f in files], ['new.jsonl', 'mid.jsonl'])


class When(unittest.TestCase):
    def test_today_yesterday_and_date(self):
        now = time.mktime((2026, 10, 25, 12, 0, 0, 0, 0, -1))
        self.assertEqual(c.when(time.mktime((2026, 10, 25, 9, 5, 0, 0, 0, -1)), now), 'сегодня 09:05')
        self.assertEqual(c.when(time.mktime((2026, 10, 24, 21, 26, 0, 0, 0, -1)), now), 'вчера 21:26')
        self.assertEqual(c.when(time.mktime((2026, 10, 3, 16, 18, 0, 0, 0, -1)), now), '03.10 16:18')
        self.assertEqual(c.when(0, now), '')


if __name__ == '__main__':
    unittest.main()


class Activity(unittest.TestCase):
    """Где недавно шла работа: свои сессии, части, живые, и сессии из корня, уходившие в папку."""
    DAY = 86400

    def setUp(self):
        self.root, self.projects = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.cache = os.path.join(tempfile.mkdtemp(), 'places.json')
        for p in ('kvant-lab/takt', 'kvant-lab/autovoronka/.claude/worktrees/prod', 'kvant-lab/old', 'work/2026-11-08-check'):
            os.makedirs(os.path.join(self.root, p))
        self.now = time.time()

    def session(self, folder, lines, age_days, name='s1', auto=False):
        d = os.path.join(self.projects, c.encode(os.path.join(self.root, folder) if folder else self.root))
        os.makedirs(d, exist_ok=True)
        head = [dict(user('x', cwd=self.root), entrypoint='sdk-cli' if auto else 'cli')]
        p = write(head + lines, d, name)
        t = self.now - age_days * self.DAY
        os.utime(p, (t, t))
        return p

    def rows(self):
        rows = c.discover(self.root)
        for r in rows:                      # как add_stats, только без claude agents и с тестовой папкой стенограмм
            stamps = [c._mtime(f) for f in c.folder_sessions(r.path, projects=self.projects)]
            r.sessions, r.last = len(stamps), max(stamps, default=0.0)
        c.add_activity(rows, now=self.now, projects=self.projects, cache=self.cache)
        return {r.label: r for r in rows}

    def test_own_part_and_live_sessions(self):
        self.session('kvant-lab/takt', [], 2)
        self.session('kvant-lab/autovoronka/.claude/worktrees/prod', [], 1)
        self.session('kvant-lab/old', [], 30)
        rows = self.rows()
        self.assertTrue(c.is_fresh(rows['takt'], self.now))
        self.assertTrue(c.is_fresh(rows['autovoronka'], self.now))       # работа шла в рабочей копии
        self.assertFalse(c.is_fresh(rows['old'], self.now))
        rows['old'].live = [{'sessionId': 'a'}]
        rows = {r.label: r for r in c.add_activity(list(rows.values()), now=self.now, projects=self.projects, cache=self.cache)}
        self.assertTrue(c.is_fresh(rows['old'], self.now))

    def test_root_session_lifts_folder_it_worked_in_but_robot_does_not(self):
        here = os.path.join(self.root, 'kvant-lab', 'old', 'src')
        self.session('', [answer('y', cwd=here)] * 5, 3)
        self.session('', [answer('y', cwd=os.path.join(self.root, 'work/2026-11-08-check'))] * 5, 0, 's2', auto=True)
        rows = self.rows()
        self.assertTrue(c.is_fresh(rows['old'], self.now))
        self.assertAlmostEqual(rows['old'].active, self.now - 3 * self.DAY, delta=1)
        self.assertFalse(c.is_fresh(rows['2026-11-08-check'], self.now))

    def test_root_session_older_than_window_is_not_read(self):
        p = self.session('', [answer('y', cwd=os.path.join(self.root, 'kvant-lab/old'))] * 5, c.FRESH_DAYS + 1)
        self.assertFalse(c.is_fresh(self.rows()['old'], self.now))
        with open(self.cache) as fh:
            self.assertNotIn(p, json.load(fh)['files'])       # старые стенограммы не читаются вовсе

    def test_cache_reads_only_new_tail(self):
        p = self.session('', [answer('y', cwd=os.path.join(self.root, 'kvant-lab/old'))] * 5, 1)
        self.rows()
        with open(self.cache) as fh:
            d = json.load(fh)
        self.assertEqual(d['files'][p]['pos'], os.path.getsize(p))
        d['files'][p]['counts'] = {'kvant-lab/takt': 1000}       # подмена: если файл перечитан с нуля, её не будет
        with open(self.cache, 'w') as fh:
            json.dump(d, fh)
        with open(p, 'a') as fh:
            fh.write(json.dumps(answer('z', cwd=os.path.join(self.root, 'work/2026-11-08-check'))) + '\n')
        os.utime(p, (self.now - self.DAY, self.now - self.DAY))
        rows = self.rows()
        self.assertTrue(c.is_fresh(rows['takt'], self.now))
        with open(self.cache) as fh:
            self.assertEqual(json.load(fh)['files'][p]['counts']['work/2026-11-08-check'], 1)

    def test_broken_cache_gives_same_answer_as_cold(self):
        p = self.session('', [answer('y', cwd=os.path.join(self.root, 'kvant-lab/old'))] * 5, 1)
        cold = {k: r.active for k, r in self.rows().items()}
        for junk in ('не json', json.dumps({'root': self.root, 'files': {p: {'pos': 10 ** 9, 'counts': {}, 'auto': False}}}),
                     json.dumps({'root': self.root, 'files': {p: {'pos': 'x'}}}), json.dumps({'root': '/elsewhere', 'files': {}})):
            with open(self.cache, 'w') as fh:
                fh.write(junk)
            self.assertEqual({k: r.active for k, r in self.rows().items()}, cold, junk)
