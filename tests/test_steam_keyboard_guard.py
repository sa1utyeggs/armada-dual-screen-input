"""Offline guard intent/worker tests; no GTK, websocket, Steam or uinput calls."""
from __future__ import annotations

import itertools
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input import steam_keyboard_guard as guard_module
from armada_dual_screen_input.steam_keyboard_guard import SteamKeyboardGuard, keyboard_guard_wanted


IS_LINUX = sys.platform == "linux"
if IS_LINUX:
    # Match the existing panel integration tests: imports may establish state
    # paths, so contain those in a temporary directory. Never construct a UI.
    with tempfile.TemporaryDirectory() as import_state, patch.dict(os.environ, {
        "XDG_RUNTIME_DIR": import_state,
        "XDG_STATE_HOME": import_state,
    }):
        from armada_dual_screen_input import panel_app


class EligibilityTests(unittest.TestCase):
    def test_exact_game_mode_keyboard_or_split_mapped_and_expanded_only(self):
        for session, mode, collapsed, mapped in itertools.product(
            ("game", "desktop", "", "unknown"),
            ("keyboard", "split", "trackpad", "settings", ""),
            (False, True), (False, True),
        ):
            with self.subTest(session=session, mode=mode, collapsed=collapsed, mapped=mapped):
                expected = (session == "game" and mode in {"keyboard", "split"}
                            and not collapsed and mapped)
                self.assertEqual(keyboard_guard_wanted(session, mode, collapsed, mapped), expected)

    def test_both_usable_keyboard_modes_are_eligible(self):
        self.assertTrue(keyboard_guard_wanted("game", "keyboard", False, True))
        self.assertTrue(keyboard_guard_wanted("game", "split", False, True))

    def test_collapsed_or_unmapped_keyboard_never_requests_suppression(self):
        for mode in ("keyboard", "split"):
            self.assertFalse(keyboard_guard_wanted("game", mode, True, True))
            self.assertFalse(keyboard_guard_wanted("game", mode, False, False))


class _Stop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True


class _Wake:
    def __init__(self, clock, stop, rounds, heartbeat=None):
        self.clock, self.stop, self.rounds = clock, stop, rounds
        self.heartbeat = heartbeat
        self.waits = 0
        self.sets = 0

    def clear(self):
        pass

    def set(self):
        self.sets += 1

    def wait(self, duration):
        self.clock[0] += duration
        self.waits += 1
        if self.heartbeat is not None:
            self.heartbeat()
        if self.waits >= self.rounds:
            self.stop.set()


class WorkerIntentTests(unittest.TestCase):
    def prepare(self, *, heartbeat=False, failure=False):
        instance = SteamKeyboardGuard()
        clock = [100.0]
        instance._stop = _Stop()
        instance._wake = _Wake(clock, instance._stop, 6)
        if heartbeat:
            instance._wake.heartbeat = lambda: instance.update(True)
        actions = []

        def command(action):
            actions.append((action, clock[0]))
            if failure and action == "renew":
                raise OSError("fake disconnect")
            return {"active": action == "renew"}

        instance._command = Mock(side_effect=command)
        instance._close_socket = Mock()
        instance._report = Mock()
        return instance, clock, actions

    def test_a_stalled_ui_heartbeat_stops_renewing_and_releases(self):
        instance, clock, actions = self.prepare()
        with patch.object(guard_module.time, "monotonic", side_effect=lambda: clock[0]):
            instance.update(True)
            instance._run()  # Synchronous fake events, not an actual worker thread.
        self.assertEqual([action for action, _ in actions], ["renew"] * 4 + ["release"])
        self.assertEqual(actions[-1][1], 103.0)
        self.assertFalse(instance._was_active)

    def test_live_ui_heartbeats_renew_beyond_stale_threshold_then_release_at_exit(self):
        instance, clock, actions = self.prepare(heartbeat=True)
        with patch.object(guard_module.time, "monotonic", side_effect=lambda: clock[0]):
            instance.update(True)
            instance._run()
        self.assertEqual([action for action, _ in actions], ["renew"] * 6 + ["release"])
        self.assertGreater(actions[-2][1], 102.5)

    def test_lost_renew_reply_retains_possible_ownership_for_release(self):
        instance, clock, actions = self.prepare(failure=True)
        with patch.object(guard_module.time, "monotonic", side_effect=lambda: clock[0]):
            instance.update(True)
            instance._run()
        self.assertIn("release", [action for action, _ in actions])
        self.assertFalse(instance._was_active)
        self.assertGreater(instance._close_socket.call_count, 0)

    def test_release_failure_still_closes_transport_and_forgets_ownership(self):
        instance = SteamKeyboardGuard()
        instance._was_active = True
        instance._command = Mock(side_effect=OSError("fake disconnect"))
        instance._close_socket = Mock()
        instance._report = Mock()
        instance._release()
        instance._command.assert_called_once_with("release")
        instance._close_socket.assert_called_once()
        self.assertFalse(instance._was_active)

    def test_update_refreshes_pulse_without_network_and_wakes_on_changed_intent(self):
        instance = SteamKeyboardGuard()
        instance._wake = Mock()
        instance._command = Mock(side_effect=AssertionError("GTK must not contact Steam"))
        with patch.object(guard_module.time, "monotonic", side_effect=[10.0, 11.0, 12.0]):
            instance.update(True)
            instance.update(True)
            instance.update(False)
        self.assertEqual(instance._pulse, 12.0)
        self.assertFalse(instance._enabled)
        self.assertEqual(instance._wake.set.call_count, 2)
        instance._command.assert_not_called()

    def test_stop_disables_intent_and_joins_for_a_bounded_time(self):
        instance = SteamKeyboardGuard()
        instance._thread = Mock()
        instance._wake = Mock()
        instance._enabled = True
        instance.stop()
        self.assertFalse(instance._enabled)
        self.assertTrue(instance._stop.is_set())
        instance._thread.join.assert_called_once_with(timeout=0.25)


@unittest.skipUnless(IS_LINUX, "Real PanelApp integration requires Linux GTK")
class PanelGuardIntentTests(unittest.TestCase):
    def make_app(self, session="game", mode="split", collapsed=False, mapped=True):
        # __init__ creates GTK/uinput resources and must never run in this test.
        app = panel_app.PanelApp.__new__(panel_app.PanelApp)
        app.session_mode = session
        app.mode = mode
        app.collapsed = collapsed
        app.keyboard_guard = Mock()
        app.window = SimpleNamespace(get_mapped=Mock(return_value=mapped))
        return app

    def test_real_sync_enables_for_both_visible_keyboard_modes(self):
        for mode in ("keyboard", "split"):
            with self.subTest(mode=mode):
                app = self.make_app(mode=mode)
                app._sync_keyboard_guard()
                app.keyboard_guard.update.assert_called_once_with(True)

    def test_real_sync_releases_for_other_tabs_collapsed_unmapped_or_desktop(self):
        for values in (
            {"mode": "trackpad"}, {"mode": "settings"},
            {"collapsed": True}, {"mapped": False}, {"session": "desktop"},
        ):
            with self.subTest(values=values):
                app = self.make_app(**values)
                app._sync_keyboard_guard()
                app.keyboard_guard.update.assert_called_once_with(False)

    def test_real_sync_without_guard_does_not_query_window(self):
        app = self.make_app()
        app.keyboard_guard = None
        app._sync_keyboard_guard()
        app.window.get_mapped.assert_not_called()


if __name__ == "__main__":
    unittest.main()
