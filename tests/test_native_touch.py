import unittest

from armada_dual_screen_input.native_touch import (ABS_MT_ID, ABS_MT_SLOT, BTN_TOUCH, EV_ABS, EV_KEY,
                          TouchSequence, VirtualTouchProbe, screen_to_raw)


class NativeTouchTests(unittest.TestCase):
    def test_inverse_right_rotation(self):
        self.assertEqual(screen_to_raw(.25, .3, 'right'), (19660, 49151))

    def test_rotations_preserve_center_and_reject_invalid_input(self):
        for rotation in ('normal', 'right', 'left', 'inverted'):
            self.assertEqual(screen_to_raw(.5, .5, rotation), (32768, 32768))
        for u, v in ((-1, 0), (0, 2), (float('nan'), 0)):
            with self.assertRaises(ValueError): screen_to_raw(u, v, 'normal')
        with self.assertRaises(ValueError): screen_to_raw(0, 0, 'auto')

    def test_two_contacts_have_distinct_slots_and_tracking_ids(self):
        t = TouchSequence('normal')
        first, second = t.down(1, .2, .3), t.down(2, .6, .7)
        self.assertIn((EV_ABS, ABS_MT_SLOT, 0), first)
        self.assertIn((EV_ABS, ABS_MT_SLOT, 1), second)
        self.assertIn((EV_ABS, ABS_MT_ID, 1), first)
        self.assertIn((EV_ABS, ABS_MT_ID, 2), second)
        self.assertNotIn((EV_KEY, BTN_TOUCH, 1), second)
        with self.assertRaises(ValueError): t.down(3, .5, .5)

    def test_lift_waits_for_last_finger_before_releasing_touch_button(self):
        t = TouchSequence('normal')
        t.down(1, .2, .3); t.down(2, .6, .7)
        self.assertNotIn((EV_KEY, BTN_TOUCH, 0), t.up(1))
        self.assertIn((EV_KEY, BTN_TOUCH, 0), t.up(2))

    def test_ten_slots_stay_independent_and_reuse_only_released_slot(self):
        t = TouchSequence('normal', max_contacts=10)
        for tid in range(10):
            self.assertIn((EV_ABS, ABS_MT_SLOT, tid), t.down(tid, .5, .5))
        with self.assertRaises(ValueError): t.down(10, .5, .5)
        t.up(4)
        self.assertIn((EV_ABS, ABS_MT_SLOT, 4), t.down(20, .3, .4))
        events = t.release_all()
        self.assertEqual(sum(e == (EV_ABS, ABS_MT_ID, -1) for e in events), 10)
        self.assertEqual(sum(e == (EV_KEY, BTN_TOUCH, 0) for e in events), 1)

    def test_release_clears_every_contact_without_mouse_buttons(self):
        t = TouchSequence('right')
        events = t.down(1, .1, .2) + t.down(2, .5, .6) + t.release_all()
        self.assertEqual(t.contacts, {})
        self.assertEqual(sum(e == (EV_ABS, ABS_MT_ID, -1) for e in events), 2)
        self.assertTrue(all(kind != EV_KEY or code == BTN_TOUCH for kind, code, _ in events))
        self.assertEqual(t.release_all(), ())

    def test_bad_coordinates_do_not_change_contacts(self):
        t = TouchSequence('normal')
        t.down(1, .1, .2)
        before = dict(t.contacts)
        with self.assertRaises(ValueError): t.move(1, float('inf'), 0)
        with self.assertRaises(ValueError): t.down(1, .3, .4)
        self.assertEqual(t.contacts, before)

    def test_guard_denies_first_contact_without_writing_input(self):
        probe = object.__new__(VirtualTouchProbe)
        probe.sequence = TouchSequence('normal')
        probe.guard = lambda: False
        probe.uinput = 1
        writes = []
        probe._write = lambda events: writes.extend(events)
        with self.assertRaises(RuntimeError): probe.contact('down', 1, .5, .5)
        self.assertEqual(writes, [])
        self.assertEqual(probe.sequence.contacts, {})

    def test_guard_loss_lifts_existing_contacts_before_refusing_more_motion(self):
        probe = object.__new__(VirtualTouchProbe)
        probe.sequence = TouchSequence('normal')
        probe.sequence.down(1, .5, .5)
        probe.guard = lambda: False
        probe.uinput = 1
        writes = []
        probe._write = lambda events: writes.extend(events)
        with self.assertRaises(RuntimeError): probe.contact('move', 1, .6, .6)
        self.assertIn((EV_ABS, ABS_MT_ID, -1), writes)
        self.assertIn((EV_KEY, BTN_TOUCH, 0), writes)
        self.assertEqual(probe.sequence.contacts, {})

    def test_close_destroys_only_owned_device_even_if_lift_write_fails(self):
        probe = object.__new__(VirtualTouchProbe)
        probe.uinput, probe.device = 10, 20
        def fail(): raise OSError('write failed')
        probe.release_all = fail
        freed = []
        class API:
            def libevdev_uinput_destroy(self, device): freed.append(('uinput', device))
            def libevdev_free(self, device): freed.append(('description', device))
        probe.api = API()
        with self.assertRaises(OSError): probe.close()
        self.assertEqual(freed, [('uinput', 10), ('description', 20)])
        self.assertIsNone(probe.uinput)
        self.assertIsNone(probe.device)


if __name__ == '__main__':
    unittest.main()
