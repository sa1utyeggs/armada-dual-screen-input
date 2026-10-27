"""Real Pango/Cairo bilingual layouts, with no windows or input devices."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.i18n import configure, active_language, msg
from armada_dual_screen_input.input_settings import (
    SettingsDraft, SETTINGS_PAGES, CHOICES, position_preview_top, marker_style_tiles,
)

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
        'bat_cap': 100, 'bat_watts': -99.9, 'cpu_load': 100, 'cpu_temp': 99, 'gpu_mhz': 1000, 'gpu_temp': 99,
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
        if section == 'position':
            for style in CHOICES['position_marker_style']:
                if style == draft.saved['position_marker_style']:
                    continue
                draft.change('position_marker_style', style)
                image, cr = surface()
                header(cr)
                settings_view.draw(cr, draft, updates, monitor_millihz=120000)
                yield 'position-'+style, image
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
        if section == 'driver':
            for variant in ('active','compatible','incompatible','confirm_apply','confirm_revert','busy','missing','error'):
                info=dict(component=variant!='missing',compatible=variant!='incompatible',
                          active=variant in ('active','confirm_revert'),kernel='7.2.6')
                driver=SimpleNamespace(info=info,phase='error' if variant=='error' else 'idle',
                    confirming='apply' if variant=='confirm_apply' else 'revert' if variant=='confirm_revert' else None,
                    busy=variant=='busy',message=str(msg('driver.'+(
                        'check_failed' if variant=='error' else 'component_missing' if variant=='missing'
                        else 'checking' if variant=='busy' else 'incompatible' if variant=='incompatible'
                        else 'active' if info['active'] else 'compatible'))))
                driver.can=lambda action: not driver.busy and info['component'] and (
                    info['compatible'] and not info['active'] if action=='apply' else info['active'])
                image,cr=surface();header(cr)
                settings_view.draw(cr,draft,updates,driver=driver)
                yield 'driver-'+variant,image


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
                self.assertEqual(len(rendered), 19+len(CHOICES['position_marker_style']))
                self.assertIn('Save settings' if language == 'en_US' else '保存设置', calls)
                self.assertIn('Interface language' if language == 'en_US' else '界面语言', calls)
                self.assertIn('Icon style' if language == 'en_US' else '图标样式', calls)
                if language == 'en_US':
                    self.assertFalse(any(any('\u3400' <= c <= '\u9fff' for c in text) for text in calls))

    def test_all_five_unlabeled_icon_cards_are_visible_in_both_languages(self):
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        for language in ('en_US', 'zh_CN'):
            configure(language)
            for style in CHOICES['position_marker_style']:
                draft = SettingsDraft({'position_marker_style': style})
                draft.section = 'position'
                with patch.object(steam_style, 'label', wraps=steam_style.label) as label, \
                        patch.object(steam_style, 'rounded', wraps=steam_style.rounded) as rounded:
                    settings_view.draw(cr, draft)
                calls = label.call_args_list
                texts = [str(call.args[1]) for call in calls]
                self.assertIn(str(msg('settings.position_marker_style')), texts)
                self.assertNotIn(str(msg('settings.idle_color')), texts)
                self.assertNotIn(str(msg('settings.pressed_color')), texts)
                self.assertNotIn(str(msg('settings.marker_preview')), texts)
                for caption in CHOICES['position_marker_style'].values():
                    self.assertNotIn(str(caption), texts)
                self.assertIn(str(msg('settings.marker_style_pick_note')), texts)
                for _, left, card_top, width, height in marker_style_tiles():
                    self.assertTrue(any(call.args[1:5] == (left, card_top, width, height)
                                        for call in rounded.call_args_list))
                note = next(call for call in calls if str(call.args[1]) == str(msg('settings.marker_style_pick_note')))
                layout = text_render.make_layout(cr, str(note.args[1]), note.args[4],
                                                 max_width=note.kwargs.get('max_width'))
                ink, logical = layout.get_pixel_extents()
                self.assertLessEqual(note.args[3]+max(ink.height, logical.height),
                                     min(tile[2] for tile in marker_style_tiles()))
                top = position_preview_top(draft)
                self.assertGreater(top, max(y+88 for _, y in draft.rows()))
                for key in ('settings.touch_gesture', 'settings.touch_style'):
                    draw = next(call for call in calls if str(call.args[1]) == str(msg(key)))
                    self.assertGreaterEqual(draw.args[3], top)
                    self.assertLess(draw.args[3]+draw.args[4], 934)

    def test_marker_preview_is_cached_and_asset_failure_keeps_settings_usable(self):
        draft = SettingsDraft({'position_marker_style': 'glove'})
        draft.section = 'position'
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        def appearance(style, **_):
            kind = 'ring' if style.startswith('ring') else style
            size = 36 if kind == 'ring' else 64
            sprite = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
            bounds = (3, 3, 33, 33) if kind == 'ring' else (8, 8, 56, 56)
            return SimpleNamespace(style=kind, tile_size=size,
                preview_bounds=lambda pressed=False: bounds,
                sprite=lambda *_: sprite)
        settings_view._preview_appearance.cache_clear()
        self.addCleanup(settings_view._preview_appearance.cache_clear)
        with patch('armada_dual_screen_input.marker_appearance.load_appearance', side_effect=appearance) as load:
            settings_view.draw(cr, draft)
            settings_view.draw(cr, draft)
            self.assertEqual(load.call_count, len(CHOICES['position_marker_style']))
        settings_view._preview_appearance.cache_clear()
        with patch('armada_dual_screen_input.marker_appearance.load_appearance', side_effect=OSError('missing image')) as load, \
                patch.object(steam_style, 'label', wraps=steam_style.label) as label:
            settings_view.draw(cr, draft)
            settings_view.draw(cr, draft)
            self.assertEqual(load.call_count, len(CHOICES['position_marker_style']))
            texts = [str(call.args[1]) for call in label.call_args_list]
            self.assertIn(str(msg('settings.marker_preview_unavailable')), texts)
            self.assertIn(str(msg('settings.save')), texts)

    def test_preview_centers_each_visible_glyph_without_using_the_runtime_hotspot(self):
        from armada_dual_screen_input.marker_appearance import load_appearance
        image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
        cr = cairo.Context(image)
        draft = SettingsDraft({'position_marker_style': 'glove'})
        draft.section = 'position'
        with patch.object(settings_view, 'marker_preview_transform',
                          wraps=settings_view.marker_preview_transform) as transform:
            settings_view.draw(cr, draft)
        image.flush()
        data, stride = bytes(image.get_data()), image.get_stride()
        def pixel(x, y):
            offset = y*stride+x*4
            return data[offset:offset+4]
        self.assertEqual(transform.call_count, 2*len(CHOICES['position_marker_style']))
        targets = {'ring': 45, 'ring_white': 45, 'glove': 60, 'pixel_hand': 56, 'reticle': 44}
        for index, (style, left, top, width, height) in enumerate(marker_style_tiles()):
            appearance = load_appearance(style)
            calls = transform.call_args_list[index*2:index*2+2]
            self.assertAlmostEqual(sum(call.args[1] for call in calls)/2, left+width/2)
            extent = max(max(x2-x1, y2-y1) for x1, y1, x2, y2 in
                         (appearance.preview_bounds(False), appearance.preview_bounds(True)))
            previous_right = None
            for call, pressed in zip(calls, (False, True)):
                center_x, center_y = call.args[1:]
                self.assertAlmostEqual(center_x, left+width*(.72 if pressed else .28))
                self.assertGreater(center_x, left)
                self.assertLess(center_x, left+width)
                self.assertEqual(center_y, top+height/2)
                self.assertEqual(call.kwargs, {'pressed': pressed})
                x, y, scale = settings_view.marker_preview_transform(appearance, center_x, center_y,
                                                                     pressed=pressed)
                x1, y1, x2, y2 = appearance.preview_bounds(pressed)
                self.assertAlmostEqual(x+(x1+x2)*scale/2, center_x)
                self.assertAlmostEqual(y+(y1+y2)*scale/2, center_y)
                self.assertGreaterEqual(x+x1*scale, left+8)
                self.assertLessEqual(x+x2*scale, left+width-8)
                self.assertGreaterEqual(y+y1*scale, top+8)
                self.assertLessEqual(y+y2*scale, top+height-8)
                if previous_right is not None:
                    self.assertLess(previous_right, x+x1*scale)
                previous_right = x+x2*scale
                self.assertAlmostEqual(scale, targets[style]/extent)
                # Check actual painted extents, excluding the card border
                # and selected stripe, rather than trusting transform math.
                background = pixel(left+20, top+20)
                points = [(px, py) for py in range(top+7, top+height-9)
                          for px in range(round(center_x)-48, round(center_x)+48)
                          if max(abs(pixel(px, py)[c]-background[c]) for c in (0, 1, 2)) >= 8]
                self.assertTrue(points, (style, pressed))
                px1, px2 = min(p[0] for p in points), max(p[0] for p in points)+1
                py1, py2 = min(p[1] for p in points), max(p[1] for p in points)+1
                self.assertAlmostEqual((px1+px2)/2, center_x, delta=1.5)
                self.assertAlmostEqual((py1+py2)/2, center_y, delta=1.5)
                self.assertAlmostEqual(px2-px1, (x2-x1)*scale, delta=3, msg=(style, pressed))
                self.assertAlmostEqual(py2-py1, (y2-y1)*scale, delta=3, msg=(style, pressed))
                if style == 'glove':
                    _, oy = appearance.origin
                    self.assertNotAlmostEqual(y+oy*scale, center_y)

    def test_artwork_preview_does_not_mislabel_ring_resource_fallback(self):
        settings_view._preview_appearance.cache_clear()
        self.addCleanup(settings_view._preview_appearance.cache_clear)
        with patch('armada_dual_screen_input.marker_appearance.load_appearance',
                   return_value=SimpleNamespace(style='ring')):
            for style in ('glove', 'pixel_hand', 'reticle'):
                self.assertIsNone(settings_view._preview_appearance(style, '#FFFFFF', '#FFFFFF'))

    def test_pixel_hand_previews_keep_nearest_sampling_while_other_styles_use_normal_sampling(self):
        draft = SettingsDraft({})
        draft.section = 'position'
        cr = Mock()
        def appearance(style, *_):
            kind = 'ring' if style.startswith('ring') else style
            return SimpleNamespace(style=kind, tile_size=64,
                preview_bounds=lambda pressed=False: (8, 8, 56, 56),
                sprite=lambda *_: object())
        with patch.object(settings_view, '_preview_appearance', side_effect=appearance), \
                patch.object(steam_style, 'label'), patch.object(steam_style, 'rounded'), \
                patch.object(steam_style, 'line'):
            settings_view.draw_marker_style_tiles(cr, draft, 398)
        self.assertEqual(cr.paint.call_count, 2*len(CHOICES['position_marker_style']))
        self.assertEqual(cr.get_source.return_value.set_filter.call_count, 2)
        for call in cr.get_source.return_value.set_filter.call_args_list:
            self.assertEqual(call.args, (cairo.FILTER_NEAREST,))

    def test_selected_icon_card_has_a_distinct_fill_and_accent_stripe(self):
        snapshots = {}
        for selected in CHOICES['position_marker_style']:
            image = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
            cr = cairo.Context(image)
            cr.set_source_rgb(*steam_style.BG)
            cr.paint()
            draft = SettingsDraft({'position_marker_style': selected})
            draft.section = 'position'
            settings_view.draw(cr, draft)
            image.flush()
            data, stride = bytes(image.get_data()), image.get_stride()
            def pixel(x, y):
                offset = y*stride+x*4
                return tuple(data[offset:offset+4])
            snapshots[selected] = {
                style: (pixel(left+20, top+20),
                        tuple(pixel(left+width//2, y) for y in range(top+height-7, top+height)))
                for style, left, top, width, height in marker_style_tiles()
            }
        def accent(pixel):
            return pixel[3] == 255 and all(abs(pixel[2-c]-round(steam_style.ACCENT[c]*255)) <= 1
                                          for c in (0, 1, 2))
        for style in CHOICES['position_marker_style']:
            active_fill, active_band = snapshots[style][style]
            self.assertTrue(any(accent(pixel) for pixel in active_band), style)
            for other in CHOICES['position_marker_style']:
                if other == style:
                    continue
                inactive_fill, inactive_band = snapshots[other][style]
                self.assertNotEqual(active_fill, inactive_fill, style)
                self.assertFalse(any(accent(pixel) for pixel in inactive_band), style)

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
