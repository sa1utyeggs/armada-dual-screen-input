import unittest

from mirror_capture import CapturedFrame, FrameStore, pipeline_description


class CaptureTests(unittest.TestCase):
    def frame(self, sequence=1, received_at=10):
        return CapturedFrame(sequence, 2, 2, 8, bytearray(16), received_at)

    def test_store_keeps_only_latest_frame_and_rejects_old_delivery(self):
        store = FrameStore()
        self.assertIsNone(store.latest())
        for sequence in range(1, 100): self.assertTrue(store.publish(self.frame(sequence)))
        self.assertEqual(store.latest().sequence, 99)
        self.assertFalse(store.publish(self.frame(2)))
        self.assertEqual(store.latest().sequence, 99)
        store.clear()
        self.assertIsNone(store.latest())

    def test_stale_and_future_frames_are_not_eligible_for_input(self):
        frame = self.frame()
        self.assertTrue(frame.fresh(10.2))
        self.assertFalse(frame.fresh(10.5))
        self.assertFalse(frame.fresh(9))
        self.assertFalse(frame.fresh(float('nan')))

    def test_bad_layout_and_oversized_buffers_are_rejected(self):
        for width, height, stride, data in ((0, 1, 4, bytearray(4)),
                                           (2, 2, 4, bytearray(16)),
                                           (2, 2, 8, bytearray(15)),
                                           (8192, 8192, 32768, bytearray())):
            with self.assertRaises(ValueError):
                CapturedFrame(1, width, height, stride, data, 10)

    def test_pipeline_has_bounded_queues_without_size_renegotiation(self):
        value = pipeline_description(55, 60)
        self.assertIn('leaky=downstream', value)
        self.assertIn('max-buffers=1 drop=true', value)
        self.assertIn('framerate=60/1', value)
        self.assertLess(value.index('videorate'), value.index('videoconvert'))
        self.assertIn('drop-only=true', value)
        self.assertNotIn('width=', value)
        self.assertNotIn('height=', value)
        self.assertNotIn('videoscale', value)
        self.assertIn('on-disconnect=error', value)
        self.assertIn('use-bufferpool=false', value)

    def test_pipeline_options_cannot_inject_additional_elements(self):
        for arguments in (('55 ! fakesink', 60), (0, 60), (55, 0), (55, True)):
            with self.assertRaises(ValueError): pipeline_description(*arguments)


if __name__ == '__main__':
    unittest.main()
