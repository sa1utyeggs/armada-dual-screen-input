"""Dirty-region geometry plus offscreen pixels; no windows or input devices."""
import sys
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.paint_damage import clip_regions, intersects, ring_damage
from armada_dual_screen_input.keyboard_redraw import widget_rect


class GeometryTests(unittest.TestCase):
    def test_disjoint_damage_does_not_include_the_bounding_box_gap(self):
        cr = SimpleNamespace(copy_clip_rectangle_list=lambda: [(0, 0, 10, 10), (90, 0, 10, 10)])
        regions = clip_regions(cr)
        self.assertTrue(intersects(regions, (95, 5, 3, 3)))
        self.assertFalse(intersects(regions, (40, 0, 20, 10)))
        self.assertFalse(intersects(regions, (10, 0, 80, 10)))
        self.assertFalse(intersects((), (0, 0, 100, 100)))

    def test_nonrectangular_clip_falls_back_to_bounds(self):
        cr = SimpleNamespace(copy_clip_rectangle_list=Mock(side_effect=RuntimeError()),
                             clip_extents=lambda: (3, 5, 13, 25))
        self.assertEqual(clip_regions(cr), ((3, 5, 10, 20),))

    def test_circle_damage_includes_departed_contacts_and_skips_unchanged_ones(self):
        pad = SimpleNamespace(x=20, y=168, width=1200, height=882)
        before = ((.1, .2, True), (.8, .9, True))
        after = ((.2, .3, True), (.8, .9, True))
        rects = ring_damage(before, after, pad)
        self.assertEqual(len(rects), 2)
        self.assertIn((112, 316.4, 56, 56), rects)
        self.assertEqual(ring_damage(after, after, pad), ())
        self.assertEqual(len(ring_damage(after, (), pad)), 2)


@unittest.skipUnless(sys.platform == 'linux', 'Offscreen checks require Linux Cairo/GTK')
class DrawingTests(unittest.TestCase):
    def test_key_release_uses_local_damage_without_a_hidden_full_redraw(self):
        from test_panel_keyboard import PanelKeyboardTests
        from armada_dual_screen_input import panel_app as panel
        from armada_dual_screen_input.keyboard_redraw import KeyboardRedraw
        PanelKeyboardTests.setUp(self)
        self.app.mode = 'split'
        self.app.collapsed = False
        self.app.keyboard_redraw = KeyboardRedraw()
        self.app.keyboard_redraw.remember(self.app.kb_layout, None)
        self.app.drawing_area = SimpleNamespace(queue_draw=Mock(), queue_draw_area=Mock(),
            get_allocation=lambda: SimpleNamespace(width=1240, height=1080))
        key = self.app.kb_layout.rows[2][2]
        with patch.object(panel.GLib, 'idle_add', side_effect=lambda callback: callback()):
            self.app._handle_touch_down(1, key.x+key.w/2, key.y+key.h/2, 1.)
            self.app._handle_touch_up(1, 1.01)
        self.app.drawing_area.queue_draw.assert_not_called()
        self.app.drawing_area.queue_draw_area.assert_called()
        self.assertFalse(self.bridge.held_keys)
        self.assertTrue(self.bridge.events[0][2])
        self.assertFalse(self.bridge.events[-1][2])

    def app(self):
        import cairo
        from armada_dual_screen_input.panel_app import PanelApp
        from armada_dual_screen_input.keyboard_redraw import KeyboardRedraw
        from keyboard_layout import KeyboardLayout
        app = PanelApp.__new__(PanelApp)
        app.mode = 'split'; app.kb_layout = KeyboardLayout(0, 500, 1240, 580)
        app.active_key_press = None; app.keyboard_redraw = KeyboardRedraw()
        app.pen_mode = 'off'; app.touch_mode = 'direct'; app.held_ui_button = None
        app.stats = SimpleNamespace(get_stats=lambda: {})
        app.languages = SimpleNamespace(language='zh_CN', ready=True, preedit='ni',
            candidates=['你', '呢'], page=0, message='中文全拼')
        app._touch_menu_open = False
        app.position = SimpleNamespace(touch_mode='direct', armed=True, message='已启用',
            pad=SimpleNamespace(x=20, y=168, width=1200, height=882),
            direct_gesture=SimpleNamespace(rings=()))
        return app

    def test_key_damage_skips_header_status_trackpad_and_candidates(self):
        import cairo
        app = self.app()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(surface); cr.rectangle(40, 520, 50, 50); cr.clip()
        with patch.object(app, '_draw_header') as header, \
                patch.object(app, '_draw_status_ribbon') as stats, \
                patch.object(app, '_draw_trackpad_surface') as pad, \
                patch('armada_dual_screen_input.keyboard_language_view.draw') as candidates:
            app._draw_ui(cr)
        for draw in (header, stats, pad, candidates):
            draw.assert_not_called()

    def test_disjoint_key_damage_does_not_layout_the_keys_in_between(self):
        import cairo
        from armada_dual_screen_input import steam_keys
        app = self.app(); keys = app.kb_layout.rows[1]
        chosen = (keys[0], keys[-1])
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(surface)
        for key in chosen:
            x, y = math.ceil(key.x+2), math.ceil(key.y+2)
            cr.rectangle(x, y, math.floor(key.x+key.w-2)-x,
                         math.floor(key.y+key.h-2)-y)
        cr.clip()
        with patch.object(steam_keys, '_labels') as labels:
            steam_keys.draw_keyboard(app, cr)
        self.assertEqual([c.args[1] for c in labels.call_args_list], list(chosen))

    def test_touch_cache_reuses_static_content_and_invalidates_message_and_scale(self):
        import cairo
        app = self.app(); app.mode = 'position'
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(surface)
        with patch.object(app, '_draw_position_background', wraps=app._draw_position_background) as draw:
            app._draw_position(cr)
            app.position.direct_gesture.rings = ((.1, .2, True),)
            app._draw_position(cr)
            self.assertEqual(draw.call_count, 1)
            app.position.message = '目标变化'
            app._draw_position(cr)
            self.assertEqual(draw.call_count, 2)
            cr.scale(.55, .55); app._draw_position(cr)
            self.assertEqual(draw.call_count, 3)
            from armada_dual_screen_input.text_render import PangoCairo
            PangoCairo.FontMap.get_default().changed()
            app._draw_position(cr)
            self.assertEqual(draw.call_count, 4)

    def test_partial_touch_moves_and_lifts_match_full_render(self):
        import cairo
        app = self.app(); app.mode = 'position'
        for scale, device_scale in ((1, 1), (.55, 1), (.55, 2)):
            with self.subTest(scale=scale, device_scale=device_scale):
                def surface():
                    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1400, 1250)
                    s.set_device_scale(device_scale, device_scale)
                    return s
                def paint(target, regions=None):
                    cr = cairo.Context(target)
                    if regions is not None:
                        # GTK clips queued damage to outward-rounded widget
                        # pixels before the application's logical transform.
                        for rect in regions:
                            cr.rectangle(*widget_rect(rect, 1240*scale, 1080*scale))
                        cr.clip()
                    cr.scale(scale, scale)
                    app._draw_ui(cr); app._draw_position(cr)
                actual = surface(); old = (); app.position.direct_gesture.rings = old
                paint(actual)
                for new in (((.1, .2, True), (.5, .5, True)),
                            ((.15, .2, True), (.5, .55, True)),
                            ((.5, .55, True),), ()):
                    app.position.direct_gesture.rings = new
                    paint(actual, ring_damage(old, new, app.position.pad))
                    reference = surface(); paint(reference)
                    self.assertTrue(bytes(actual.get_data()) == bytes(reference.get_data()),
                                    'Partial circles differ from a complete frame')
                    old = new

    def test_cache_pixels_match_vector_rendering(self):
        import cairo
        from armada_dual_screen_input import steam_style
        app = self.app(); app.mode = 'position'
        for scale, device_scale in ((1, 1), (.55, 1), (.55, 2)):
            with self.subTest(scale=scale, device_scale=device_scale):
                pixels = []
                for cached in (False, True):
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1400, 1250)
                    surface.set_device_scale(device_scale, device_scale)
                    cr = cairo.Context(surface); cr.scale(scale, scale)
                    cr.set_source_rgb(*steam_style.BG); cr.paint()
                    if cached: app._draw_position(cr)
                    else: app._draw_position_background(cr)
                    pixels.append(bytes(surface.get_data()))
                self.assertTrue(pixels[0] == pixels[1], 'Raster cache differs from vector rendering')
