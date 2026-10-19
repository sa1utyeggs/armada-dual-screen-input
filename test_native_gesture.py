import unittest

from mirror_geometry import MirrorTransform, Rect
from native_gesture import NativeMirroredTouch


class NativeGestureTests(unittest.TestCase):
    def setUp(self):
        self.gesture = NativeMirroredTouch(MirrorTransform.fit(1920, 1080, Rect(0, 0, 1000, 1000)))

    def test_first_contact_is_immediate_without_chord_wait(self):
        event, = self.gesture.begin(8, 500, 500, 1)
        self.assertEqual((event.kind, event.position, event.contact_id), ('down', (.5, .5), 8))
        self.assertEqual(self.gesture.tick(1), ())

    def test_two_fingers_move_independently_without_any_wheel_intent(self):
        events = self.gesture.begin(1, 450, 500, 1)
        events += self.gesture.begin(2, 550, 500, 2)  # no simultaneous-landing deadline
        events += self.gesture.move(1, 450, 470, 3)
        events += self.gesture.move(2, 550, 480, 4)
        self.assertEqual(self.gesture.state, 'multi')
        self.assertEqual([e.kind for e in events], ['down', 'down', 'move', 'move'])
        self.assertEqual([e.contact_id for e in events], [1, 2, 1, 2])
        self.assertEqual(self.gesture.end(1, 5)[0].contact_id, 1)
        self.assertEqual(self.gesture.state, 'single')
        self.assertEqual(self.gesture.end(2, 6)[0].contact_id, 2)
        self.assertEqual(self.gesture.state, 'idle')

    def test_margin_touch_is_ignored_and_drag_is_clamped(self):
        self.assertEqual(self.gesture.begin(1, 500, 0, 1), ())
        self.assertEqual(self.gesture.move(1, 500, 500, 2), ())
        self.assertEqual(self.gesture.end(1, 3), ())
        self.gesture.begin(2, 500, 500, 4)
        event, = self.gesture.move(2, -500, -500, 5)
        self.assertEqual(event.position, (0, 0))

    def test_third_finger_is_ignored_without_interrupting_two_contacts(self):
        self.gesture.begin(1, 450, 500, 1)
        self.gesture.begin(2, 550, 500, 1)
        self.assertEqual(self.gesture.begin(3, 600, 500, 1), ())
        self.assertEqual(self.gesture.end(3, 2), ())
        self.assertEqual(self.gesture.state, 'multi')

    def test_cancel_and_resize_discard_all_old_contacts(self):
        self.gesture.begin(1, 450, 500, 1)
        self.gesture.begin(2, 550, 500, 1)
        events = self.gesture.set_transform(self.gesture.transform, 2)
        self.assertEqual([e.kind for e in events], ['cancel', 'cancel'])
        self.assertEqual(self.gesture.end(1, 3), ())
        self.assertEqual(self.gesture.move(2, 400, 400, 3), ())
