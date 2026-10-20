"""Real system-library checks. No display, input device or event is created."""
import ctypes.util
from pathlib import Path
import sys
import unittest

from armada_dual_screen_input.keyboard_xkb import XkbLayout
from armada_dual_screen_input.pinyin_engine import PinyinEngine


@unittest.skipUnless(sys.platform == "linux" and ctypes.util.find_library("xkbcommon"),
                     "System XKB requires Linux libxkbcommon")
class SystemXkbTests(unittest.TestCase):
    def test_shift_caps_and_symbol_use_system_keymap(self):
        xkb = XkbLayout()
        self.addCleanup(xkb.close)
        self.assertEqual(xkb.character(30), "a")
        self.assertEqual(xkb.character(30, shift=True), "A")
        self.assertEqual(xkb.character(30, caps=True), "A")
        self.assertEqual(xkb.character(30, shift=True, caps=True), "a")
        self.assertEqual(xkb.character(3, shift=True), "@")

    def test_other_system_layouts_produce_actual_characters(self):
        for layout, code, expected in (("de", 21, "z"), ("fr", 16, "a"), ("ru", 30, "ф")):
            with self.subTest(layout=layout):
                xkb = XkbLayout(layout)
                try:
                    self.assertEqual(xkb.character(code), expected)
                finally:
                    xkb.close()


@unittest.skipUnless(sys.platform == "linux" and ctypes.util.find_library("pinyin")
                     and Path("/usr/lib64/libpinyin/data/table.conf").exists(),
                     "System libpinyin dictionary not available on this test host")
class SystemPinyinTests(unittest.TestCase):
    def setUp(self):
        self.engine = PinyinEngine()
        self.addCleanup(self.engine.close)

    def test_system_dictionary_generates_common_chinese_words(self):
        for text, expected in (("nihao", "你好"), ("zhongwen", "中文"), ("shijie", "世界")):
            with self.subTest(text=text):
                self.assertEqual(self.engine.lookup(text)[0], expected)
                self.assertEqual(self.engine.choose(0), (expected, ""))

    def test_partial_selection_and_incomplete_syllable(self):
        candidates = self.engine.lookup("nihaoma")
        self.assertEqual(self.engine.choose(candidates.index("你好")), ("你好", "ma"))
        self.assertTrue(self.engine.lookup("n"))

    def test_invalid_or_oversized_input_is_rejected_before_native_api(self):
        for text in ("NIHAO", "你好", "n" * 65, "bad\0input"):
            with self.assertRaises(ValueError):
                self.engine.lookup(text)


if __name__ == "__main__":
    unittest.main()
