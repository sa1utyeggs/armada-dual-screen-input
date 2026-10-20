"""Exercise the real panel's touch-to-keyboard routing without a UI or uinput.

Run on Linux with the panel's GTK dependencies. macOS deliberately skips the
integration checks; the pure KeyboardPulses tests remain cross-platform.
"""
import os
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keyboard_pulses import KeyboardPulses
from test_keyboard_pulses import FakeScheduler


IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    # Import the real adapter, but keep its import-time state directory and
    # socket path in a throwaway location, without touching the user's setup.
    with tempfile.TemporaryDirectory() as import_state, patch.dict(os.environ, {
        "XDG_RUNTIME_DIR": import_state,
        "XDG_STATE_HOME": import_state,
    }):
        import panel_app
        from keyboard_layout import KeyboardLayout
        from modifiers import CODES, ModifierState


class FakeBridge:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.events = []
        self.held_keys = set()

    def key(self, code, down):
        self.events.append((self.scheduler.now, code, down))
        if down:
            self.held_keys.add(code)
        else:
            self.held_keys.discard(code)

    def release_all(self):
        for code in sorted(self.held_keys):
            self.key(code, False)


@unittest.skipUnless(IS_LINUX, "Real PanelApp integration requires Linux GTK")
class PanelKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = FakeScheduler()
        self.bridge = FakeBridge(self.scheduler)
        # Never run PanelApp.__init__: it creates GTK and /dev/uinput objects.
        self.app = panel_app.PanelApp.__new__(panel_app.PanelApp)
        self.app.bridge = self.bridge
        self.app.key_pulses = KeyboardPulses(
            send_key=self.bridge.key,
            schedule=self.scheduler.schedule,
            cancel=self.scheduler.cancel,
        )
        self.bridge.tap_key = self.app.key_pulses.tap
        self.app.mode = "keyboard"
        self.app.ui_hidden = False
        self.app._cleaned = False
        self.app._physical_sequences = set()
        self.app.mirror = self.app.position = None
        self.app._touch_owner = {}
        self.app._slider_drag = None
        self.app.held_ui_button = None
        self.app.held_ui_button_tid = None
        self.app.held_key = None
        self.app.held_key_tid = None
        self.app.active_key_press = None
        self.app.active_key_tid = None
        self.app.last_key_label = ""
        self.app.last_event_time = 0
        self.app._repeat_stop = threading.Event()
        self.app._repeat_thread = None
        self.app.input_lock = threading.RLock()
        self.app.mods = ModifierState()
        self.app.keyboard_cfg = dict(panel_app.upstream.keyboard_settings.DEFAULTS)
        self.app.kb_layout = KeyboardLayout(
            0, panel_app.upstream.HEADER_HEIGHT,
            panel_app.SCREEN_WIDTH,
            panel_app.SCREEN_HEIGHT - panel_app.upstream.HEADER_HEIGHT,
        )
        self.app.drawing_area = SimpleNamespace(queue_draw=lambda: None)
        self.app.gesture = SimpleNamespace(
            glide_stop=threading.Event(), reset_all=lambda: None,
        )
        self.addCleanup(self.app.key_pulses.close)
        # Parent handlers schedule drawing with GLib, but no real main loop
        # should run during these input-order checks.
        self.addCleanup(patch.stopall)
        patch.object(panel_app.upstream.GLib, "idle_add", return_value=1).start()
        patch.object(panel_app.upstream.time, "monotonic", side_effect=(
            lambda: 1000 + self.scheduler.now / 1000
        )).start()

    def down(self, label, tid):
        key = next(key for row in self.app.kb_layout.rows for key in row if key.label == label)
        self.app._handle_touch_down(
            tid, key.x + key.w / 2, key.y + key.h / 2,
            self.scheduler.now / 1000,
        )
        return key.code

    def up(self, tid):
        self.app._handle_touch_up(tid, self.scheduler.now / 1000)

    def test_ordinary_touch_input_never_sleeps_and_releases_normally(self):
        with patch("time.sleep", side_effect=AssertionError("GTK callback blocked")):
            code = self.down("a", 1)
        self.assertEqual(self.bridge.events, [(0, code, True)])
        self.scheduler.advance(20)
        self.assertEqual(self.bridge.events[-1], (20, code, False))
        self.up(1)
        self.assertFalse(self.bridge.held_keys)
        self.assertIsNone(self.app.held_key)

    def test_fast_same_key_old_release_cannot_end_new_press(self):
        code = self.down("a", 1)
        old_release = self.scheduler.callbacks[1]
        self.scheduler.advance(5)
        self.up(1)
        self.down("a", 2)
        self.assertEqual(self.bridge.events, [
            (0, code, True), (5, code, False), (5, code, True),
        ])
        old_release()
        self.assertIn(code, self.bridge.held_keys)
        self.assertEqual(len(self.bridge.events), 3)
        self.scheduler.advance(20)
        self.assertEqual(self.bridge.events[-1], (25, code, False))
        self.up(2)

    def test_latched_shift_is_released_after_pending_character(self):
        self.down("Shift", 1)
        self.up(1)
        self.assertTrue(self.app.mods.latched("shift"))
        code = self.down("a", 2)
        self.scheduler.advance(5)
        self.up(2)
        self.assertEqual(self.bridge.events, [
            (0, CODES["shift"], True), (0, code, True),
            (5, code, False), (5, CODES["shift"], False),
        ])
        self.assertFalse(self.app.mods.active("shift"))
        self.assertFalse(self.bridge.held_keys)

    def test_held_shift_applies_to_multiple_characters(self):
        self.down("Shift", 1)
        a = self.down("a", 2)
        self.scheduler.advance(5)
        self.up(2)
        self.assertTrue(self.app.mods.active("shift"))
        self.scheduler.advance(5)
        s = self.down("s", 3)
        self.assertEqual(self.app.last_key_label, "S")
        self.scheduler.advance(5)
        self.up(3)
        self.assertTrue(self.app.mods.active("shift"))
        self.up(1)
        self.assertEqual(self.bridge.events, [
            (0, CODES["shift"], True), (0, a, True), (5, a, False),
            (10, s, True), (15, s, False), (15, CODES["shift"], False),
        ])
        self.assertFalse(self.bridge.held_keys)

    def test_modifier_release_flushes_pulse_without_stopping_character_repeat(self):
        self.down("Shift", 1)
        code = self.down("a", 2)
        self.scheduler.advance(5)
        self.up(1)
        self.assertEqual(self.bridge.events[-2:], [
            (5, code, False), (5, CODES["shift"], False),
        ])
        self.assertEqual(self.app.held_key_tid, 2)
        self.scheduler.advance(345)
        self.assertEqual(self.bridge.events[-1], (350, code, True))
        self.scheduler.advance(60)
        self.assertEqual(self.bridge.events[-2:], [(370, code, False), (410, code, True)])
        self.up(2)
        self.assertFalse(self.bridge.held_keys)

    def test_reset_releases_character_then_modifier_and_cancels_future_input(self):
        self.down("Shift", 1)
        code = self.down("a", 2)
        callbacks = list(self.scheduler.callbacks.values())
        self.scheduler.advance(5)
        self.app._reset_input()
        self.assertEqual(self.bridge.events[-2:], [
            (5, code, False), (5, CODES["shift"], False),
        ])
        self.assertFalse(self.bridge.held_keys)
        self.assertFalse(self.app.mods.active("shift"))
        self.assertFalse(self.app._touch_owner)
        self.assertIsNone(self.app.held_key)
        self.assertIsNone(self.app.active_key_press)
        before = list(self.bridge.events)
        for callback in callbacks:
            callback()
        self.scheduler.advance(1000)
        self.assertEqual(self.bridge.events, before)
        self.assertFalse(self.scheduler.pending)

    def test_panel_uses_configured_350ms_delay_and_60ms_repeat_interval(self):
        code = self.down("Bksp", 1)
        self.scheduler.advance(349)
        self.assertEqual(self.bridge.events, [(0, code, True), (20, code, False)])
        self.scheduler.advance(1)
        self.assertEqual(self.bridge.events[-1], (350, code, True))
        self.scheduler.advance(60)
        self.assertEqual(self.bridge.events[-2:], [(370, code, False), (410, code, True)])
        self.scheduler.advance(60)
        self.assertEqual(self.bridge.events[-2:], [(430, code, False), (470, code, True)])
        self.up(1)


if __name__ == "__main__":
    unittest.main()
