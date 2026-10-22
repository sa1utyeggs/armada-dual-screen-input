"""Real Pango/Cairo bilingual layouts, with no windows or input devices."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from armada_dual_screen_input.i18n import configure, active_language, msg
from armada_dual_screen_input.input_settings import SettingsDraft, SETTINGS_PAGES

IS_LINUX = sys.platform == 'linux'
if IS_LINUX:
    import cairo
    import test_panel_keyboard as fixture
    from armada_dual_screen_input import settings_view, steam_style, text_render, touchscreen_selector
    from armada_dual_screen_input.panel_position import PanelPosition


def scenes(language):
    """Own image surfaces only; useful for inspecting the same tested layouts."""
    configure(language)
    app = fixture.panel_app.PanelApp.__new__(fixture.panel_app.PanelApp)
    app.mode = 'trackpad'
    app.held_ui_button = None
    app._touch_menu_open = False
    app.position = PanelPosition()
    app.stats = SimpleNamespace(get_stats=lambda: {
        'bat_cap': 100, 'cpu_load': 100, 'cpu_temp': 99, 'gpu_mhz': 1000, 'gpu_temp': 99,
        'ram_used_gb': 15.9, 'ram_total_gb': 16, 'vol_pct': 100,
        'top_bright_pct': 100, 'bot_bright_pct': 100})
    def surface():
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        cr.set_source_rgb(*steam_style.BG)
        cr.paint()
        return image, cr
    def header(cr):
        steam_style.draw_header(app, cr, fixture.panel_app.upstream.HEADER_BUTTONS, 8, 64, 1240)
        steam_style.draw_status(app, cr, 80, 44, 1240)
    image, cr = surface()
    header(cr)
    steam_style.draw_trackpad(app, cr, 124, 956, 1240)
    yield 'touchpad', image
    for mode in ('position', 'direct'):
        app.mode = 'position'
        app.position.touch_mode = mode
        image, cr = surface()
        header(cr)
        app._draw_position_background(cr)
        touchscreen_selector.draw_button(cr, mode)
        touchscreen_selector.draw_menu(cr, mode)
        yield mode, image
    app.mode = 'preferences'
    for section in SETTINGS_PAGES:
        draft = SettingsDraft({'ui_language': language})
        draft.section = section
        updates = SimpleNamespace(current='0.1.3', latest=SimpleNamespace(tag='v0.2.0'),
            message=str(msg('update.check_timeout')), phase='error', managed=True,
            confirming=True, busy=False, available=True)
        image, cr = surface()
        header(cr)
        settings_view.draw(cr, draft, updates, monitor_millihz=120000)
        yield section, image
        if section == 'general':
            for variant in ('ready', 'confirm', 'busy', 'error'):
                uninstall = SimpleNamespace(managed=True, phase='error' if variant == 'error' else 'ready',
                    confirming=variant == 'confirm', busy=variant == 'busy',
                    message=str(msg('uninstall.start_failed' if variant == 'error' else
                                    'uninstall.running' if variant == 'busy' else 'uninstall.ready')))
                image, cr = surface()
                header(cr)
                settings_view.draw(cr, draft, updates, uninstall=uninstall)
                yield 'uninstall-'+variant, image


@unittest.skipUnless(IS_LINUX, 'Bilingual layout checks require Linux Pango/Cairo')
class BilingualRenderTests(unittest.TestCase):
    def setUp(self):
        previous = active_language()
        self.addCleanup(configure, previous)

    def test_both_languages_fit_existing_surfaces_with_readable_fonts(self):
        original = steam_style.label
        calls = []
        def check(cr, value, x, y, size, **kwargs):
            text = str(value)
            layout = text_render.make_layout(cr, text, size, bold=kwargs.get('bold', False),
                                             max_width=kwargs.get('max_width'))
            fitted = layout.get_font_description().get_size() / text_render.Pango.SCALE
            self.assertGreaterEqual(fitted, 16, (active_language(), text, fitted))
            ink, logical = layout.get_pixel_extents()
            if kwargs.get('max_width'):
                self.assertLessEqual(max(ink.width, logical.width), kwargs['max_width']+1, text)
            self.assertEqual(layout.get_unknown_glyphs_count(), 0, text)
            self.assertEqual(layout.get_line_count(), 1)
            calls.append(text)
            return original(cr, text, x, y, size, **kwargs)
        with patch.object(steam_style, 'label', side_effect=check):
            for language in ('en_US', 'zh_CN'):
                calls.clear()
                rendered = list(scenes(language))
                self.assertEqual(len(rendered), 12)
                self.assertIn('Save settings' if language == 'en_US' else '保存设置', calls)
                self.assertIn('Interface language' if language == 'en_US' else '界面语言', calls)
                if language == 'en_US':
                    self.assertFalse(any(any('\u3400' <= c <= '\u9fff' for c in text) for text in calls))

    def test_layout_cache_separates_languages_for_identical_text(self):
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        text_render.clear_layout_cache()
        with patch.object(text_render.PangoCairo, 'create_layout', wraps=text_render.PangoCairo.create_layout) as create:
            configure('en_US')
            text_render.draw_text(cr, 'CPU', 0, 0, 22)
            text_render.draw_text(cr, 'CPU', 0, 0, 22)
            configure('zh_CN')
            text_render.draw_text(cr, 'CPU', 0, 0, 22)
            self.assertEqual(create.call_count, 2)

    def test_static_background_rebuilds_when_only_ui_language_changes(self):
        from armada_dual_screen_input.static_layer import StaticLayer
        layer = StaticLayer()
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        def draw(context):
            context.set_source_rgb(*steam_style.BG)
            context.paint()
            context.set_source_rgb(*steam_style.FG)
            steam_style.label(context, msg('common.settings'), 20, 20, 30)
        with patch('builtins.open', side_effect=AssertionError('No translation file I/O during painting')):
            configure('en_US')
            layer.paint(cr, 'unchanged-content', 1240, 1080, draw)
            english = bytes(image.get_data())
            configure('zh_CN')
            layer.paint(cr, 'unchanged-content', 1240, 1080, draw)
            self.assertNotEqual(english, bytes(image.get_data()))
            configure('en_US')
            layer.paint(cr, 'unchanged-content', 1240, 1080, draw)
            self.assertEqual(english, bytes(image.get_data()))
