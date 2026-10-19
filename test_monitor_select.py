"""Offline monitor-selection fixtures; no GI/display/device dependencies."""
import unittest

from monitor_select import choose_bottom_monitor


class MonitorSelectionTests(unittest.TestCase):
    def test_desktop_uses_exact_connector_independent_of_monitor_order(self):
        fixtures = [
            (["DSI-2", "DSI-1"], 1),
            (["DSI-1", "DSI-2"], 0),
            (["HDMI-A-1", "DSI-2", "DSI-1"], 2),
            ([None, "DSI-1"], 1),
            (["DSI-1"], 0),
        ]
        for connectors, expected in fixtures:
            with self.subTest(connectors=connectors):
                self.assertEqual(choose_bottom_monitor(connectors, "desktop"), expected)

    def test_desktop_does_not_fall_back_to_top_or_an_unnamed_single_monitor(self):
        for connectors in (["DSI-2"], [None], ["Unknown"], [], ["DSI-2", None]):
            with self.subTest(connectors=connectors):
                self.assertIsNone(choose_bottom_monitor(connectors, "desktop"))

    def test_desktop_rejects_duplicate_or_inexact_names(self):
        for connectors in (["DSI-1", "DSI-1"], ["dsi-1"], [" DSI-1"], ["DSI-10"]):
            with self.subTest(connectors=connectors):
                self.assertIsNone(choose_bottom_monitor(connectors, "desktop"))

    def test_verified_game_bottom_socket_accepts_its_only_output(self):
        for connectors in ([None], ["WL-1"], ["DSI-1"], ["DSI-2"]):
            with self.subTest(connectors=connectors):
                self.assertEqual(choose_bottom_monitor(connectors, "gamemode"), 0)

    def test_game_multiple_outputs_need_the_exact_unique_connector(self):
        self.assertEqual(choose_bottom_monitor(["WL-1", "DSI-1"], "gamemode"), 1)
        for connectors in (["WL-1", "WL-2"], [None, None], ["DSI-1", "DSI-1"], []):
            with self.subTest(connectors=connectors):
                self.assertIsNone(choose_bottom_monitor(connectors, "gamemode"))

    def test_unknown_mode_or_bad_input_fails_closed(self):
        for mode in (None, "", "gaming", "Desktop", "unknown"):
            self.assertIsNone(choose_bottom_monitor(["DSI-1"], mode))
        for connectors in (None, "DSI-1", 1):
            self.assertIsNone(choose_bottom_monitor(connectors, "desktop"))


if __name__ == "__main__":
    unittest.main()
