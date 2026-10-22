"""Language discovery fixtures; never read the real Steam registry or launch it."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from armada_dual_screen_input import i18n, supervisor
from armada_dual_screen_input import steam_ui_language as steam


def registry(steam_body='"language" "schinese"', *, valve_extra='', hive='HKCU'):
    return ('"Registry" { "' + hive + '" { "Software" { "Valve" { '
            '"Steam" { ' + steam_body + ' } ' + valve_extra + ' } } } }')


class SteamLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = self.home / '.steam/registry.vdf'
        self.path.parent.mkdir()

    def write(self, text):
        self.path.write_text(text)

    def test_supported_steam_names_and_key_case(self):
        for name, expected in (('schinese', 'zh_CN'), ('tchinese', 'zh_CN'),
                               ('english', 'en_US'), (' SCHINESE ', 'zh_CN')):
            self.write(registry('"Language" "' + name + '"'))
            self.assertEqual(steam.read_steam_language(self.home), expected)
        self.assertEqual(steam.registry_language(registry().upper()), 'zh_CN')

    def test_unsupported_language_is_not_guessed_from_other_settings(self):
        self.write(registry('"language" "german"',
            valve_extra='"Steamsteamglobal" { "language" "schinese" }'))
        self.assertIsNone(steam.read_steam_language(self.home))

    def test_only_exact_client_branches_are_used(self):
        self.assertIsNone(steam.registry_language(registry(
            '"Apps" { "42" { "language" "schinese" } }')))
        self.assertIsNone(steam.registry_language('"language" "schinese"'))
        self.assertEqual(steam.registry_language(registry('',
            valve_extra='"Steamsteamglobal" { "language" "schinese" }')), 'zh_CN')
        self.assertEqual(steam.registry_language(registry(hive='HKLM')), 'zh_CN')

    def test_user_preference_wins_over_global_and_machine_branches(self):
        text = registry('"language" "english"',
            valve_extra='"Steamsteamglobal" { "language" "schinese" }')
        text = text[:-1] + ' "HKLM" { "Software" { "Valve" { "Steam" {' \
               ' "language" "schinese" } } } } }'
        self.assertEqual(steam.registry_language(text), 'en_US')

    def test_comments_escaped_strings_and_quoted_braces_are_values(self):
        text = registry('''// ignore "language" "english"
            "path" "C:\\some\\directory" "brace" "{" "other" "}"
            "quoted" "a\\\"b" "language" "schinese" // comment
        ''')
        self.assertEqual(steam.registry_language(text), 'zh_CN')

    def test_malformed_or_ambiguous_registry_supplies_no_hint(self):
        for text in (registry()[:-1], registry() + '}', '"Registry" { "HKCU"',
                     registry('"language" "schinese" "Language" "english"'),
                     registry('"language"'), registry('"language" "unterminated'),
                     '"x" {' * 34 + '}' * 34,
                     ' ' * (steam.MAX_BYTES + 1)):
            with self.subTest(text=text[:80]):
                self.assertIsNone(steam.registry_language(text))

    def test_bom_non_utf8_oversize_and_missing_file(self):
        self.assertIsNone(steam.read_steam_language(self.home))
        self.path.write_bytes(b'\xef\xbb\xbf' + registry().encode())
        self.assertEqual(steam.read_steam_language(self.home), 'zh_CN')
        for data in (b'\xff\xfe', b'x' * (steam.MAX_BYTES + 1)):
            self.path.write_bytes(data)
            self.assertIsNone(steam.read_steam_language(self.home))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO fixture requires POSIX')
    def test_nonregular_registry_never_blocks_waiting_for_a_writer(self):
        os.mkfifo(self.path)
        self.assertIsNone(steam.read_steam_language(self.home))

    def test_io_failure_is_an_english_fallback(self):
        with patch.object(steam.os, 'open', side_effect=PermissionError):
            self.assertIsNone(steam.read_steam_language(self.home))

    def test_game_hint_preserves_locale_and_other_environment_values(self):
        self.write(registry())
        original = {'LANG': 'C.UTF-8', 'HOME': str(self.home), 'OTHER': 'kept'}
        result = steam.add_steam_language_hint(original, 'game')
        self.assertNotIn(i18n.STEAM_LANGUAGE_HINT, original)
        self.assertEqual(result, {**original, i18n.STEAM_LANGUAGE_HINT: 'zh_CN'})
        self.assertEqual(i18n.resolve_language('auto', result), 'zh_CN')
        self.assertEqual(i18n.resolve_language('en_US', result), 'en_US')
        self.assertEqual(i18n.resolve_language(None, result), 'en_US')

    def test_explicit_locale_and_desktop_mode_do_not_read_registry(self):
        for env, mode in (({'LANG': 'C.UTF-8'}, 'desktop'),
                          ({'LANG': 'zh_CN.UTF-8'}, 'game'),
                          ({'LANG': 'C.UTF-8', 'LC_ALL': 'en_US.UTF-8'}, 'game'),
                          ({'LANG': 'fr_FR.UTF-8'}, 'game')):
            original = {**env, 'HOME': str(self.home), i18n.STEAM_LANGUAGE_HINT: 'zh_CN'}
            with patch.object(steam, 'read_steam_language') as read:
                result = steam.add_steam_language_hint(original, mode)
                read.assert_not_called()
            self.assertNotIn(i18n.STEAM_LANGUAGE_HINT, result)

    def test_unavailable_steam_drops_a_stale_inherited_hint(self):
        result = steam.add_steam_language_hint({'LANG': 'C.UTF-8', 'HOME': str(self.home),
            i18n.STEAM_LANGUAGE_HINT: 'zh_CN'}, 'game')
        self.assertNotIn(i18n.STEAM_LANGUAGE_HINT, result)
        self.assertEqual(i18n.resolve_language('auto', result), 'en_US')

    def test_supervisor_provides_hint_to_its_child_only(self):
        self.write(registry())
        target = SimpleNamespace(mode='game', environment={
            'LANG': 'C.UTF-8', 'HOME': str(self.home)})
        with patch.object(supervisor, 'portable_environment', side_effect=lambda env: env):
            env = supervisor.child_environment(target)
        self.assertEqual(env[i18n.STEAM_LANGUAGE_HINT], 'zh_CN')
        self.assertNotIn(i18n.STEAM_LANGUAGE_HINT, target.environment)
        self.assertEqual(env['LANG'], 'C.UTF-8')


if __name__ == '__main__':
    unittest.main()
