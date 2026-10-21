import unittest
from armada_dual_screen_input.marker_state import decode_rings, validate_rings


class MarkerStateTests(unittest.TestCase):
    def test_legacy_single_ring_and_multiple_contacts_share_normalized_state(self):
        self.assertEqual(decode_rings([.2, .3, False]), ((.2, .3, False),))
        rings = [[.2, .3, True], [.7, .8, True]]
        self.assertEqual(decode_rings({'contacts': rings}), tuple(tuple(ring) for ring in rings))

    def test_empty_contacts_clear_all_visible_rings(self):
        self.assertEqual(decode_rings({'contacts': []}), ())

    def test_marker_payload_is_bounded_and_rejects_malformed_points(self):
        bad = ({'contacts': [[.5, .5, True]]*11}, {'contacts': [[float('nan'), .5, True]]},
               {'contacts': [[2, .5, True]]}, {'contacts': [[True, .5, True]]},
               {'contacts': [[.5, .5, 1]]}, {'contacts': [[.5, .5]]},
               {'contacts': [], 'other': True}, {'restore': True}, None)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                decode_rings(payload)

    def test_maximum_contact_payload_is_supported(self):
        self.assertEqual(len(validate_rings([(.5, .5, True)]*10)), 10)
