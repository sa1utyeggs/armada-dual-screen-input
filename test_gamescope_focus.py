from dataclasses import replace
import unittest

from gamescope_focus import FocusSnapshot, FocusState, UpperFocus


class FocusTests(unittest.TestCase):
    def test_matching_scaled_surface_is_supported(self):
        self.assertTrue(FocusSnapshot(10, 42, 42, 1280, 720).compatible((1920, 1080)))

    def test_steam_overlay_over_game_is_not_supported(self):
        self.assertFalse(FocusSnapshot(10, 769, 42, 1920, 1080).compatible((1920, 1080)))
        self.assertFalse(FocusSnapshot(10, 42, 42, 1920, 1080,
                                       input_in_surface=False).compatible((1920, 1080)))

    def test_letterboxed_or_invalid_geometry_is_rejected(self):
        for width, height in ((800, 600), (0, 0), (10000, 5625)):
            self.assertFalse(FocusSnapshot(10, 42, 42, width, height).compatible((1920, 1080)))

    def test_remote_or_unspecified_x_displays_are_rejected_before_connection(self):
        for display in ('', 'hostname:0', 'localhost:10', '../0', ':0\n'):
            with self.assertRaises(ValueError): UpperFocus(display)

    def test_stale_error_or_changed_focus_cannot_authorize_input(self):
        focus = FocusSnapshot(10, 42, 42, 1280, 720)
        state = FocusState(focus, 1.0)
        self.assertTrue(state.matches(focus, 1.1))
        self.assertFalse(state.matches(focus, 1.21))
        self.assertFalse(state.matches(focus, 0.9))
        self.assertFalse(state.matches(FocusSnapshot(11, 42, 42, 1280, 720), 1.1))
        self.assertFalse(FocusState(focus, 1.0, 'disconnected').matches(focus, 1.1))

    def test_touch_passthrough_change_invalidates_existing_focus_guard(self):
        focus = FocusSnapshot(10, 769, 769, 1920, 1080, touch_mode=4)
        self.assertFalse(FocusState(replace(focus, touch_mode=1), 1).matches(focus, 1.1))


if __name__ == '__main__':
    unittest.main()
