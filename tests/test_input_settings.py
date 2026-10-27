"""Preference validation, persistence failures and touch editing without input."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from armada_dual_screen_input.input_settings import (
    DEFAULTS, NUMBERS, CHOICES, SECTIONS, SettingsDraft, read_settings, write_settings, position_preview_top,
    marker_style_tiles, row_height,
    settings_tabs, GENERAL_TOUCH_DISPLAY_TOP, GENERAL_UPDATE_BUTTON_TOP, GENERAL_UNINSTALL_BUTTON_TOP,
)
from armada_dual_screen_input.marker_colors import COLOR_SETTINGS


class InputSettingsTests(unittest.TestCase):
    def test_missing_values_keep_existing_behavior_defaults(self):
        self.assertEqual(read_settings({}), DEFAULTS)
        self.assertEqual(DEFAULTS["sensitivity"], 1.5)
        self.assertEqual(DEFAULTS["position_sensitivity"], 2.)
        self.assertTrue(DEFAULTS["keyboard_repeat_enabled"])
        self.assertFalse(DEFAULTS['touch_display_mode'])
        self.assertEqual(DEFAULTS['position_marker_style'], 'ring')

    def test_position_icon_style_is_strict_and_draft_edits_are_reversible(self):
        styles = ('ring', 'ring_white', 'glove', 'pixel_hand', 'reticle')
        self.assertEqual(tuple(CHOICES['position_marker_style']), styles)
        self.assertNotIn('ring_blue', CHOICES['position_marker_style'])
        self.assertNotIn('ring_green', CHOICES['position_marker_style'])
        for style in styles:
            self.assertEqual(read_settings({'position_marker_style': style})['position_marker_style'], style)
        for invalid in (None, {}, [], True, 1, 'Glove', 'glove ', 'ring_red', 'unknown'):
            self.assertEqual(read_settings({'position_marker_style': invalid})['position_marker_style'], 'ring')
        draft = SettingsDraft({'position_marker_style': 'glove', 'marker_frame_rate': '60',
                               'marker_idle_color': '#FFFFFF', 'scroll_scale': .001})
        draft.change('position_marker_style', 'ring')
        self.assertTrue(draft.dirty)
        self.assertEqual(draft.saved['position_marker_style'], 'glove')
        draft.discard()
        self.assertEqual(draft.values['position_marker_style'], 'glove')
        self.assertFalse(draft.dirty)
        draft.change('position_marker_style', {})
        self.assertEqual(draft.values['position_marker_style'], 'ring')
        draft.section = 'position'
        draft.reset_section()
        self.assertEqual(draft.values['position_marker_style'], 'ring')
        self.assertEqual(draft.values['marker_frame_rate'], 'auto')
        self.assertEqual(draft.values['marker_idle_color'], '#FFFFFF')
        self.assertEqual(draft.values['scroll_scale'], .001)

    def test_position_icon_style_round_trip_preserves_ring_colors_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = {'mode': 'position', 'touch_mode': 'direct', 'scroll_scale': .001,
                        'marker_idle_color': '#B494FF', 'marker_pressed_color': '#FFFFFF',
                        'future': {'keep': True}}
            path.write_text(json.dumps(original))
            draft = SettingsDraft(original)
            draft.change('position_marker_style', 'glove')
            write_settings(path, read_settings(draft.values))
            draft.mark_saved()
            saved = json.loads(path.read_text())
            for key, value in original.items():
                self.assertEqual(saved[key], value)
            self.assertEqual(saved['position_marker_style'], 'glove')
            self.assertEqual(SettingsDraft(saved).values['position_marker_style'], 'glove')
            self.assertFalse(draft.dirty)

    def test_position_icon_cards_have_direct_hits_and_leave_header_and_gaps_inert(self):
        draft = SettingsDraft({})
        draft.section = 'position'
        for style in CHOICES['position_marker_style']:
            draft.change('position_marker_style', style)
            self.assertEqual(draft.rows(), [('position_sensitivity', 300),
                                            ('position_marker_style', 398), ('marker_frame_rate', 566)])
            self.assertEqual(position_preview_top(draft), 668)
            self.assertEqual(row_height('position_marker_style'), 156)
            for key in ('position_sensitivity', 'marker_frame_rate'):
                self.assertEqual(row_height(key), 88)
            tiles = marker_style_tiles()
            self.assertEqual(tiles, (('ring', 44, 448, 220, 92),
                                     ('ring_white', 276, 448, 220, 92),
                                     ('glove', 508, 448, 220, 92),
                                     ('pixel_hand', 740, 448, 220, 92),
                                     ('reticle', 972, 448, 220, 92)))
            self.assertEqual(tuple(tile[0] for tile in tiles), tuple(CHOICES['position_marker_style']))
            for selected, left, top, width, height in tiles:
                for x in (left, left+width/2, left+width):
                    for y in (top, top+height/2, top+height):
                        self.assertEqual(draft.hit(x, y), ('marker_style', selected))
                self.assertLess(top+height, dict(draft.rows())['marker_frame_rate'])
            self.assertLess(398+row_height('position_marker_style'), 566)
            self.assertEqual(draft.hit(1000, 610), ('choice', 'marker_frame_rate'))
            for x, y in ((1000, 420), (620, 442), (620, 447), (43, 494),
                         (270, 494), (502, 494), (734, 494), (966, 494),
                         (1193, 494), (1000, 541), (1000, 555), (680, 736)):
                self.assertEqual(draft.hit(x, y), (None, None))

    def test_direct_style_selection_is_idempotent_and_retains_save_discard_reset_semantics(self):
        draft = SettingsDraft({'position_marker_style': 'ring_white', 'marker_frame_rate': '60'})
        draft.section = 'position'
        for style in ('reticle', 'pixel_hand', 'glove', 'ring', 'ring_white', 'reticle'):
            left, top, width, height = next(tile[1:] for tile in marker_style_tiles() if tile[0] == style)
            action, selected = draft.hit(left+width/2, top+height/2)
            self.assertEqual(action, 'marker_style')
            draft.change('position_marker_style', selected)
            self.assertEqual(draft.values['position_marker_style'], style)
            before, dirty = dict(draft.values), draft.dirty
            draft.change('position_marker_style', selected)
            self.assertEqual(draft.values, before)
            self.assertEqual(draft.dirty, dirty)
            self.assertEqual(draft.saved['position_marker_style'], 'ring_white')
        draft.discard()
        self.assertEqual(draft.values['position_marker_style'], 'ring_white')
        self.assertFalse(draft.dirty)
        draft.change('position_marker_style', 'glove')
        draft.mark_saved()
        self.assertEqual(draft.saved['position_marker_style'], 'glove')
        self.assertFalse(draft.dirty)
        draft.reset_section()
        self.assertEqual(draft.values['position_marker_style'], 'ring')
        self.assertEqual(draft.values['marker_frame_rate'], 'auto')

    def test_touch_display_is_opt_in_and_preserves_other_preferences(self):
        for invalid in ('true',1,None,{}):
            self.assertFalse(read_settings({'touch_display_mode':invalid})['touch_display_mode'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            original={'scroll_scale':.001,'mode':'position','future':{'keep':True}}
            write_settings(path,original)
            write_settings(path,{'touch_display_mode':True})
            saved=json.loads(path.read_text())
            self.assertEqual(saved,{**original,'touch_display_mode':True})
            self.assertTrue(read_settings(saved)['touch_display_mode'])

    def test_invalid_and_nonfinite_numbers_never_reach_input(self):
        for key, spec in NUMBERS.items():
            for value in (None, {}, [], True, "bad", float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    self.assertEqual(read_settings({key: value})[key], spec.default)
            self.assertEqual(read_settings({key: -999})[key],
                             spec.default if key == "scroll_scale" else spec.low)
            self.assertEqual(read_settings({key: 99999})[key], spec.high)

    def test_booleans_are_strict_and_unknown_config_is_not_an_input_option(self):
        for key in ("glide", "tap_to_click", "keyboard_repeat_enabled"):
            self.assertFalse(read_settings({key: False})[key])
            self.assertTrue(read_settings({key: "false"})[key])
        self.assertNotIn("unrelated", read_settings({"unrelated": 1}))

    def test_small_legacy_wheel_scale_survives_editing_another_preference(self):
        draft = SettingsDraft({"scroll_scale": .001})
        draft.change("sensitivity", 2.)
        self.assertEqual(read_settings(draft.values)["scroll_scale"], .001)

    def test_marker_frame_rate_choices_are_strict_and_reset_only_touch_preferences(self):
        for rate in ('auto','120','60','30'):
            self.assertEqual(read_settings({'marker_frame_rate':rate})['marker_frame_rate'],rate)
        for rate in (None,{},[],True,120,'240','bad'):
            self.assertEqual(read_settings({'marker_frame_rate':rate})['marker_frame_rate'],'auto')
        draft=SettingsDraft({'marker_frame_rate':'30','scroll_scale':.001})
        draft.change('marker_frame_rate','120');draft.discard()
        self.assertEqual(draft.values['marker_frame_rate'],'30')
        draft.section='position';draft.reset_section()
        self.assertEqual(draft.values['marker_frame_rate'],'auto')
        self.assertEqual(draft.values['scroll_scale'],.001)

    def test_follow_screen_caption_uses_upper_monitor_when_available(self):
        from armada_dual_screen_input.input_settings import choice_caption
        self.assertEqual(choice_caption('marker_frame_rate','auto',119930),'Follow display (120 Hz)')
        self.assertEqual(choice_caption('marker_frame_rate','auto',0),'Follow display')
        self.assertEqual(choice_caption('marker_frame_rate','60',119930),'60 FPS')

    def test_marker_colors_validate_old_configs_and_preserve_independent_states(self):
        for key, default in COLOR_SETTINGS.items():
            for invalid in (None, True, 0, [], {}, 'blue', '#FFF', '#FFFFFF00', '#gg1122', '#123456\n'):
                self.assertEqual(read_settings({key: invalid})[key], default)
            self.assertEqual(read_settings({key:'#ab12cd'})[key], '#AB12CD')
        draft=SettingsDraft({'marker_idle_color':'#FFFFFF', 'scroll_scale':.001})
        draft.change('marker_pressed_color','#58e38b')
        self.assertEqual(draft.values['marker_idle_color'],'#FFFFFF')
        self.assertTrue(draft.dirty)
        draft.discard()
        self.assertEqual(draft.values['marker_pressed_color'],DEFAULTS['marker_pressed_color'])
        draft.section='position';draft.reset_section()
        self.assertEqual(draft.values['marker_idle_color'],'#FFFFFF')
        self.assertEqual(draft.values['scroll_scale'],.001)

    def test_legacy_ring_colors_are_preserved_without_editable_rows(self):
        original = {'marker_idle_color': '#B494FF', 'marker_pressed_color': '#FFFFFF'}
        draft = SettingsDraft(original)
        draft.section = 'position'
        for style in CHOICES['position_marker_style']:
            draft.change('position_marker_style', style)
            self.assertTrue(set(COLOR_SETTINGS).isdisjoint(dict(draft.rows())))
            for key, value in original.items():
                self.assertEqual(draft.values[key], value)
        draft.discard()
        for key, value in original.items():
            self.assertEqual(draft.values[key], value)
        draft.reset_section()
        for key, value in original.items():
            self.assertEqual(draft.values[key], value)

    def test_colors_round_trip_with_unknown_configuration_and_other_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            write_settings(path,{'mode':'position','future':{'keep':True},'marker_frame_rate':'60'})
            draft=SettingsDraft(json.loads(path.read_text()))
            draft.change('marker_idle_color','#B494FF');draft.change('marker_pressed_color','#FFFFFF')
            write_settings(path,read_settings(draft.values))
            saved=json.loads(path.read_text())
            self.assertEqual(saved['marker_idle_color'],'#B494FF')
            self.assertEqual(saved['marker_pressed_color'],'#FFFFFF')
            self.assertEqual(saved['marker_frame_rate'],'60')
            self.assertEqual(saved['future'],{'keep':True})
            self.assertEqual(saved['mode'],'position')

    def test_opening_and_editing_draft_does_not_change_saved_values(self):
        draft = SettingsDraft({"scroll_scale": .25})
        draft.change("sensitivity", 2.3)
        draft.change("keyboard_repeat_enabled", False)
        self.assertTrue(draft.dirty)
        self.assertEqual(draft.saved["sensitivity"], 1.5)
        draft.discard()
        self.assertFalse(draft.dirty)
        self.assertEqual(draft.values["scroll_scale"], .25)

    def test_restoring_defaults_only_changes_selected_section(self):
        draft = SettingsDraft({"sensitivity": 2.3, "position_sensitivity": 3.,
                               "keyboard_repeat_interval_ms": 80})
        draft.section = "mouse"
        draft.reset_section()
        self.assertEqual(draft.values["sensitivity"], 1.5)
        self.assertEqual(draft.values["position_sensitivity"], 3.)
        self.assertEqual(draft.values["keyboard_repeat_interval_ms"], 80)
        self.assertTrue(draft.dirty)

    def test_slider_clamps_to_range_and_stepper_values_do_not_accumulate_noise(self):
        draft = SettingsDraft({})
        for key, spec in NUMBERS.items():
            draft.slide(key, -1)
            self.assertEqual(draft.values[key], spec.low)
            draft.slide(key, 2000)
            self.assertLessEqual(draft.values[key], spec.high)
        for _ in range(7):
            draft.change("sensitivity", draft.values["sensitivity"] - .1)
        self.assertEqual(draft.values["sensitivity"], 4.3)

    def test_controls_have_separate_hit_regions_and_all_fit_lower_screen(self):
        draft = SettingsDraft({})
        for section in SECTIONS:
            draft.section = section
            for key, top in draft.rows():
                self.assertGreaterEqual(top, 300)
                self.assertLess(top + row_height(key), 996 if section=='general' else 934)
                if key == 'position_marker_style':
                    style, left, card_top, width, height = marker_style_tiles()[0]
                    self.assertEqual(draft.hit(left+width/2, card_top+height/2), ('marker_style', style))
                    continue
                expected = "slider" if key in NUMBERS else "choice" if key in CHOICES else "toggle"
                self.assertEqual(draft.hit(800 if key in NUMBERS else 1000, top + 50),
                                 (expected, key))
            self.assertEqual(draft.hit(1100, 1020), ("save", None))
            self.assertEqual(draft.hit(30, 120), (None, None))
        for section, left, width in settings_tabs():
            self.assertEqual(draft.hit(left + width/2, 250), ('section', section))
            self.assertLessEqual(left + width, 1216)
        draft.section = 'general'
        self.assertEqual(draft.hit(200, GENERAL_UPDATE_BUTTON_TOP+20), ('update_left', None))
        self.assertEqual(draft.hit(900, GENERAL_UPDATE_BUTTON_TOP+20), ('install_update', None))
        self.assertEqual(draft.hit(200, GENERAL_UNINSTALL_BUTTON_TOP+20), ('uninstall_left', None))
        self.assertEqual(draft.hit(900, GENERAL_UNINSTALL_BUTTON_TOP+20), ('uninstall_confirm', None))
        self.assertEqual(draft.hit(900, GENERAL_TOUCH_DISPLAY_TOP+40), ('toggle','touch_display_mode'))
        self.assertGreater(GENERAL_TOUCH_DISPLAY_TOP, GENERAL_UNINSTALL_BUTTON_TOP+52)

    def test_save_merges_unknown_fields_and_preserves_previous_input_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thor-panel/config.json"
            write_settings(path, {"mode": "position", "future": {"keep": True}, "scroll_scale": .25})
            write_settings(path, {"sensitivity": 2.3, "keyboard_repeat_enabled": False})
            result = json.loads(path.read_text())
            self.assertEqual(result["future"], {"keep": True})
            self.assertEqual(result["mode"], "position")
            self.assertEqual(result["scroll_scale"], .25)
            self.assertEqual(result["sensitivity"], 2.3)
            self.assertFalse(result["keyboard_repeat_enabled"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_atomic_replace_keeps_old_bytes_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            original = b'{"keep":true}\n'
            path.write_bytes(original)
            with patch("armada_dual_screen_input.input_settings.os.replace", side_effect=OSError("full")):
                with self.assertRaises(OSError):
                    write_settings(path, {"sensitivity": 2.})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_malformed_existing_config_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for original in (b'{broken', b'[]', b'null'):
                path.write_bytes(original)
                with self.assertRaises(ValueError):
                    write_settings(path, DEFAULTS)
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
