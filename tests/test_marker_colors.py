"""Color validation and immutable render state without GTK or input devices."""
from dataclasses import FrozenInstanceError
import math
import sys
import unittest
from unittest.mock import patch

from armada_dual_screen_input.marker_colors import MarkerColors, DEFAULT_COLORS, parse_color, color_rgb


class MarkerColorTests(unittest.TestCase):
    def test_defaults_preserve_the_previous_strokes_exactly(self):
        self.assertEqual(DEFAULT_COLORS.idle_rgba,(.35,.85,1.,1.))
        self.assertEqual(DEFAULT_COLORS.pressed_rgba,(1.,.65,.15,1.))

    def test_custom_channels_are_normalized_once_and_remain_opaque(self):
        colors=MarkerColors('#00ff80','#1234aB')
        self.assertEqual(colors.idle,'#00FF80')
        self.assertEqual(colors.pressed,'#1234AB')
        self.assertEqual(colors.idle_rgba,(0,1,128/255,1))
        self.assertEqual(colors.pressed_rgba,(*color_rgb('#1234AB'),1))
        with self.assertRaises(FrozenInstanceError):colors.idle='#FFFFFF'

    def test_invalid_cli_colors_cannot_reach_the_worker(self):
        for value in (None,False,42,[],{},'red','#fff','#12345678','#12345G','#123456\n'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):parse_color(value)
                with self.assertRaises(ValueError):MarkerColors(value,'#FFFFFF')
                with self.assertRaises(ValueError):MarkerColors('#FFFFFF',value)


@unittest.skipUnless(sys.platform=='linux','Color settings drawing requires Linux Cairo/Pango')
class ColorSettingsDrawingTests(unittest.TestCase):
    def test_ring_preset_previews_draw_both_selected_state_colors_without_color_rows(self):
        import cairo
        from armada_dual_screen_input import settings_view, steam_style
        from armada_dual_screen_input.input_settings import SettingsDraft, marker_style_tiles
        from armada_dual_screen_input.marker_appearance import load_appearance, RING_PRESETS
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(surface)
        cr.set_source_rgb(*steam_style.BG)
        cr.paint()
        draft = SettingsDraft({'position_marker_style': 'glove',
                               'marker_idle_color': '#FF0000', 'marker_pressed_color': '#FF00FF'})
        draft.section = 'position'
        self.assertTrue({'marker_idle_color', 'marker_pressed_color'}.isdisjoint(dict(draft.rows())))
        with patch.object(settings_view, 'marker_preview_transform',
                          wraps=settings_view.marker_preview_transform) as transform:
            settings_view.draw(cr, draft, monitor_millihz=119930)
        surface.flush()
        pixels, stride = bytes(surface.get_data()), surface.get_stride()
        def pixel(x, y):
            x, y = round(x), round(y)
            return pixels[y*stride+x*4:y*stride+x*4+4]
        for index, (style, left, top, _, _) in enumerate(marker_style_tiles()):
            if style not in RING_PRESETS:
                continue
            with self.subTest(style=style):
                colors = RING_PRESETS[style]
                self.assertEqual(load_appearance(style).colors, colors)
                calls = transform.call_args_list[index*2:index*2+2]
                self.assertEqual(len(calls), 2)
                background = pixel(left+20, top+20)
                for call, pressed in zip(calls, (False, True)):
                    center, y = call.args[1:]
                    actual = pixel(center, y)
                    # Each open center reveals its card's background fill.
                    self.assertTrue(all(abs(actual[c]-background[c]) <= 1 for c in (0, 1, 2)))
                    self.assertEqual(actual[3], 255)
                    expected = colors.pressed_rgba if pressed else colors.idle_rgba
                    _, _, scale = settings_view.marker_preview_transform(load_appearance(style), center, y,
                                                                         pressed=pressed)
                    # Card centers may fall between device pixels. A fixed
                    # rightmost sample can land in the resampling fringe;
                    # find the actual solid color along the ring centerline.
                    radius = 12*scale
                    solid = []
                    for py in range(math.floor(y-radius-2), math.ceil(y+radius+2)+1):
                        for px in range(math.floor(center-radius-2), math.ceil(center+radius+2)+1):
                            if abs(math.hypot(px+.5-center, py+.5-y)-radius) > 1:
                                continue
                            actual = pixel(px, py)
                            if actual[3] == 255 and all(abs(actual[2-c]-round(expected[c]*255)) <= 2
                                                       for c in (0, 1, 2)):
                                solid.append((px+.5 >= center, py+.5 >= y))
                    self.assertGreaterEqual(len(solid), 8, (style, pressed, expected))
                    self.assertEqual(set(solid), {(False, False), (False, True),
                                                  (True, False), (True, True)}, (style, pressed))


if __name__=='__main__':unittest.main()
