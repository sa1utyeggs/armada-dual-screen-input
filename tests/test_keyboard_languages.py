import unittest

from armada_dual_screen_input.keyboard_languages import KeyboardLanguages, read_language
from armada_dual_screen_input.keyboard_language_view import hit, visible, HEIGHT


class FakeWorker:
    def __init__(self, runtime, deliver, dispatch):
        self.deliver, self.closed, self.requests = deliver, False, []

    def submit(self, request):
        self.requests.append(request)
        return not self.closed

    def close(self):
        self.closed = True


class FakeXkb:
    def __init__(self):
        self.closed = False

    def character(self, code, **kwargs):
        return "a"

    def close(self):
        self.closed = True


class KeyboardLanguageTests(unittest.TestCase):
    def setUp(self):
        self.changed, self.forwarded = [], []
        self.state = KeyboardLanguages("en_US", mode="game", runtime="/own/runtime",
                                       changed=lambda: self.changed.append(True),
                                       dispatch=lambda cb: cb(), forward_key=self.forwarded.append,
                                       worker_factory=FakeWorker, xkb_factory=FakeXkb)
        self.addCleanup(self.state.close)

    def ready(self):
        self.state.sync(True)
        self.state.set_language("zh_CN")
        self.state.worker.deliver({"status": "ready", "preedit": "", "candidates": [], "revision": 0})

    def test_english_and_hidden_chinese_never_start_a_native_worker(self):
        self.state.sync(True)
        self.assertIsNone(self.state.worker)
        self.assertFalse(self.state.key(30))
        self.state.sync(False)
        self.state.set_language("zh_CN")
        self.assertIsNone(self.state.worker)

    def test_chinese_initialization_is_async_and_never_falls_back_to_raw_pinyin(self):
        self.state.set_language("zh_CN")
        self.state.sync(True)
        self.assertEqual(self.state.worker.requests, [{"kind": "init"}])
        self.assertTrue(self.state.key(30))
        self.assertEqual(len(self.state.worker.requests), 1)

    def test_language_or_page_changes_terminate_old_worker_and_ignore_late_replies(self):
        self.ready()
        old = self.state.worker
        self.state.sync(False)
        old.deliver({"status": "ready", "preedit": "must-not-return", "candidates": ["旧"]})
        self.assertTrue(old.closed)
        self.assertFalse(self.state.ready)
        self.assertEqual(self.state.preedit, "")

    def test_keys_are_ordered_commands_and_shortcuts_stay_on_raw_route(self):
        self.ready()
        self.assertTrue(self.state.key(30))
        self.assertEqual(self.state.worker.requests[-1], {"kind": "key", "code": 30, "text": "a", "page": 0})
        self.assertFalse(self.state.key(30, shortcut=True))

    def test_candidate_tap_has_a_revision_and_paging_is_bounded(self):
        self.ready()
        self.state.worker.deliver({"status": "ready", "preedit": "ni", "candidates": [str(x) for x in range(8)], "revision": 7})
        self.state.turn_page(10)
        self.assertEqual(self.state.page, 1)
        self.state.choose(6)
        self.assertEqual(self.state.worker.requests[-1], {"kind": "choose", "index": 6, "revision": 7})
        self.state.turn_page(-10)
        self.assertEqual(self.state.page, 0)

    def test_failure_stops_native_backend_and_does_not_retry_from_stats_tick(self):
        self.ready()
        worker = self.state.worker
        worker.deliver({"status": "unavailable"})
        self.assertTrue(worker.closed)
        self.assertIsNone(self.state.worker)
        self.state.sync(True)
        self.assertIsNone(self.state.worker)
        self.assertIn("不可用", self.state.message)

    def test_desktop_does_not_bind_private_gamescope_protocol(self):
        self.state.mode = "desktop"
        self.state.set_language("zh_CN")
        self.state.sync(True)
        self.assertIsNone(self.state.worker)
        self.assertIn("Game Mode", self.state.message)

    def test_invalid_config_never_selects_an_arbitrary_library_or_module(self):
        for value in (None, {}, [], "xx", "/tmp/module", True):
            self.assertEqual(read_language({"keyboard_language": value}), "en_US")

    def test_language_bar_hit_areas_are_separate_from_keys(self):
        top = 500
        self.assertEqual(hit(1170, top + 25, top), ("cancel", None))
        self.assertEqual(hit(200, top + 75, top), ("candidate", 1))
        self.assertEqual(hit(1170, top + 75, top), ("page", 1))
        self.assertEqual(hit(100, top + HEIGHT, top), (None, None))

    def test_idle_language_does_not_take_any_trackpad_area(self):
        self.state.sync(True)
        self.assertFalse(visible(self.state))
        self.ready()
        self.assertFalse(visible(self.state))
        self.state.preedit = "ni"
        self.assertTrue(visible(self.state))
        self.state.reset()
        self.assertFalse(visible(self.state))


if __name__ == "__main__":
    unittest.main()
