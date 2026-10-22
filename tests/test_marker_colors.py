"""Color validation and immutable render state without GTK or input devices."""
from dataclasses import FrozenInstanceError
import sys
import unittest

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
    def test_both_color_rows_draw_all_swatches_and_highlight_the_selected_choice(self):
        import cairo
        from armada_dual_screen_input import settings_view, steam_style
        from armada_dual_screen_input.input_settings import SettingsDraft, color_swatches
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        cr=cairo.Context(surface);cr.set_source_rgb(*steam_style.BG);cr.paint()
        draft=SettingsDraft({'marker_idle_color':'#FFFFFF','marker_pressed_color':'#58E38B'})
        draft.section='position'
        settings_view.draw(cr,draft,monitor_millihz=119930)
        surface.flush();pixels=bytes(surface.get_data());stride=surface.get_stride()
        def pixel(x,y):return pixels[y*stride+x*4:y*stride+x*4+4]
        for key,top in draft.rows():
            if key not in ('marker_idle_color','marker_pressed_color'):continue
            for left,color,_ in color_swatches():
                # The center stays open, revealing the active/neutral tile.
                expected=steam_style.KEY_LATCHED if color==draft.values[key] else steam_style.KEY_MOD
                actual=pixel(left+30,top+44)
                self.assertTrue(all(abs(actual[2-c]-round(expected[c]*255))<=1 for c in (0,1,2)))
                self.assertEqual(actual[3],255)
                # At the ring's right edge the palette color is present.
                expected_rgb=color_rgb(color)
                actual=pixel(left+46,top+44)
                self.assertTrue(all(abs(actual[2-c]-round(expected_rgb[c]*255))<=2 for c in (0,1,2)))


if __name__=='__main__':unittest.main()
