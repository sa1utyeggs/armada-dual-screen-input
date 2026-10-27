"""Bounded damage and offscreen pixels, with no windows/input devices."""
import sys
import unittest

from armada_dual_screen_input.marker_paint import MarkerScene, draw_rings
from armada_dual_screen_input.marker_appearance import MarkerAppearance


class MarkerSceneTests(unittest.TestCase):
    def test_repeated_position_does_not_schedule_extra_damage(self):
        scene=MarkerScene((320,180))
        self.assertTrue(scene.update(((.5,.5,False),)))
        scene.take_damage()
        self.assertFalse(scene.update(((.5,.5,False),)))
        self.assertFalse(scene.damage)
        self.assertTrue(scene.update(((.5,.5,True),)))
        self.assertTrue(scene.damage)

    def test_lifting_all_contacts_still_clears_old_bounds(self):
        scene=MarkerScene((320,180))
        scene.update(((.2,.3,True),(.8,.7,True)))
        before=set(scene.take_damage())
        self.assertTrue(scene.update(()))
        self.assertEqual(set(scene.take_damage()),before)
        self.assertFalse(scene.rings)

    def test_unpainted_changes_accumulate_bounded_damage_and_clip_edges(self):
        scene=MarkerScene((320,180))
        for n in range(1000):
            scene.update(((n/999,n/999,False),))
            self.assertLessEqual(len(scene.damage),64)
        for x,y,w,h in scene.damage:
            self.assertTrue(0 <= x < x+w <= 320)
            self.assertTrue(0 <= y < y+h <= 180)

    def test_reexpose_and_full_map_do_not_change_scene(self):
        scene=MarkerScene((320,180))
        scene.update(((.5,.5,False),))
        scene.take_damage()
        scene.invalidate()
        self.assertTrue(scene.damage)
        scene.invalidate(full=True)
        self.assertEqual(scene.take_damage(),((0,0,320,180),))
        self.assertEqual(scene.rings,((.5,.5,False),))

    def test_stationary_style_switch_damages_old_ring_and_complete_position_sprite_extents(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style):
                scene = MarkerScene((201, 161))
                rings = ((.5, .5, False),)
                scene.update(rings)
                old_ring = set(scene.take_damage())
                appearance = MarkerAppearance(style)
                self.assertTrue(scene.update(rings, appearance))
                rectangles = set(scene.take_damage())
                self.assertTrue(old_ring <= rectangles)
                ox, oy = appearance.origin
                left, top = 100-ox, 80-oy
                self.assertTrue(any(x <= left and y <= top and x+w >= left+64 and y+h >= top+64
                                    for x, y, w, h in rectangles))
                self.assertFalse(scene.update(rings, appearance))
                self.assertEqual(scene.take_damage(), ())
                self.assertTrue(scene.update(rings, MarkerAppearance('ring')))
                self.assertEqual(set(scene.take_damage()), rectangles)

    def test_position_press_switch_and_lift_clear_old_pose_even_without_position_change(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style):
                scene = MarkerScene((201, 121), MarkerAppearance(style))
                scene.update(((.5, .5, False),))
                visible = scene.take_damage()
                self.assertTrue(scene.update(((.5, .5, True),)))
                self.assertEqual(scene.take_damage(), visible)
                self.assertTrue(scene.update(()))
                self.assertEqual(scene.take_damage(), visible)

    def test_position_bounds_clip_at_all_corners_without_moving_touch_points(self):
        for style in ('glove', 'pixel_hand', 'reticle'):
            with self.subTest(style=style):
                scene = MarkerScene((80, 80), MarkerAppearance(style))
                rings = ((0., 0., False), (1., 0., True), (0., 1., False), (1., 1., True))
                scene.update(rings)
                rectangles = scene.take_damage()
                self.assertEqual(scene.rings, rings)
                self.assertEqual(len(rectangles), 4)
                for x, y, width, height in rectangles:
                    self.assertTrue(0 <= x < x+width <= 80)
                    self.assertTrue(0 <= y < y+height <= 80)


@unittest.skipUnless(sys.platform=='linux','Offscreen Cairo checks require Linux runtime')
class MarkerPixelTests(unittest.TestCase):
    def vector_reference(self, cr, rings, canvas, colors):
        import cairo, math
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0,0,0,0);cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        for u,v,pressed in rings:
            for width,color in ((5,(0,0,0,.85)),
                                (2.5,colors.pressed_rgba if pressed else colors.idle_rgba)):
                cr.set_line_width(width);cr.set_source_rgba(*color)
                cr.new_sub_path();cr.arc(u*(canvas[0]-1),v*(canvas[1]-1),12,0,math.tau);cr.stroke()

    def test_cached_subpixel_phases_match_vector_strokes_for_both_colors(self):
        import cairo
        from armada_dual_screen_input.marker_colors import MarkerColors
        colors=MarkerColors('#FF0000','#00FF00');canvas=(96,96)
        for pressed in (False,True):
            for x in range(8):
                for y in range(8):
                    rings=(((40+x/8)/95,(40+y/8)/95,pressed),)
                    actual=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
                    reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
                    draw_rings(cairo.Context(actual),rings,canvas,colors)
                    self.vector_reference(cairo.Context(reference),rings,canvas,colors)
                    self.assert_pixels_match(actual,reference)

    def test_scaled_and_transformed_contexts_retain_original_vector_pixels(self):
        import cairo
        from armada_dual_screen_input.marker_colors import DEFAULT_COLORS
        canvas=(96,96);rings=((.301,.529,False),(.8,.6,True))
        for scale,translate in ((2,False),(1,True)):
            actual=cairo.ImageSurface(cairo.FORMAT_ARGB32,96*scale,96*scale)
            reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,96*scale,96*scale)
            actual.set_device_scale(scale,scale);reference.set_device_scale(scale,scale)
            a,b=cairo.Context(actual),cairo.Context(reference)
            if translate:a.translate(1,2);b.translate(1,2)
            draw_rings(a,rings,canvas)
            self.vector_reference(b,rings,canvas,DEFAULT_COLORS)
            self.assert_pixels_match(actual,reference)

    def test_ring_appearance_colors_are_consistent_in_cached_and_scaled_paths(self):
        import cairo
        from armada_dual_screen_input.marker_colors import MarkerColors
        colors = MarkerColors('#FF0000', '#00FF00')
        appearance = MarkerAppearance('ring', colors)
        canvas = (96, 48)
        rings = ((.25, .5, False), (.75, .5, True))
        for scale in (1, 2):
            actual = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas[0]*scale, canvas[1]*scale)
            reference = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas[0]*scale, canvas[1]*scale)
            actual.set_device_scale(scale, scale)
            reference.set_device_scale(scale, scale)
            draw_rings(cairo.Context(actual), rings, canvas, appearance=appearance)
            draw_rings(cairo.Context(reference), rings, canvas, colors)
            self.assert_pixels_match(actual, reference)

    def test_cache_is_bounded_when_colors_change(self):
        from armada_dual_screen_input.marker_paint import _ring_sprite
        _ring_sprite.cache_clear()
        for n in range(160):_ring_sprite((n/160,0.,0.,1.),0,0)
        self.assertLessEqual(_ring_sprite.cache_info().currsize,128)
        _ring_sprite.cache_clear()

    def test_selected_colors_apply_independently_without_filling_the_center(self):
        import cairo
        from armada_dual_screen_input.marker_colors import MarkerColors
        colors=MarkerColors('#FF0000','#00FF00')
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,192,96)
        draw_rings(cairo.Context(surface),((.25,.5,False),(.75,.5,True)),(192,96),colors)
        surface.flush();pixels=bytes(surface.get_data());stride=surface.get_stride()
        for u,channel in ((.25,2),(.75,1)):
            cx=round(u*191);cy=round(.5*95)
            self.assertEqual(pixels[cy*stride+cx*4+3],0)
            ring=[pixels[y*stride+x*4:y*stride+x*4+4]
                  for y in range(cy-16,cy+17) for x in range(cx-16,cx+17)]
            self.assertTrue(any(p[channel]>200 and p[3]>200 and all(p[c]<10 for c in (0,1,2) if c!=channel) for p in ring))
            self.assertTrue(any(p[3]>150 and max(p[:3])<10 for p in ring))

    def assert_pixels_match(self,actual,reference):
        a,b=bytes(actual.get_data()),bytes(reference.get_data())
        # Cairo's clipped/full rasterization differed by 1 alpha unit at one
        # edge pixel on Thor. Transparent pixels must still clear exactly.
        self.assertLessEqual(max(abs(x-y) for x,y in zip(a,b)),1)
        self.assertTrue(all(a[i:i+4]==b'\0'*4 for i in range(0,len(b),4) if b[i+3]==0))

    def test_partial_frames_match_full_scene_across_moves_lifts_and_edges(self):
        import cairo
        canvas=(320,180)
        for scale in (1,2):
            actual=cairo.ImageSurface(cairo.FORMAT_ARGB32,canvas[0]*scale,canvas[1]*scale)
            actual.set_device_scale(scale,scale)
            scene=MarkerScene(canvas)
            groups=((((.2,.3,False),),),
                    (((.4,.3,True),),((.5,.4,True),(.9,.1,True))),
                    (((0,0,False),(1,1,True)),),
                    ((),),
                    tuple(((n/99,.5,bool(n%2)),) for n in range(100)))
            for group in groups:
                for rings in group:scene.update(rings)
                cr=cairo.Context(actual)
                for rect in scene.take_damage():cr.rectangle(*rect)
                cr.clip();draw_rings(cr,scene.rings,canvas)
                reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,canvas[0]*scale,canvas[1]*scale)
                reference.set_device_scale(scale,scale)
                draw_rings(cairo.Context(reference),scene.rings,canvas)
                self.assert_pixels_match(actual,reference)

    def test_position_style_partial_pixels_match_full_frames_across_poses_modes_edges_and_clear(self):
        import cairo
        from armada_dual_screen_input.marker_appearance import load_appearance
        appearances = [load_appearance(style) for style in ('glove', 'pixel_hand', 'reticle')]
        self.assertEqual([appearance.style for appearance in appearances], ['glove', 'pixel_hand', 'reticle'])
        canvas = (192, 128)
        # Switch the entire shape at a fixed coordinate before checking
        # motion, contact changes and fallback back to direct-touch rings.
        frames = [(((.25, .3, False),), appearance) for appearance in appearances]
        for appearance in appearances:
            frames.extend((
                (((.25, .3, False),), appearance),
                (((.25, .3, True),), appearance),
                (((.25, .3, True),), appearance.for_mode('direct')),
                (((0., 0., False), (1., 1., True)), appearance),
                (((1., 0., True), (0., 1., False)), appearance),
                (((.45, .55, True), (.46, .56, False)), appearance),
                ((), appearance),
            ))
            frames.extend(((((.2+step/1000, .5, bool(step % 2)),), appearance)
                          for step in range(40)))
            frames.append(((), appearance))
        for scale in (1, 2):
            scene = MarkerScene(canvas)
            actual = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas[0]*scale, canvas[1]*scale)
            actual.set_device_scale(scale, scale)
            for rings, appearance in frames:
                scene.update(rings, appearance)
                cr = cairo.Context(actual)
                for rectangle in scene.take_damage():
                    cr.rectangle(*rectangle)
                cr.clip()
                draw_rings(cr, scene.rings, canvas, appearance=scene.appearance)
                reference = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas[0]*scale, canvas[1]*scale)
                reference.set_device_scale(scale, scale)
                draw_rings(cairo.Context(reference), rings, canvas, appearance=appearance)
                self.assert_pixels_match(actual, reference)

    def test_unrelated_partial_expose_does_not_forget_old_visible_ring(self):
        import cairo
        canvas=(320,180);scene=MarkerScene(canvas)
        actual=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
        scene.update(((.2,.3,False),));draw_rings(cairo.Context(actual),scene.rings,canvas)
        scene.take_damage()
        scene.update(((.5,.5,True),))
        cr=cairo.Context(actual);cr.rectangle(280,0,20,20);cr.clip()
        draw_rings(cr,scene.rings,canvas)
        scene.update(((.8,.7,False),))
        cr=cairo.Context(actual)
        for rect in scene.take_damage():cr.rectangle(*rect)
        cr.clip();draw_rings(cr,scene.rings,canvas)
        reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
        draw_rings(cairo.Context(reference),scene.rings,canvas)
        self.assert_pixels_match(actual,reference)

    def test_rings_retain_open_transparent_center_and_distinct_press_color(self):
        import cairo
        colors=[]
        for pressed in (False,True):
            surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,128,128)
            draw_rings(cairo.Context(surface),((.5,.5,pressed),),(128,128))
            pixels=bytes(surface.get_data())
            self.assertEqual(pixels[(63*128+63)*4+3],0)
            self.assertEqual(pixels[:4],b'\0'*4)
            colors.append(any(pixels[i+3]>100 and (pixels[i+2]>pixels[i] if pressed else pixels[i]>pixels[i+2])
                              for i in range(0,len(pixels),4)))
        self.assertEqual(colors,[True,True])

    def test_smoothed_subpixel_frames_clear_old_pixels_through_contact_changes(self):
        import cairo
        from armada_dual_screen_input.marker_motion import MarkerMotion
        from armada_dual_screen_input.marker_sample import decode_sample, sample_payload
        canvas=(320,180);scene=MarkerScene(canvas);motion=MarkerMotion(canvas)
        actual=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
        for frame in range(180):
            now=frame/120
            if frame < 120:
                rings=((.25+frame/1000,.3,True),(.75-frame/1000,.7,True))
                ids=(10,20)
            elif frame < 150:
                rings=((.37,.3,True),);ids=(10,)
            else:rings=();ids=()
            if frame % 2 == 0 or frame in (120,150):
                motion.accept(decode_sample(sample_payload(rings,dict(ids=ids,mode='direct',active=bool(ids),
                    sampled_at=now,snap=frame in (120,150)))),now)
            scene.update(motion.sample(now))
            cr=cairo.Context(actual)
            for rectangle in scene.take_damage():cr.rectangle(*rectangle)
            cr.clip();draw_rings(cr,scene.rings,canvas)
            reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,*canvas)
            draw_rings(cairo.Context(reference),scene.rings,canvas)
            self.assert_pixels_match(actual,reference)


if __name__=='__main__':unittest.main()
