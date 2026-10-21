"""Real offscreen glyph checks; never initialize GTK or an input device."""
import sys
import unittest
from unittest.mock import patch

IS_LINUX = sys.platform == 'linux'
if IS_LINUX:
    import cairo
    from armada_dual_screen_input import text_render as text


@unittest.skipUnless(IS_LINUX, 'Pango/Cairo checks require Linux dependencies')
class TextRenderTests(unittest.TestCase):
    def setUp(self):
        text.clear_layout_cache()
        self.addCleanup(text.clear_layout_cache)

    def surface(self, *, scale=1, translation=0, device_scale=1, hint=None):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 180)
        surface.set_device_scale(device_scale, device_scale)
        cr = cairo.Context(surface)
        cr.scale(scale, scale); cr.translate(translation, translation)
        if hint is not None:
            options = cairo.FontOptions(); options.set_hint_style(hint)
            cr.set_font_options(options)
        cr.set_source_rgb(1, .8, .3)
        return surface, cr

    @staticmethod
    def reference(cr, label, size, bold, width):
        layout = text.make_layout(cr, label, size, bold=bold, max_width=width)
        ink, _ = layout.get_pixel_extents()
        cr.move_to(120-ink.x-ink.width/2, 50-ink.y-ink.height/2)
        text.PangoCairo.show_layout(cr, layout)

    def test_cached_text_matches_fresh_layout_across_contexts(self):
        for label in ('a', '@', '中/EN', '你好 世界', '较长的候选词测试'):
            for scale, translation, device_scale, hint in (
                (1, 0, 1, None), (.55, .3, 1, None), (1, 1.2, 1, None),
                (1, 0, 2, None), (1, 0, 1, cairo.HINT_STYLE_NONE)):
                with self.subTest(label=label, scale=scale, translation=translation,
                                  device_scale=device_scale, hint=hint):
                    a, cr = self.surface(scale=scale, translation=translation,
                                         device_scale=device_scale, hint=hint)
                    text.draw_text(cr, label, 120, 50, 25, bold=True,
                                   max_width=90, centered=True)
                    b, ref = self.surface(scale=scale, translation=translation,
                                          device_scale=device_scale, hint=hint)
                    self.reference(ref, label, 25, True, 90)
                    self.assertEqual(bytes(a.get_data()), bytes(b.get_data()))

    def test_repeat_draws_reuse_layout_but_not_color_or_position(self):
        _, cr = self.surface()
        with patch.object(text.PangoCairo, 'create_layout', wraps=text.PangoCairo.create_layout) as create:
            for i in range(100):
                cr.set_source_rgb((i % 3)/3, .5, .7)
                text.draw_text(cr, 'a', i+30, 50, 25)
            self.assertEqual(create.call_count, 1)
            text.draw_text(cr, 'A', 50, 50, 25)
            self.assertEqual(create.call_count, 2)

    def test_cache_is_bounded_and_fontmap_changes_invalidate_layouts(self):
        _, cr = self.surface()
        for i in range(400): text.draw_text(cr, str(i), 50, 50, 25)
        self.assertLessEqual(len(text._local.layouts), 256)
        with patch.object(text.PangoCairo, 'create_layout', wraps=text.PangoCairo.create_layout) as create:
            text.draw_text(cr, '中', 50, 50, 25)
            text.PangoCairo.FontMap.get_default().changed()
            text.draw_text(cr, '中', 50, 50, 25)
            self.assertEqual(create.call_count, 2)

    def test_public_measurement_layout_remains_independent_of_draw_cache(self):
        _, cr = self.surface()
        first = text.make_layout(cr, 'a', 25)
        first.set_text('different', -1)
        second = text.make_layout(cr, 'a', 25)
        self.assertEqual(second.get_text(), 'a')
