"""Exercise real GTK callback routing with synthetic events and memory output."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    import test_panel_keyboard as fixture
    from engine import TouchGestureProcessor
    from toolkit_touch import ToolkitTouch


@unittest.skipUnless(IS_LINUX, "Real GTK callback integration requires Linux")
class PanelTouchRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture.PanelKeyboardTests.setUp(self)
        self.panel = fixture.panel_app
        self.app.mode = "trackpad"
        self.app.collapsed = False
        self.app.show_debug_hud = False
        self.app.burn_in = SimpleNamespace(record_touch=Mock())
        self.output = []
        self.bridge.emit_mouse_rel = lambda x, y: self.output.append(("move", x, y))
        self.bridge.emit_scroll = lambda x, y: self.output.append(("scroll", x, y))
        self.bridge.tap_button = lambda button: self.output.append(("click", button))
        self.app.gesture = TouchGestureProcessor(self.bridge, Mock())
        self.app.gesture.set_settings(glide=False, scroll_speed=1)
        self.app.touch = ToolkitTouch(
            self.app._handle_touch_down, self.app._handle_touch_move,
            self.app._handle_touch_up, self.app._cancel_contact,
            on_activity=self.app._refresh_contact,
            on_timed_update=self.app._handle_timed_touch_move,
            clock=lambda: self.scheduler.now / 1000,
        )
        patch.object(self.panel.Gtk, "Window",
                     side_effect=AssertionError("No real windows")).start()
        patch.object(self.panel.upstream, "UInputBridge",
                     side_effect=AssertionError("No real input devices")).start()

    def event(self, kind, sequence, x=300, y=250, *, initial=False):
        self.scheduler.now += 20
        event = SimpleNamespace(
            type=getattr(self.panel.Gdk.EventType, "TOUCH_" + kind), x=x, y=y,
            get_event_sequence=lambda: sequence,
            get_time=lambda: self.scheduler.now,
            touch=SimpleNamespace(emulating_pointer=initial),
            # Real GTK events on Thor retained the public touch field while
            # this private event flag was false, including the first finger.
            get_pointer_emulated=lambda: False,
        )
        self.assertTrue(self.app._on_touch(None, event))

    def test_position_new_group_releases_old_touch_without_disarming_or_jumping(self):
        from panel_position import PanelPosition
        self.app.mode = "position"
        p = self.app.position = PanelPosition()
        p.active = p.armed = p.auto_requested = True
        p._focus_current = lambda: True
        events = []
        p.sender = SimpleNamespace(send=events.append)
        p.marker = Mock()
        self.event("BEGIN", "aim", initial=True)
        self.event("BEGIN", "confirm", x=900)
        self.event("UPDATE", "aim", x=424)
        point = p.gesture.point
        self.assertTrue(p.gesture.held)
        # Missing old ENDs in the adapter, but GTK now reports an empty-seat
        # first contact. It releases the old native touch, never a new click.
        self.event("BEGIN", "fresh", x=100, initial=True)
        self.assertTrue(p.armed)
        self.assertEqual(p.gesture.point, point)
        self.assertFalse(p.gesture.held)
        self.assertEqual(len(self.app.touch.active), 1)
        self.assertEqual([e.kind for e in events], ["down", "move", "cancel"])
        self.event("END", "confirm")  # late old lift cannot affect the new aim
        self.event("BEGIN", "fresh-confirm", x=1000)
        self.assertTrue(p.gesture.held)
        self.assertEqual(events[-1].kind, "down")

    def test_new_wayland_group_recovers_pointer_after_a_missing_end(self):
        self.event("BEGIN", "one", initial=True)
        self.event("BEGIN", "ghost", x=500)
        self.event("UPDATE", "one", y=300)
        self.event("UPDATE", "ghost", x=500, y=300)
        self.event("END", "one")
        self.assertEqual(len(self.app.touch.active), 1)
        self.assertEqual(len(self.app.gesture.active_contacts), 1)
        # No END for the other old contact reaches the application. GDK's
        # next initial-touch flag is authoritative: the seat started empty.
        self.output.clear()
        self.event("BEGIN", "new", initial=True)
        self.event("UPDATE", "new", x=360, y=280)
        self.assertTrue(any(e[0] == "move" for e in self.output))
        self.assertFalse(any(e[0] in ("scroll", "click") for e in self.output))
        self.event("END", "new")
        self.assertFalse(self.app.touch.active)
        self.assertFalse(self.app.gesture.active_contacts)
        self.assertFalse(self.app._touch_owner)

    def test_secondary_touch_keeps_stationary_first_finger_for_scrolling(self):
        self.event("BEGIN", "one", initial=True)
        self.scheduler.now += 30000
        self.app._keep_contacts_alive()
        self.event("BEGIN", "two", x=500)
        self.assertEqual(len(self.app.touch.active), 2)
        self.assertEqual(len(self.app.gesture.active_contacts), 2)
        self.event("UPDATE", "two", x=500, y=310)
        self.assertTrue(any(e[0] == "scroll" for e in self.output))
        self.assertFalse(any(e[0] == "move" for e in self.output))

    def leave_one_scroll_contact(self):
        self.event("BEGIN", "one", initial=True)
        self.event("BEGIN", "ghost", x=500)
        self.event("UPDATE", "one", y=300)
        self.event("UPDATE", "ghost", x=500, y=300)
        self.event("END", "one")

    def test_quiet_kernel_style_ghost_recovers_without_initial_flag(self):
        self.leave_one_scroll_contact()
        self.scheduler.now += 4000
        self.app._keep_contacts_alive()
        self.output.clear()
        self.event("BEGIN", "new", initial=False)
        self.assertEqual(len(self.app.touch.active), 1)
        self.assertEqual(len(self.app.gesture.active_contacts), 1)
        self.event("UPDATE", "new", x=360, y=280)
        self.assertTrue(any(e[0] == "move" for e in self.output))
        self.assertFalse(any(e[0] in ("scroll", "click") for e in self.output))

    def test_stationary_anchor_survives_repeated_rolling_finger_lifts(self):
        self.event("BEGIN", "anchor", initial=True)
        self.scheduler.now += 30000
        self.app._keep_contacts_alive()
        for i in range(10):
            self.event("BEGIN", f"rolling-{i}", x=500)
            self.assertEqual(len(self.app.touch.active), 2)
            self.event("UPDATE", f"rolling-{i}", x=500, y=320)
            self.event("END", f"rolling-{i}")
            self.scheduler.now += 100
        self.assertEqual(len(self.app.touch.active), 1)
        self.assertTrue(any(e[0] == "scroll" for e in self.output))
        self.assertFalse(any(e[0] == "move" for e in self.output))

    def test_quiet_real_anchor_recovery_cannot_turn_second_press_into_a_click(self):
        self.leave_one_scroll_contact()
        self.scheduler.now += 3100
        self.output.clear()
        self.event("BEGIN", "possibly-second", initial=False)
        self.event("END", "possibly-second")
        self.event("END", "ghost")
        self.assertFalse(self.output)

    def test_held_modifier_or_recent_lift_blocks_heuristic_recovery(self):
        self.leave_one_scroll_contact()
        self.assertFalse(self.app._stalled_trackpad_begin("new", 300, 250))
        self.scheduler.now += 4000
        self.bridge.held_keys.add(29)
        self.assertFalse(self.app._stalled_trackpad_begin("new", 300, 250))
        self.bridge.held_keys.clear()
        self.assertTrue(self.app._stalled_trackpad_begin("new", 300, 250))

    def test_recovery_never_starts_from_keyboard_or_header_or_old_sequence(self):
        self.leave_one_scroll_contact()
        self.scheduler.now += 4000
        self.app.mode = "split"
        for sequence, x, y in (("new", 300, 700), ("new", 300, 30),
                                ("ghost", 300, 250), (None, 300, 250)):
            self.assertFalse(self.app._stalled_trackpad_begin(sequence, x, y))


if __name__ == "__main__":
    unittest.main()
