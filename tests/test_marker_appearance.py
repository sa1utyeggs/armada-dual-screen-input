"""Marker style policy and approved runtime assets, without devices or windows."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from armada_dual_screen_input.marker_appearance import (
    POSITION_STYLES, RING_PRESETS, MarkerAppearance, load_appearance, read_position_style,
    RETICLE_COLORS,
)
from armada_dual_screen_input.marker_colors import DEFAULT_COLORS, MarkerColors


class MarkerAppearancePolicyTests(unittest.TestCase):
    def test_only_supported_style_values_survive_preference_validation(self):
        self.assertEqual(set(POSITION_STYLES),
                         {'ring', 'ring_white', 'glove', 'pixel_hand', 'reticle'})
        self.assertEqual(tuple(POSITION_STYLES), ('ring', 'ring_white', 'glove', 'pixel_hand', 'reticle'))
        for value in POSITION_STYLES:
            self.assertEqual(read_position_style(value), value)
        for value in (None, True, False, 1, [], {}, 'GLOVE', 'hand', 'glove\n', '../glove'):
            with self.subTest(value=value):
                self.assertEqual(read_position_style(value), 'ring')

    def test_superseded_single_hue_ring_choices_migrate_to_the_default_pair(self):
        for old_style in ('ring_blue', 'ring_green'):
            self.assertEqual(read_position_style(old_style), 'ring')

    def test_runtime_pair_uses_matching_small_rgba_canvases(self):
        for style in ('glove', 'pixel_hand'):
            root = Path(__file__).resolve().parents[1] / 'assets' / 'markers' / style
            self.assertEqual({p.name for p in root.glob('*.png')}, {'idle.png', 'pressed.png'})
            for name in ('idle.png', 'pressed.png'):
                with self.subTest(style=style, pose=name):
                    data = (root / name).read_bytes()
                    self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(data[12:16], b'IHDR')
                    width, height, depth, color = struct.unpack('>IIBB', data[16:26])
                    self.assertEqual((width, height), (64, 64))
                    self.assertEqual((depth, color), (8, 6))

    def test_direct_and_legacy_contacts_do_not_inherit_positioning_gloves(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            appearance = MarkerAppearance(style)
            self.assertIs(appearance.for_mode('position'), appearance)
            for mode in ('direct', 'legacy'):
                with self.subTest(style=style, mode=mode):
                    ring = appearance.for_mode(mode)
                    self.assertEqual(ring.style, 'ring')
                    self.assertEqual(ring.colors, RING_PRESETS['ring'])
        # The origin belongs to the pair, rather than to a particular pose.
        self.assertEqual(MarkerAppearance('glove').origin, (19, 11))
        self.assertEqual(MarkerAppearance('pixel_hand').origin, (15, 5))
        self.assertEqual(MarkerAppearance('reticle').origin, (32, 32))

    def test_each_ring_choice_owns_both_states_and_applies_to_direct_contacts(self):
        expected = {
            'ring': ('#59D9FF', '#FFA626'),
            'ring_white': ('#FFFFFF', '#58E38B'),
        }
        self.assertEqual(set(RING_PRESETS), set(expected))
        for style, pair in expected.items():
            with self.subTest(style=style):
                appearance = load_appearance(style)
                self.assertEqual(appearance.style, 'ring')
                self.assertEqual((appearance.colors.idle, appearance.colors.pressed), pair)
                self.assertIs(appearance.for_mode('position'), appearance)
                self.assertIs(appearance.for_mode('direct'), appearance)
                self.assertIs(appearance.for_mode('legacy'), appearance)

    def test_default_preserves_historical_rgb_and_both_pairs_change_color_clearly(self):
        self.assertEqual(RING_PRESETS['ring'], DEFAULT_COLORS)
        self.assertEqual(RING_PRESETS['ring'].idle_rgba, (.35, .85, 1., 1.))
        self.assertEqual(RING_PRESETS['ring'].pressed_rgba, (1., .65, .15, 1.))
        for colors in RING_PRESETS.values():
            # A state change changes chroma substantially, not just a tiny shade adjustment.
            self.assertGreater(max(abs(a-b) for a, b in
                                   zip(colors.idle_rgba[:3], colors.pressed_rgba[:3])), .5)

    def test_presentation_bounds_do_not_replace_the_input_hotspot(self):
        ring = load_appearance('ring')
        glove = MarkerAppearance('glove')
        for pressed in (False, True):
            self.assertEqual(ring.preview_bounds(pressed), (3, 3, 33, 33))
        self.assertEqual(glove.preview_bounds(False), (14, 9, 61, 62))
        self.assertEqual(glove.preview_bounds(True), (14, 17, 61, 62))
        self.assertEqual(ring.origin, (18, 18))
        self.assertEqual(glove.origin, (19, 11))
        reticle = MarkerAppearance('reticle')
        self.assertEqual(reticle.preview_bounds(False), (3, 3, 61, 61))
        self.assertEqual(reticle.preview_bounds(True), (9, 9, 55, 55))
        self.assertEqual(reticle.origin, (32, 32))
        pixel = MarkerAppearance('pixel_hand')
        self.assertEqual(pixel.preview_bounds(False), (8, 3, 56, 61))
        self.assertEqual(pixel.preview_bounds(True), (8, 8, 56, 61))

    def test_legacy_separate_colors_cannot_override_selected_ring_preset(self):
        legacy = MarkerColors('#FF0000', '#0000FF')
        for style in RING_PRESETS:
            with self.subTest(style=style):
                self.assertEqual(load_appearance(style, legacy).colors, RING_PRESETS[style])


class MarkerArtworkFallbackTests(unittest.TestCase):
    def setUp(self):
        load_appearance.cache_clear()
        self.addCleanup(load_appearance.cache_clear)

    def test_missing_malformed_or_undecodable_optional_artwork_uses_rings_at_startup(self):
        class PNGError(Exception):
            pass
        fake_cairo = SimpleNamespace(Error=PNGError)
        for style, source in (('glove', '_glove_source'), ('pixel_hand', '_pixel_hand_source')):
            for error in (OSError('missing'), ValueError('wrong dimensions'), PNGError('bad PNG')):
                with self.subTest(style=style, error=type(error).__name__):
                    load_appearance.cache_clear()
                    with patch.dict('sys.modules', {'cairo': fake_cairo}), \
                         patch('armada_dual_screen_input.marker_appearance.'+source, side_effect=error):
                        appearance = load_appearance(style)
                    self.assertEqual(appearance.style, 'ring')
                    self.assertEqual(appearance.colors, RING_PRESETS['ring'])

    def test_missing_pressed_pose_cannot_leave_a_half_valid_glove_pair(self):
        for style, source_name in (('glove', '_glove_source'), ('pixel_hand', '_pixel_hand_source')):
            with self.subTest(style=style), \
                 patch.dict('sys.modules', {'cairo': SimpleNamespace(Error=Exception)}), \
                 patch('armada_dual_screen_input.marker_appearance.'+source_name,
                       side_effect=[object(), ValueError('pressed pose missing')]) as source:
                self.assertEqual(load_appearance(style).style, 'ring')
            self.assertEqual([call.args for call in source.call_args_list], [(False,), (True,)])

    def test_ring_selection_never_decodes_optional_glove_files(self):
        with patch('armada_dual_screen_input.marker_appearance._glove_source') as glove, \
             patch('armada_dual_screen_input.marker_appearance._pixel_hand_source') as pixel:
            for style in ('ring', 'ring_white', 'reticle'):
                load_appearance(style)
        glove.assert_not_called()
        pixel.assert_not_called()

    def test_unexpected_programming_error_is_not_hidden_as_an_artwork_fallback(self):
        class PNGError(Exception):
            pass
        with patch.dict('sys.modules', {'cairo': SimpleNamespace(Error=PNGError)}), \
             patch('armada_dual_screen_input.marker_appearance._glove_source',
                   side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                load_appearance('glove')

    def test_selected_glove_uses_default_blue_orange_rings_for_direct_mode(self):
        legacy = MarkerColors('#FF0000', '#0000FF')
        with patch.dict('sys.modules', {'cairo': SimpleNamespace(Error=Exception)}), \
             patch('armada_dual_screen_input.marker_appearance._glove_source', return_value=object()):
            appearance = load_appearance('glove', legacy)
        self.assertEqual(appearance.style, 'glove')
        self.assertEqual(appearance.colors, RING_PRESETS['ring'])
        self.assertIs(appearance.for_mode('position'), appearance)
        for mode in ('direct', 'legacy'):
            ring = appearance.for_mode(mode)
            self.assertEqual(ring.style, 'ring')
            self.assertEqual(ring.colors, RING_PRESETS['ring'])


@unittest.skipUnless(sys.platform == 'linux', 'Glove sprite pixels require Linux Cairo runtime')
class MarkerAppearancePixelTests(unittest.TestCase):
    def test_preview_bounds_cover_each_visible_pose_without_changing_its_hotspot(self):
        for style in POSITION_STYLES:
            appearance = load_appearance(style)
            self.assertEqual(appearance.style, style if style in ('glove', 'pixel_hand', 'reticle') else 'ring')
            origin = appearance.origin
            for pressed in (False, True):
                with self.subTest(style=style, pressed=pressed):
                    sprite = appearance.sprite(pressed, 0, 0)
                    sprite.flush()
                    width = sprite.get_width()
                    alpha = bytes(sprite.get_data())[3::4]
                    visible = [(i % width, i // width) for i, value in enumerate(alpha) if value > 15]
                    bounds = (min(x for x, _ in visible), min(y for _, y in visible),
                              max(x for x, _ in visible)+1, max(y for _, y in visible)+1)
                    self.assertEqual(appearance.preview_bounds(pressed), bounds)
                    self.assertEqual(appearance.origin, origin)

    def test_ring_presets_render_their_own_two_colors_with_transparent_centers(self):
        from armada_dual_screen_input.marker_gpu import rgba_pixels
        for style, colors in RING_PRESETS.items():
            appearance = load_appearance(style)
            for pressed, rgb in ((False, colors.idle_rgba), (True, colors.pressed_rgba)):
                with self.subTest(style=style, pressed=pressed):
                    sprite = appearance.sprite(pressed, 0, 0)
                    sprite.flush()
                    pixels = bytes(rgba_pixels(sprite.get_data()))
                    origin = appearance.origin
                    center = (origin[1]*sprite.get_width()+origin[0])*4
                    self.assertEqual(pixels[center:center+4], b'\0'*4)
                    expected = tuple(round(channel*255) for channel in rgb[:3])
                    self.assertTrue(any(pixels[i+3] == 255 and all(
                        abs(pixels[i+c]-expected[c]) <= 1 for c in range(3))
                        for i in range(0, len(pixels), 4)))

    def test_glove_states_share_one_hotspot_and_direct_mode_keeps_rings(self):
        from armada_dual_screen_input.marker_appearance import load_appearance
        appearance = load_appearance('glove')
        self.assertEqual(appearance.style, 'glove')
        self.assertEqual(appearance.tile_size, 64)
        self.assertEqual(len(appearance.origin), 2)
        self.assertTrue(all(type(n) is int and 0 <= n < 64 for n in appearance.origin))
        self.assertIs(appearance.for_mode('position'), appearance)
        for mode in ('direct', 'legacy'):
            self.assertEqual(appearance.for_mode(mode).style, 'ring')
        idle, pressed = (appearance.sprite(state, 0, 0) for state in (False, True))
        self.assertEqual((idle.get_width(), idle.get_height()), (64, 64))
        self.assertEqual((pressed.get_width(), pressed.get_height()), (64, 64))
        self.assertNotEqual(bytes(idle.get_data()), bytes(pressed.get_data()))
        for sprite in (idle, pressed):
            sprite.flush()
            pixels = bytes(sprite.get_data())
            alpha = pixels[3::4]
            self.assertEqual(min(alpha), 0)
            self.assertEqual(max(alpha), 255)
            self.assertTrue(any(0 < value < 255 for value in alpha))

    def test_all_subpixel_poses_are_prepared_before_the_render_loop_needs_them(self):
        from armada_dual_screen_input import marker_appearance as sprites
        appearances = [load_appearance(style) for style in ('glove', 'pixel_hand', 'reticle')]
        self.assertEqual([appearance.style for appearance in appearances], ['glove', 'pixel_hand', 'reticle'])
        for appearance in appearances:
            sprites.prepare_sprites(appearance)
        with patch('armada_dual_screen_input.marker_appearance._glove_source',
                   side_effect=AssertionError('render loop attempted glove PNG decode')), \
             patch('armada_dual_screen_input.marker_appearance._pixel_hand_source',
                   side_effect=AssertionError('render loop attempted pixel PNG decode')), \
             patch('cairo.Context', side_effect=AssertionError('render loop attempted rasterization')), \
             patch('cairo.ImageSurface', side_effect=AssertionError('render loop allocated a sprite')):
            for appearance in appearances:
                for pressed in (False, True):
                    for phase_y in range(8):
                        for phase_x in range(8):
                            sprite = appearance.sprite(pressed, phase_x, phase_y)
                            self.assertEqual((sprite.get_width(), sprite.get_height()), (64, 64))
        for cache in (sprites._glove_sprite, sprites._pixel_hand_sprite, sprites._reticle_sprite):
            self.assertLessEqual(cache.cache_info().currsize, 128)
        self.assertLessEqual(sprites._glove_source.cache_info().currsize, 2)
        self.assertLessEqual(sprites._pixel_hand_source.cache_info().currsize, 2)

    def test_pixel_hand_two_poses_keep_one_hotspot_and_never_change_direct_touch_geometry(self):
        appearance = load_appearance('pixel_hand')
        self.assertEqual(appearance.style, 'pixel_hand')
        self.assertEqual(appearance.tile_size, 64)
        origin = appearance.origin
        self.assertEqual(len(origin), 2)
        self.assertTrue(all(type(n) is int and 0 <= n < 64 for n in origin))
        idle, pressed = (appearance.sprite(state, 0, 0) for state in (False, True))
        self.assertNotEqual(bytes(idle.get_data()), bytes(pressed.get_data()))
        self.assertEqual(appearance.origin, origin)
        for state in (False, True):
            for phase_y in range(8):
                for phase_x in range(8):
                    sprite = appearance.sprite(state, phase_x, phase_y)
                    self.assertEqual(set(bytes(sprite.get_data())[3::4]), {0, 255})
        for mode in ('direct', 'legacy'):
            self.assertEqual(appearance.for_mode(mode), load_appearance('ring'))

    def test_reticle_states_change_geometry_color_and_center_coverage_without_moving_hotspot(self):
        from armada_dual_screen_input.marker_gpu import rgba_pixels
        appearance = load_appearance('reticle')
        self.assertEqual(appearance.style, 'reticle')
        self.assertEqual(appearance.origin, (32, 32))
        states = []
        for pressed, color in ((False, RETICLE_COLORS.idle_rgba), (True, RETICLE_COLORS.pressed_rgba)):
            sprite = appearance.sprite(pressed, 0, 0)
            sprite.flush()
            pixels = bytes(rgba_pixels(sprite.get_data()))
            states.append(pixels)
            center = (32*64+32)*4
            expected = tuple(round(c*255) for c in color[:3])
            if pressed:
                self.assertEqual(pixels[center:center+4], b'\0'*4)
            else:
                self.assertTrue(all(abs(pixels[center+c]-expected[c]) <= 1 for c in range(3)))
                self.assertEqual(pixels[center+3], 255)
            self.assertTrue(any(pixels[i+3] == 255 and all(abs(pixels[i+c]-expected[c]) <= 1
                for c in range(3)) for i in range(0, len(pixels), 4)))
            alpha = pixels[3::4]
            # Cairo quantizes half-pixel stroke coverage differently at top
            # and bottom edges (e.g. alpha 119/136 on 1.18.6). Geometry is
            # checked through the visible contour used by previews and the
            # near-opaque core, rather than byte-identical antialias fringes.
            for threshold in (15, 239):
                contour = {(i % 64, i // 64) for i, value in enumerate(alpha) if value > threshold}
                self.assertEqual(contour, {(63-x, y) for x, y in contour})
                self.assertEqual(contour, {(x, 63-y) for x, y in contour})
            # Edge-coverage rounding must not displace the perceived center
            # by even one half of the renderer's 1/8-pixel positioning step.
            total_alpha = sum(alpha)
            self.assertAlmostEqual(sum((i % 64+.5)*value for i, value in enumerate(alpha))/total_alpha,
                                   32, delta=1/16)
            self.assertAlmostEqual(sum((i // 64+.5)*value for i, value in enumerate(alpha))/total_alpha,
                                   32, delta=1/16)
            outer, arm = (18, 9) if pressed else (24, 12)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    for dx, dy in ((sx*outer, sy*outer), (sx*outer, sy*(outer-arm)),
                                   (sx*(outer-arm), sy*outer)):
                        offset = ((32+dy)*64+32+dx)*4
                        self.assertEqual(pixels[offset+3], 255)
                        self.assertTrue(all(abs(pixels[offset+c]-expected[c]) <= 1 for c in range(3)))
            for phase_y in range(8):
                for phase_x in range(8):
                    phase = appearance.sprite(pressed, phase_x, phase_y)
                    alpha = bytes(phase.get_data())[3::4]
                    self.assertTrue(all(alpha[y*64+x] == 0 for x, y in
                        (*((n, 0) for n in range(64)), *((n, 63) for n in range(64)),
                         *((0, n) for n in range(64)), *((63, n) for n in range(64)))))
                    if pressed:
                        self.assertEqual(alpha[32*64+32], 0)
        self.assertNotEqual(states[0], states[1])
        idle_bounds, pressed_bounds = appearance.preview_bounds(False), appearance.preview_bounds(True)
        self.assertLess(pressed_bounds[2]-pressed_bounds[0], idle_bounds[2]-idle_bounds[0])


if __name__ == '__main__':
    unittest.main()
