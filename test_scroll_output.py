"""Wheel output checks; no real input device is opened or written."""
import sys
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

VENDOR = Path(__file__).parent / "vendor/ratatoskr"
sys.path[:0] = [str(VENDOR / "bin"), str(VENDOR)]
import engine
from scroll_output import ScaledScroll, read_scroll_scale


class ScrollOutputTests(unittest.TestCase):
    def test_small_steps_accumulate_on_both_axes(self):
        events = []
        scroll = ScaledScroll(lambda x, y: events.append((x, y)), 0.25)
        for _ in range(3):
            scroll.scroll(1, -1)
        self.assertEqual(events, [])
        scroll.scroll(1, -1)
        self.assertEqual(events, [(1, -1)])

    def test_direction_change_cancels_fractional_remainder(self):
        events = []
        scroll = ScaledScroll(lambda x, y: events.append((x, y)), 0.25)
        scroll.scroll(3, -3)
        scroll.scroll(-3, 3)
        self.assertEqual(events, [])
        scroll.scroll(-4, 4)
        self.assertEqual(events, [(-1, 1)])

    def test_segmented_and_coalesced_input_have_equal_totals(self):
        def total(chunks):
            events = []
            scroll = ScaledScroll(lambda x, y: events.append((x, y)), 0.25)
            for x, y in chunks:
                scroll.scroll(x, y)
            return tuple(sum(e[axis] for e in events) for axis in (0, 1))
        self.assertEqual(total([(1, -2)] * 480), (120, -240))
        self.assertEqual(total([(480, -960)]), (120, -240))

    def test_invalid_config_keeps_unscaled_behavior(self):
        for value in (None, {}, "invalid", 0, -1, 2, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertEqual(read_scroll_scale(value), 1.0)
        self.assertEqual(read_scroll_scale(0.25), 0.25)

    def test_high_res_and_legacy_wheel_share_the_same_reduction(self):
        # Construct the bridge without __init__, so /dev/uinput is untouched.
        bridge = engine.UInputBridge.__new__(engine.UInputBridge)
        bridge.lock = threading.RLock()
        bridge.mouse_fd = 123
        bridge.wake_pointer = False
        bridge.scroll_accum_x = bridge.scroll_accum_y = 0.0
        bridge.count_scrolls = 0
        writes = []
        scroll = ScaledScroll(bridge.emit_scroll, 0.25)
        with patch.object(engine.os, "write", side_effect=lambda fd, data: writes.append(data)):
            for _ in range(480):
                scroll.scroll(1, -1)
        totals = {}
        for data in writes:
            for _, _, event_type, code, value in engine.EVENT_STRUCT.iter_unpack(data):
                if event_type == engine.EV_REL:
                    totals[code] = totals.get(code, 0) + value
        self.assertEqual(totals, {
            engine.REL_WHEEL_HI_RES: -120,
            engine.REL_WHEEL: -1,
            engine.REL_HWHEEL_HI_RES: 120,
            engine.REL_HWHEEL: 1,
        })


if __name__ == "__main__":
    unittest.main()
