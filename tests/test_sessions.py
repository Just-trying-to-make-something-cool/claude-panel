"""Подписи сессий, имя сегмента из CLAUDE.md, колонка «память», действие «пара с Codex»:
.venv/bin/python -m unittest discover tests"""
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from panel import core as c  # noqa: E402


def write_session(projects, path, lines, name=None):
    d = os.path.join(projects, c.encode(path)); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, 'abcdef12-0000.jsonl')
    with open(f, 'w', encoding='utf-8') as fh:
        for l in lines:
            fh.write(json.dumps(l, ensure_ascii=False) + '\n')
        if name:   # Claude Code пишет журнал компактно, без пробелов после двоеточий
            fh.write(json.dumps({'type': 'custom-title', 'customTitle': name}, ensure_ascii=False, separators=(',', ':')) + '\n')
    return f


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.old = c.PROJECTS; c.PROJECTS = self.tmp

    def tearDown(self):
        c.PROJECTS = self.old

    def test_first_ask_when_no_name(self):
        write_session(self.tmp, '/x/p', [
            {'type': 'user', 'message': {'content': '<system-reminder>служебное</system-reminder>'}},
            {'type': 'user', 'isMeta': True, 'message': {'content': 'мета'}},
            {'type': 'user', 'message': {'content': [{'type': 'text', 'text': 'сделай  сайт\nномер 9'}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'ок'}]}},
        ])
        sid, name, when = c.session_info('/x/p')[0]
        self.assertEqual(sid, 'abcdef12-0000')
        self.assertEqual(name, 'сделай сайт номер 9')
        self.assertEqual(when, 'сегодня')

    def test_custom_title_wins(self):
        write_session(self.tmp, '/x/p', [{'type': 'user', 'message': {'content': 'первая реплика'}}], name='takt · бизнес')
        self.assertEqual(c.session_names('/x/p'), ['takt · бизнес'])

    def test_long_ask_is_cut(self):
        write_session(self.tmp, '/x/p', [{'type': 'user', 'message': {'content': 'а' * 200}}])
        name = c.session_info('/x/p')[0][1]
        self.assertEqual(len(name), 90)
        self.assertTrue(name.endswith('…'))


class Tables(unittest.TestCase):
    md = '# Студия KVANT LAB\n\n| папка | что | где | память |\n|---|---|---|---|\n| takt | таск-менеджер | VPS | `takt.md`, с блока «ПРОДОЛЖЕНИЕ» |\n| sova | сайт | | |\n'

    def test_memo_column(self):
        m = c.parse_memo(self.md)
        self.assertEqual(m['takt'], 'takt.md, с блока «ПРОДОЛЖЕНИЕ»')
        self.assertEqual(m['sova'], '')
        self.assertEqual(c.parse_table(self.md)['takt'], ('таск-менеджер', 'VPS'))

    def test_title_from_claude_md(self):
        d = tempfile.mkdtemp()
        self.assertEqual(c.title_of(d, 'запас'), 'запас')
        with open(os.path.join(d, 'CLAUDE.md'), 'w', encoding='utf-8') as fh:
            fh.write(self.md)
        self.assertEqual(c.title_of(d), 'Студия KVANT LAB')


class Pair(unittest.TestCase):
    def test_pair_action_is_dry_safe(self):
        d = tempfile.mkdtemp(); os.environ['C_DRY'] = '1'
        try:
            c.launch(c.Row(d, 2, 'p', project='p'), 'pair')   # без C_DRY вызвал бы rev
        finally:
            del os.environ['C_DRY']


if __name__ == '__main__':
    unittest.main()
