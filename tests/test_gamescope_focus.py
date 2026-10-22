from dataclasses import replace
import ctypes as c
from types import SimpleNamespace
import unittest

from armada_dual_screen_input.gamescope_focus import Cookie, Geometry, PropertyReply, FocusSnapshot, FocusState, UpperFocus
from armada_dual_screen_input.gamescope_target import InputUnavailable


class FocusServer:
    """In-memory X replies, with request batches and lifetime accounting."""

    def __init__(self):
        self.names = UpperFocus.PROPERTIES + UpperFocus.DISPLAY_PROPERTIES + (UpperFocus.TOUCH_PROPERTY,)
        self.atoms = dict(zip(self.names, range(1, 7)))
        self.properties = dict(zip(self.names, (10, 42, 42, b':0\0', b':0\0', 4)))
        self.requests, self.pending, self.batches = {}, [], []
        self.replies, self.freed, self.discarded = {}, [], []
        self.failed = None
        self.input_window = 10
        self.origin = (0, 0)
        self.parents = {11: 10, 12: 100}

    def queue(self, kind, value=None):
        seq = len(self.requests) + 1
        self.requests[seq] = (kind, value)
        self.pending.append(seq)
        return Cookie(seq)

    def xcb_connection_has_error(self, connection): return 0
    def xcb_get_property(self, connection, delete, window, atom, kind, offset, length):
        return self.queue('property', self.names[atom-1])
    def xcb_get_geometry(self, connection, window): return self.queue('geometry', window)
    def xcb_get_input_focus(self, connection): return self.queue('input')
    def xcb_query_tree(self, connection, window): return self.queue('tree', window)
    def xcb_discard_reply(self, connection, sequence): self.discarded.append(sequence)

    def reply(self, connection, cookie, error):
        if self.pending:
            self.batches.append([self.requests[n][0] for n in self.pending])
            self.pending.clear()
        kind, name = self.requests[cookie.sequence]
        if self.failed is not None and self.failed in (kind, name):
            return 0
        value = self.properties.get(name) if kind == 'property' else None
        data = (value if isinstance(value, bytes) else
                int(value).to_bytes(4, 'little') if value is not None else b'')
        buf = c.create_string_buffer(32 + len(data))
        address = c.addressof(buf)
        if kind == 'property':
            header = PropertyReply.from_address(address)
            header.format = 8 if isinstance(value, bytes) else 32
            header.value_len = len(data) if header.format == 8 else len(data)//4
            header.length = (len(data)+3)//4
            c.memmove(address+32, data, len(data))
        elif kind == 'geometry':
            geo = Geometry.from_address(address)
            geo.width, geo.height = 1920, 1080
            geo.x, geo.y = self.origin
        elif kind == 'input':
            c.c_uint32.from_address(address+8).value = self.input_window
        elif kind == 'tree':
            c.c_uint32.from_address(address+12).value = self.parents.get(name, 100)
        self.replies[address] = (buf, len(data))
        return address

    xcb_get_property_reply = reply
    xcb_get_geometry_reply = reply
    xcb_get_input_focus_reply = reply
    xcb_query_tree_reply = reply
    def xcb_get_property_value(self, reply): return reply+32
    def xcb_get_property_value_length(self, reply): return self.replies[reply][1]
    def free(self, reply):
        if reply:
            self.freed.append(reply)

    def focus(self):
        focus = object.__new__(UpperFocus)
        focus.connection, focus.root, focus.server_pid = 1, 100, 42
        focus.display, focus.surface_connection = ':0', None
        focus.api, focus.libc, focus.atoms = self, SimpleNamespace(free=self.free), self.atoms.copy()
        return focus


class FocusTests(unittest.TestCase):
    def test_property_header_matches_xcb_wire_layout_without_accessor_calls(self):
        self.assertEqual(c.sizeof(PropertyReply), 32)
        self.assertEqual(PropertyReply.value_len.offset, 16)
        server = FocusServer()
        def unexpected(*args):
            self.fail('snapshot must decode the received reply without another native call')
        server.xcb_get_property_value = unexpected
        server.xcb_get_property_value_length = unexpected
        self.assertEqual(server.focus().snapshot().touch_mode, 4)

    def test_truncated_property_body_is_rejected_and_reply_freed(self):
        for name in ('GAMESCOPE_FOCUSED_WINDOW', 'GAMESCOPE_FOCUS_DISPLAY'):
            with self.subTest(name=name):
                server = FocusServer()
                focus = server.focus()
                original = focus._reply
                def reply(kind, cookie):
                    address = original(kind, cookie)
                    if server.requests[cookie.sequence] == ('property', name):
                        PropertyReply.from_address(address).length = 0
                    return address
                focus._reply = reply
                with self.assertRaises(InputUnavailable):
                    focus.snapshot()
                self.assertTrue(server.freed)

    def test_snapshot_batches_root_properties_and_surface_queries(self):
        server = FocusServer()
        snapshot = server.focus().snapshot()
        self.assertEqual(snapshot, FocusSnapshot(10, 42, 42, 1920, 1080, 42, ':0', 10, True, 4))
        self.assertEqual(server.batches, [['property']*6, ['geometry', 'input']])
        self.assertEqual(len(server.freed), 8)
        self.assertFalse(server.discarded)

    def test_batched_snapshot_still_reads_changed_policy_and_target_each_time(self):
        server = FocusServer()
        focus = server.focus()
        old = focus.snapshot()
        server.properties['STEAM_TOUCH_CLICK_MODE'] = 1
        self.assertFalse(old.same_target(focus.snapshot()))
        server.properties['GAMESCOPE_FOCUSED_WINDOW'] = 20
        self.assertFalse(old.same_target(focus.snapshot()))

    def test_window_movement_is_fresh_and_invalidates_existing_input_target(self):
        server = FocusServer()
        focus = server.focus()
        old = focus.snapshot()
        server.origin = (37, -12)
        moved = focus.snapshot()
        self.assertEqual((moved.x, moved.y), (37, -12))
        self.assertFalse(FocusState(moved, 1).matches(old, 1.1))

    def test_batched_snapshot_verifies_child_ancestry_and_rejects_other_surface(self):
        server = FocusServer()
        focus = server.focus()
        server.input_window = 11
        self.assertTrue(focus.snapshot().input_in_surface)
        server.input_window = 12
        self.assertFalse(focus.snapshot().input_in_surface)

    def test_different_display_routes_are_still_rejected(self):
        server = FocusServer()
        server.properties['GAMESCOPE_MOUSE_FOCUS_DISPLAY'] = b':1\0'
        with self.assertRaisesRegex(InputUnavailable, 'displays differ'):
            server.focus().snapshot()
        self.assertEqual(len(server.freed), 6)
        self.assertFalse(server.discarded)

    def test_missing_optional_touch_atom_does_not_queue_invalid_property(self):
        server = FocusServer()
        focus = server.focus()
        focus.atoms['STEAM_TOUCH_CLICK_MODE'] = 0
        self.assertIsNone(focus.snapshot().touch_mode)
        self.assertEqual(server.batches, [['property']*5, ['geometry', 'input']])

    def test_malformed_required_property_releases_remaining_queued_replies(self):
        server = FocusServer()
        server.properties['GAMESCOPE_FOCUSED_WINDOW'] = b''
        with self.assertRaises(InputUnavailable):
            server.focus().snapshot()
        self.assertEqual(server.discarded, [2, 3, 4, 5, 6])
        self.assertEqual(len(server.freed), 1)

    def test_failed_root_reply_discards_other_requests(self):
        server = FocusServer()
        server.failed = 'GAMESCOPE_FOCUSED_APP'
        with self.assertRaises(InputUnavailable):
            server.focus().snapshot()
        self.assertEqual(server.discarded, [3, 4, 5, 6])

    def test_failed_geometry_discards_queued_input_reply(self):
        server = FocusServer()
        server.failed = 'geometry'
        with self.assertRaises(InputUnavailable):
            server.focus().snapshot()
        self.assertEqual(server.discarded, [8])

    def test_failed_input_reply_is_rejected_after_geometry(self):
        server = FocusServer()
        server.failed = 'input'
        with self.assertRaises(InputUnavailable):
            server.focus().snapshot()
        self.assertEqual(len(server.freed), 7)
        self.assertFalse(server.discarded)

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

    def test_verified_child_focus_change_within_same_surface_keeps_drag_target(self):
        focus = FocusSnapshot(10, 769, 769, 1920, 1080, 42, ':0', 11, True, 4)
        child = replace(focus, input_window=12)
        self.assertTrue(FocusState(child, 1).matches(focus, 1.1))
        self.assertTrue(focus.same_target(child))

    def test_real_target_changes_and_unverified_children_are_still_rejected(self):
        focus = FocusSnapshot(10, 769, 769, 1920, 1080, 42, ':0', 11, True, 4)
        for change in ({'window': 20}, {'app_id': 42}, {'graphics_app_id': 42},
                       {'width': 1280}, {'height': 720}, {'server_pid': 43},
                       {'surface_display': ':1'}, {'touch_mode': 1},
                       {'x': 1}, {'y': 1},
                       {'input_window': 12, 'input_in_surface': False}):
            with self.subTest(change=change):
                self.assertFalse(FocusState(replace(focus, **change), 1).matches(focus, 1.1))


if __name__ == '__main__':
    unittest.main()
