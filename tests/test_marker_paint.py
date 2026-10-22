"""Bounded damage and offscreen pixels, with no windows/input devices."""
import sys
import unittest

from armada_dual_screen_input.marker_paint import MarkerScene, draw_rings


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


@unittest.skipUnless(sys.platform=='linux','Offscreen Cairo checks require Linux runtime')
class MarkerPixelTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
