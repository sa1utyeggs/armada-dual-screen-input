"""Ordering, focus isolation and candidate semantics without real input."""
import unittest

from armada_dual_screen_input.keyboard_composition import Composition


class FakeEngine:
    def lookup(self, text):
        self.text = text
        return {"ni": ["你", "尼"], "nihao": ["你好", "你"],
                "hao": ["好"]}.get(text, [])

    def choose(self, index):
        if self.text == "nihao":
            return [("你好", ""), ("你", "hao")][index]
        return self.lookup(self.text)[index], ""


class FakeTransport:
    def __init__(self):
        self.target = "own-window-1"
        self.sent = []

    def focus(self):
        return self.target

    def matches(self, target):
        return target == self.target

    def commit(self, text, target):
        if not self.matches(target):
            raise RuntimeError("Focus changed")
        self.sent.append(("text", text, target))

    def action(self, action, target):
        if not self.matches(target):
            raise RuntimeError("Focus changed")
        self.sent.append(("action", action, target))


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.ime = Composition(FakeEngine(), self.transport)

    def type(self, text):
        for char in text:
            self.ime.handle({"kind": "key", "code": 30, "text": char})

    def key(self, code, text=""):
        return self.ime.handle({"kind": "key", "code": code, "text": text})

    def test_letters_do_not_leak_to_upper_before_selection(self):
        self.type("nihao")
        self.assertEqual(self.ime.preedit, "nihao")
        self.assertEqual(self.ime.candidates, ["你好", "你"])
        self.assertFalse(self.transport.sent)
        self.key(57, " ")
        self.assertEqual(self.transport.sent, [("text", "你好", "own-window-1")])
        self.assertEqual(self.ime.preedit, "")

    def test_partial_candidate_preserves_the_unconsumed_pinyin(self):
        self.type("nihao")
        self.ime.handle({"kind": "choose", "index": 1, "revision": self.ime.revision})
        self.assertEqual(self.ime.preedit, "hao")
        self.key(57, " ")
        self.assertEqual([s[1] for s in self.transport.sent], ["你", "好"])

    def test_backspace_and_escape_cancel_before_touching_target(self):
        self.type("nihao")
        self.key(14)
        self.assertEqual(self.ime.preedit, "niha")
        self.key(1)
        self.assertFalse(self.ime.preedit)
        self.assertFalse(self.transport.sent)
        self.key(14)
        self.assertEqual(self.transport.sent[0][0:2], ("action", 2))

    def test_enter_commits_literal_pinyin_and_a_second_enter_submits(self):
        self.type("nihao")
        self.key(28)
        self.key(28)
        self.assertEqual([s[:2] for s in self.transport.sent], [("text", "nihao"), ("action", 1)])

    def test_stale_candidate_does_not_select_a_different_word(self):
        self.type("ni")
        revision = self.ime.revision
        self.type("hao")
        result = self.ime.handle({"kind": "choose", "index": 0, "revision": revision})
        self.assertEqual(result["status"], "stale_candidate")
        self.assertEqual(self.ime.preedit, "nihao")
        self.assertFalse(self.transport.sent)

    def test_focus_change_cancels_instead_of_committing_into_another_window(self):
        self.type("nihao")
        self.transport.target = "own-window-2"
        result = self.key(57, " ")
        self.assertEqual(result["status"], "focus_changed")
        self.assertFalse(self.transport.sent)
        self.assertFalse(self.ime.preedit)

    def test_sequential_keys_after_commit_start_a_fresh_composition(self):
        self.type("ni")
        self.key(57, " ")
        self.type("hao")
        self.assertEqual(self.ime.preedit, "hao")
        self.assertEqual(self.transport.sent[0][1], "你")

    def test_digits_select_and_punctuation_finishes_the_best_sentence(self):
        self.type("nihao")
        self.key(3, "2")
        self.assertEqual(self.ime.preedit, "hao")
        self.key(51, ",")
        self.assertEqual([s[1] for s in self.transport.sent], ["你", "好", "，"])

    def test_punctuation_does_not_recapture_a_different_target_mid_commit(self):
        self.type("nihao")
        original = self.transport.commit

        def commit_then_change(text, target):
            original(text, target)
            self.transport.target = "own-window-2"

        self.transport.commit = commit_then_change
        with self.assertRaises(RuntimeError):
            self.key(51, ",")
        self.assertEqual([s[1] for s in self.transport.sent], ["你好"])

    def test_composition_is_bounded_and_reset_clears_candidate_target(self):
        self.type("n" * 100)
        self.assertEqual(len(self.ime.preedit), 64)
        self.ime.handle({"kind": "reset"})
        self.assertEqual(self.ime.candidates, [])
        self.assertIsNone(self.ime.target)


if __name__ == "__main__":
    unittest.main()
