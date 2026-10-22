"""UI language lifecycle, complete catalogs and stable message identities."""
import ast
import json
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input import i18n
from armada_dual_screen_input.i18n import configure, msg, tr, LocalizedState
from armada_dual_screen_input.input_settings import SettingsDraft, read_settings, write_settings
from armada_dual_screen_input.keyboard_language_view import visible
from armada_dual_screen_input.keyboard_languages import KeyboardLanguages
from armada_dual_screen_input.panel_position import PanelPosition
from armada_dual_screen_input.updates import UpdateError
import update as worker


class I18nTests(unittest.TestCase):
    def setUp(self):
        previous = i18n.active_language()
        configure('en_US')
        self.addCleanup(configure, previous)

    def test_absent_invalid_language_defaults_to_english_without_changing_input(self):
        for value in (None, {}, [], False, 'fr_FR', 'en', 0):
            self.assertEqual(read_settings({'ui_language': value})['ui_language'], 'en_US')
        self.assertEqual(read_settings({})['ui_language'], 'en_US')
        self.assertEqual(read_settings({'keyboard_language': 'zh_CN'})['keyboard_language'], 'zh_CN')
        self.assertEqual(read_settings({'ui_language': 'zh_CN'})['keyboard_language'], 'en_US')

    def test_system_resolution_respects_locale_precedence_and_english_fallback(self):
        cases = [({}, 'en_US'), ({'LANG': 'zh_CN.UTF-8'}, 'zh_CN'),
                 ({'LANG': 'en_US.UTF-8', 'LC_MESSAGES': 'zh_TW.UTF-8'}, 'zh_CN'),
                 ({'LANG': 'zh_CN', 'LC_ALL': 'en_GB.UTF-8'}, 'en_US'),
                 ({'LANG': 'zh_CN', 'LANGUAGE': 'fr:en:zh'}, 'en_US'),
                 ({'LANG': 'en_GB', 'LANGUAGE': 'zh-CN:en'}, 'zh_CN'),
                 ({'LC_ALL': 'C.UTF-8', 'LANGUAGE': 'zh_CN'}, 'en_US'),
                 ({'LANG': 'POSIX', 'LANGUAGE': 'zh_CN'}, 'en_US'),
                 ({'LANG': 'fr_FR.UTF-8'}, 'en_US')]
        for environ, expected in cases:
            with self.subTest(environ=environ):
                self.assertEqual(i18n.resolve_language('auto', environ), expected)
                self.assertEqual(i18n.resolve_language('en_US', environ), 'en_US')
                self.assertEqual(i18n.resolve_language('zh_CN', environ), 'zh_CN')

    def test_catalogs_have_matching_keys_and_named_placeholders(self):
        self.assertEqual(set(i18n.EN_US), set(i18n.ZH_CN))
        for key, english in i18n.EN_US.items():
            self.assertTrue(english.strip(), key)
            chinese = i18n.ZH_CN[key]
            en_fields = {name for _, name, _, _ in Formatter().parse(english) if name is not None}
            zh_fields = {name for _, name, _, _ in Formatter().parse(chinese) if name is not None}
            self.assertEqual(en_fields, zh_fields, key)
            self.assertTrue(all(field.isidentifier() for field in en_fields), key)
            for language in ('en_US', 'zh_CN'):
                configure(language)
                self.assertTrue(tr(key, **{field: '42' for field in en_fields}))

    def test_fallback_is_english_and_unknown_keys_remain_identifiable(self):
        configure('zh_CN')
        with patch.dict(i18n.CATALOGS, {'zh_CN': {}}):
            self.assertEqual(tr('common.settings'), 'Settings')
        self.assertEqual(tr('future.key'), 'future.key')
        with self.assertRaises(KeyError):
            msg('mistyped.key')

    def test_existing_statuses_and_errors_translate_without_restarting_models(self):
        model = LocalizedState()
        model.message = msg('update.available', tag='v0.2.0')
        error = UpdateError(msg('update.http', code=503))
        touch = PanelPosition()
        self.assertEqual(model.message, 'New version available: v0.2.0')
        self.assertIn('503', str(error))
        self.assertEqual(touch.message, 'Touchscreen not open')
        configure('zh_CN')
        self.assertEqual(model.message, '发现新版本 v0.2.0')
        self.assertIn('检查更新失败', str(error))
        self.assertEqual(touch.message, '触屏尚未打开')
        configure('en_US')
        self.assertEqual(model.message, 'New version available: v0.2.0')

    def test_language_error_visibility_uses_state_key_independent_of_translation(self):
        state = KeyboardLanguages('en_US', mode='game', runtime='/unused',
            changed=lambda: None, dispatch=lambda cb: cb(), forward_key=lambda code: None)
        self.addCleanup(state.close)
        state.message = msg('ime.save_failed')
        for language in ('zh_CN', 'en_US'):
            configure(language)
            self.assertTrue(visible(state))
        state.message = msg('ime.english')
        self.assertFalse(visible(state))

    def test_draft_save_discard_reset_preserve_input_and_unknown_preferences(self):
        original = {'mode': 'position', 'keyboard_language': 'zh_CN', 'scroll_scale': .001,
                    'marker_frame_rate': '60', 'future': {'keep': True}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(original))
            draft = SettingsDraft(original)
            draft.change('ui_language', 'zh_CN')
            self.assertEqual(i18n.active_language(), 'en_US')
            draft.discard()
            self.assertEqual(draft.values['ui_language'], 'en_US')
            draft.change('ui_language', 'auto')
            write_settings(path, read_settings(draft.values))
            saved = json.loads(path.read_text())
            for key, value in original.items():
                self.assertEqual(saved[key], value)
            self.assertEqual(saved['ui_language'], 'auto')
            draft.section = 'general'
            draft.reset_section()
            self.assertEqual(draft.values['ui_language'], 'en_US')
            self.assertEqual(draft.values['keyboard_language'], 'zh_CN')

    def test_detached_worker_metadata_survives_language_changes_and_old_readers(self):
        token = msg('worker.cache_warning', message=msg('worker.updated_running', tag='v0.2.0'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'update.json'
            worker.write_status('success', token, tag='v0.2.0', path=path)
            data = json.loads(path.read_text())
            self.assertIsInstance(data['message'], str)
            self.assertIn('Updated to v0.2.0', data['message'])
            restored = i18n.decode_message(data['message_i18n'], data['message'])
            configure('zh_CN')
            self.assertIn('已更新至 v0.2.0', str(restored))
            self.assertIn('桌面缓存刷新未完成', str(restored))
            self.assertEqual(i18n.decode_message(None, 'legacy status'), 'legacy status')

    def test_invalid_status_translation_metadata_falls_back_to_plain_status(self):
        for payload in ({'key': 'missing', 'values': {}},
                        {'key': 'update.available', 'values': {}},
                        {'key': 'common.settings', 'values': {'extra': 1}},
                        {'key': 'update.available', 'values': {'tag': []}},
                        {'key': 'update.available', 'values': {'tag': 'x'*241}}):
            self.assertEqual(i18n.decode_message(payload, 'legacy'), 'legacy')

    def test_ui_sources_do_not_reintroduce_chinese_literals_outside_catalogs(self):
        source = Path(__file__).resolve().parents[1] / 'src/armada_dual_screen_input'
        allowed = {'i18n.py': {'简体中文'}, 'panel_app.py': {'中/EN'}}
        for path in source.glob('*.py'):
            if path.name == 'ui_catalogs.py':
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if any('\u3400' <= char <= '\u9fff' for char in node.value):
                        self.assertIn(node.value, allowed.get(path.name, set()), (path.name, node.lineno))

    def test_desktop_entry_has_english_and_chinese_names_and_comments(self):
        path = Path(__file__).resolve().parents[1] / 'packaging/desktop/thor-panel.desktop.in'
        entries = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
        self.assertEqual(entries['Name'], i18n.EN_US['app.name'])
        self.assertEqual(entries['Name[zh_CN]'], i18n.ZH_CN['app.name'])
        self.assertIn('Comment[zh_CN]', entries)
        self.assertIn('Comment', entries)

    def test_message_call_sites_use_known_keys_and_matching_placeholders(self):
        source = Path(__file__).resolve().parents[1]
        paths = list((source / 'src/armada_dual_screen_input').glob('*.py')) + [source / 'tools/update.py', source / 'tools/uninstall.py']
        def literal_keys(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node.value]
            if isinstance(node, ast.IfExp):
                return literal_keys(node.body) + literal_keys(node.orelse)
            return []
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'msg' and node.args):
                    continue
                for key in literal_keys(node.args[0]):
                    self.assertIn(key, i18n.EN_US, (path.name, node.lineno))
                    fields = {name for _, name, _, _ in Formatter().parse(i18n.EN_US[key]) if name is not None}
                    self.assertEqual(fields, {kw.arg for kw in node.keywords}, (path.name, node.lineno))
