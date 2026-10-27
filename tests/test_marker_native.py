"""Native submission contracts without opening windows or input devices."""
import ctypes as c
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.marker_egl import Surface, damage_values
from armada_dual_screen_input.marker_gpu import Renderer, rgba_pixels
from armada_dual_screen_input.marker_appearance import MarkerAppearance
from armada_dual_screen_input.marker_colors import DEFAULT_COLORS
from armada_dual_screen_input.marker_native_worker import NativeUnavailable
from armada_dual_screen_input import marker_worker


class MarkerBackendTests(unittest.TestCase):
    def test_native_success_does_not_initialize_gtk(self):
        with patch('armada_dual_screen_input.marker_native_worker.run', return_value=42) as native:
            with patch.dict('sys.modules', {'armada_dual_screen_input.marker_gtk_worker': None}):
                self.assertEqual(marker_worker.run(7, 'target', '120'), 42)
        native.assert_called_once()

    def test_only_unpublished_setup_failure_falls_back_using_same_fd_and_settings(self):
        gtk = Mock(return_value=11)
        with patch('armada_dual_screen_input.marker_native_worker.run', side_effect=NativeUnavailable('no alpha visual')):
            with patch.dict('sys.modules', {'armada_dual_screen_input.marker_gtk_worker': SimpleNamespace(run=gtk)}):
                self.assertEqual(marker_worker.run(7, 'target', '60'), 11)
        self.assertEqual(gtk.call_args.args, (7, 'target', '60'))

    def test_position_style_reaches_both_backends_without_changing_fallback_rules(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style):
                with patch('armada_dual_screen_input.marker_native_worker.run', return_value=42) as native:
                    self.assertEqual(marker_worker.run(7, 'target', '60', position_style=style), 42)
                self.assertEqual(native.call_args.kwargs['position_style'], style)
                gtk = Mock(return_value=11)
                with patch('armada_dual_screen_input.marker_native_worker.run',
                           side_effect=NativeUnavailable('no alpha visual')) as native:
                    with patch.dict('sys.modules', {'armada_dual_screen_input.marker_gtk_worker':
                                                  SimpleNamespace(run=gtk)}):
                        self.assertEqual(marker_worker.run(7, 'target', '60', position_style=style), 11)
                self.assertEqual(native.call_args.kwargs['position_style'], style)
                self.assertEqual(gtk.call_args.kwargs['position_style'], style)
                self.assertEqual(gtk.call_args.args, (7, 'target', '60'))

    def test_startup_artwork_fallback_is_resolved_once_and_shared_across_backends(self):
        fallback = MarkerAppearance('ring')
        for style in ('glove', 'pixel_hand'):
            with self.subTest(style=style):
                gtk = Mock(return_value=11)
                with patch.object(marker_worker, 'load_appearance', return_value=fallback) as resolve, \
                     patch('armada_dual_screen_input.marker_native_worker.run',
                           side_effect=NativeUnavailable('no EGL surface')) as native:
                    with patch.dict('sys.modules', {'armada_dual_screen_input.marker_gtk_worker':
                                                  SimpleNamespace(run=gtk)}):
                        self.assertEqual(marker_worker.run(7, 'target', position_style=style), 11)
                resolve.assert_called_once_with(style, DEFAULT_COLORS)
                self.assertIs(native.call_args.kwargs['appearance'], fallback)
                self.assertIs(gtk.call_args.kwargs['appearance'], fallback)

    def test_runtime_or_target_failure_never_switches_live_backends(self):
        gtk = Mock()
        for error in (RuntimeError('target changed'), OSError('connection lost')):
            with self.subTest(error=error), patch('armada_dual_screen_input.marker_native_worker.run', side_effect=error):
                with patch.dict('sys.modules', {'armada_dual_screen_input.marker_gtk_worker': SimpleNamespace(run=gtk)}):
                    with self.assertRaises(type(error)):
                        marker_worker.run(7, 'target')
        gtk.assert_not_called()

    def test_native_setup_failure_cleans_unmapped_resources_without_using_ipc(self):
        from armada_dual_screen_input import marker_native_worker as worker
        control, focus = Mock(), Mock()
        expected = Mock()
        expected.compatible.return_value = True
        control.snapshot.return_value = expected
        target = SimpleNamespace(surface_display=':0', server_pid=123, width=320,
                                 height=180, matches_focus=Mock(return_value=True))
        focus.server_pid = 123
        gi = SimpleNamespace(require_version=Mock())
        repository = SimpleNamespace(Gdk=Mock(), GdkX11=Mock(), GLib=Mock())
        geometry = SimpleNamespace(from_address=lambda _: SimpleNamespace(width=320, height=180))
        with patch.dict('sys.modules', {'gi': gi, 'gi.repository': repository}), \
             patch('armada_dual_screen_input.gamescope_focus.UpperFocus', side_effect=[control, focus]), \
             patch('armada_dual_screen_input.gamescope_focus.Geometry', geometry), \
             patch('armada_dual_screen_input.marker_egl.Surface', side_effect=ValueError('optional GL entry unavailable')), \
             patch.object(worker.socket, 'socket') as channel, patch.dict('os.environ'):
            with self.assertRaises(NativeUnavailable):
                worker.run(7, target)
        channel.assert_not_called()
        focus.close.assert_called_once()
        control.close.assert_called_once()


class EGLSurfaceTests(unittest.TestCase):
    def test_damage_y_conversion_keeps_separate_rectangles_and_full_frame(self):
        self.assertEqual(damage_values(((2, 3, 10, 20), (50, 60, 15, 12)), 100, 80),
                         [2, 57, 10, 20, 50, 8, 15, 12])
        self.assertEqual(damage_values(((0, 0, 100, 80),), 100, 80), [0, 0, 100, 80])

    def test_invalid_damage_cannot_cross_native_boundary(self):
        for rect in ((0, 0, 0, 1), (-1, 0, 3, 3), (90, 0, 11, 1),
                     (0, 79, 1, 2), (True, 0, 1, 1), (0, 0, 1.5, 1), (0, 0)):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                damage_values((rect,), 100, 80)
        with self.assertRaises(ValueError):
            damage_values(((0, 0, 1, 1),)*65, 100, 80)

    def test_configure_uses_complete_32_bit_window_id_and_own_window_only(self):
        api = Mock()
        focus = SimpleNamespace(api=api, connection=900)
        # Setup is skipped, but real binding declarations are checked.
        with patch('armada_dual_screen_input.marker_egl.c.CDLL', return_value=Mock()), patch.object(Surface, 'setup'):
            surface = Surface(focus, SimpleNamespace())
        self.assertEqual(api.xcb_configure_window_checked.argtypes,
                         [c.c_void_p, c.c_uint, c.c_uint16, c.c_void_p])
        surface.window = 0x03A00003
        surface.checked = Mock()
        surface.raise_window()
        args = api.xcb_configure_window_checked.call_args.args
        self.assertEqual(args[:3], (900, 0x03A00003, 1 << 6))
        self.assertEqual(c.cast(args[3], c.POINTER(c.c_uint32)).contents.value, 0)
        surface.checked.assert_called_once()

    def test_egl_damage_path_receives_bottom_left_hints(self):
        surface = Surface.__new__(Surface)
        surface.target = SimpleNamespace(width=100, height=80)
        surface.display, surface.surface = 10, 20
        seen = []
        surface.swap_damage = lambda display, window, rects, count: seen.append((display, window, list(rects), count)) or 1
        surface.check = Mock()
        surface.swap(((2, 3, 10, 20),))
        self.assertEqual(seen, [(10, 20, [2, 57, 10, 20], 1)])
        surface.swap(())
        self.assertEqual(len(seen), 1)

    def test_no_damage_extension_still_submits_complete_rendered_backbuffer(self):
        surface = Surface.__new__(Surface)
        surface.display, surface.surface = 10, 20
        surface.swap_damage = None
        surface.egl = Mock()
        surface.check = Mock()
        surface.swap(((0, 0, 10, 10),))
        surface.egl.eglSwapBuffers.assert_called_once_with(10, 20)

    def test_close_releases_gpu_before_only_own_xcb_resources_and_is_idempotent(self):
        events = []
        def logger(name):
            return lambda *args: events.append(name)
        surface = Surface.__new__(Surface)
        surface.display, surface.context, surface.surface = 1, 2, 3
        surface.window, surface.colormap = 0x12345678, 0x12345679
        surface.egl = SimpleNamespace(**{name: logger(name) for name in (
            'eglMakeCurrent', 'eglDestroySurface', 'eglDestroyContext', 'eglTerminate')})
        surface.focus = SimpleNamespace(connection=9, api=SimpleNamespace(
            xcb_destroy_window=logger('destroy-window'), xcb_free_colormap=logger('free-colormap'),
            xcb_flush=logger('flush')))
        surface.close()
        self.assertEqual(events, ['eglMakeCurrent', 'eglDestroySurface', 'eglDestroyContext',
                                  'eglTerminate', 'destroy-window', 'free-colormap', 'flush'])
        events.clear()
        surface.close()
        self.assertEqual(events, [])


class GPUSpriteTests(unittest.TestCase):
    def test_native_cairo_byte_order_conversion_retains_premultiplied_alpha(self):
        with patch('sys.byteorder', 'little'):
            self.assertEqual(rgba_pixels(bytes([3, 4, 5, 9, 1, 2, 3, 4])), bytes([5, 4, 3, 9, 3, 2, 1, 4]))
        with patch('sys.byteorder', 'big'):
            self.assertEqual(rgba_pixels(bytes([9, 5, 4, 3])), bytes([5, 4, 3, 9]))

    def test_each_frame_clears_full_backbuffer_and_selects_correct_color_phase(self):
        renderer = Renderer.__new__(Renderer)
        renderer.gl = gl = Mock()
        renderer.canvas = (101, 101)
        renderer.program, renderer.vao = 2, c.c_uint(3)
        renderer.textures = [c.c_uint(4), c.c_uint(5)]
        renderer.position_textures = []
        renderer.appearance = MarkerAppearance()
        renderer.canvas_location, renderer.tile_location, renderer.atlas_location = 6, 7, 8
        renderer.sizes_location = 9
        renderer.draw(((.20125, .30125, False), (.7, .8, True)))
        gl.ClearColor.assert_called_once_with(0, 0, 0, 0)
        gl.Clear.assert_called_once_with(0x4000)
        gl.BlendFunc.assert_called_once_with(1, 0x0303)
        self.assertEqual(gl.DrawArrays.call_count, 2)
        self.assertEqual(gl.Uniform4f.call_args_list[0].args, (7, 2, 12, 36, 36))
        self.assertEqual(gl.BindTexture.call_args_list[0].args, (0x0DE1, 4))
        self.assertEqual(gl.BindTexture.call_args_list[1].args, (0x0DE1, 5))
        gl.TexImage2D.assert_not_called()
        gl.reset_mock()
        renderer.draw(())
        gl.Clear.assert_called_once_with(0x4000)
        gl.DrawArrays.assert_not_called()
        gl.TexImage2D.assert_not_called()

    def test_position_pose_changes_keep_each_hotspot_and_direct_contacts_use_ring_atlas(self):
        renderer = Renderer.__new__(Renderer)
        renderer.gl = gl = Mock()
        renderer.canvas = (201, 121)
        renderer.program, renderer.vao = 2, c.c_uint(3)
        renderer.textures = [c.c_uint(4), c.c_uint(5)]
        renderer.position_textures = [c.c_uint(40), c.c_uint(41)]
        renderer.canvas_location, renderer.tile_location, renderer.atlas_location = 6, 7, 8
        renderer.sizes_location = 9
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style):
                renderer.appearance = MarkerAppearance(style)
                positions = []
                for pressed, texture in ((False, 40), (True, 41)):
                    gl.reset_mock()
                    renderer.draw(((.5, .5, pressed),), mode='position')
                    positions.append(gl.Uniform4f.call_args.args)
                    gl.BindTexture.assert_called_once_with(0x0DE1, texture)
                    gl.Uniform2f.assert_any_call(9, 64, 512)
                    gl.TexImage2D.assert_not_called()
                    gl.GenTextures.assert_not_called()
                    gl.DrawArrays.assert_called_once_with(5, 0, 4)
                ox, oy = renderer.appearance.origin
                self.assertEqual(positions, [(7, 100-ox, 60-oy, 0, 0)]*2)
                for mode in ('direct', 'legacy'):
                    gl.reset_mock()
                    renderer.draw(((.5, .5, True),), mode=mode)
                    gl.BindTexture.assert_called_once_with(0x0DE1, 5)
                    gl.Uniform2f.assert_any_call(9, 36, 288)
                    gl.Uniform4f.assert_called_once_with(7, 82, 42, 0, 0)
                    gl.TexImage2D.assert_not_called()

    def test_renderer_close_releases_both_atlases_and_is_idempotent(self):
        renderer = Renderer.__new__(Renderer)
        renderer.gl = gl = Mock()
        renderer.program, renderer.vao = 2, c.c_uint(3)
        renderer.textures = [c.c_uint(4), c.c_uint(5)]
        renderer.position_textures = [c.c_uint(40), c.c_uint(41)]
        renderer.close()
        self.assertEqual(gl.DeleteTextures.call_count, 4)
        gl.DeleteVertexArrays.assert_called_once()
        gl.DeleteProgram.assert_called_once_with(2)
        gl.reset_mock()
        renderer.close()
        self.assertFalse(gl.mock_calls)


if __name__ == '__main__':
    unittest.main()
