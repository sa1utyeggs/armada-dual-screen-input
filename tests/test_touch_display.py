"""Passive visualization follows contact snapshots without affecting input."""
from types import SimpleNamespace as NS
import sys
import unittest
from unittest.mock import Mock, patch

from armada_dual_screen_input.touch_display import TouchDisplay, bounds, input_region
from armada_dual_screen_input.toolkit_touch import ToolkitTouch


class TouchDisplayTests(unittest.TestCase):
    def region(self, mode='trackpad', **kwargs):
        return input_region(mode, header=124, split=500, width=1240, height=1080, **kwargs)

    def test_disabled_has_no_work(self):
        display=TouchDisplay()
        self.assertEqual(display.sync([NS(tid=1,x=200,y=200)], {1:'trackpad'},
                                      self.region(), enabled=False), [])
        self.assertFalse(display.points)
        display.draw(Mock(spec=[]))

    def test_multitouch_motion_and_lift_erase_old_bounds(self):
        display=TouchDisplay()
        one,two=NS(tid=1,x=200,y=250),NS(tid=2,x=500,y=400)
        owners={1:'trackpad',2:'trackpad'}
        self.assertCountEqual(display.sync([one,two],owners,self.region(),enabled=True),
                              [bounds((200,250)),bounds((500,400))])
        one.x=240
        self.assertEqual(display.sync([one,two],owners,self.region(),enabled=True),
                         [bounds((200,250)),bounds((240,250))])
        self.assertEqual(display.sync([one],owners,self.region(),enabled=True),[bounds((500,400))])
        self.assertEqual(display.clear(),[bounds((240,250))])
        self.assertFalse(display.points)
        self.assertEqual(display.clear(),[])

    def test_header_keyboard_candidate_and_control_regions_are_excluded(self):
        display=TouchDisplay()
        contacts=[NS(tid=i,x=400,y=y) for i,y in enumerate((40,100,300,450,600,300,300))]
        owners=dict(enumerate(('header','status','trackpad','trackpad','keyboard',
                               'languagebar','touch_selector')))
        display.sync(contacts,owners,self.region('split',candidate_top=412),enabled=True)
        self.assertEqual(display.points,{2:(400,300)})
        for mode in ('preferences','keyboard','settings'):
            self.assertIsNone(self.region(mode))
        for option in ('hidden','collapsed','menu_open'):
            self.assertIsNone(self.region(**{option:True}))
        self.assertEqual(self.region('split'),(0,124,1240,376))
        self.assertEqual(self.region('position'),(0,124,1240,956))

    def test_mode_change_and_invalid_contacts_leave_no_markers(self):
        display=TouchDisplay()
        one=NS(tid=1,x=100,y=300)
        display.sync([one],{1:'position'},self.region('position'),enabled=True)
        self.assertEqual(display.sync([one],{1:'position'},None,enabled=True),[bounds((100,300))])
        for x,y in ((-1,300),(100,0),(1240,300),(100,1080),(float('nan'),300)):
            one.x,one.y=x,y
            self.assertEqual(display.sync([one],{1:'position'},self.region('position'),enabled=True),[])

    def test_observation_does_not_change_native_lifecycle_or_coordinates(self):
        events=[]
        touch=ToolkitTouch(lambda *a:events.append(('down',a)),lambda *a:events.append(('move',a)),
                           lambda *a:events.append(('up',a)),lambda *a:events.append(('cancel',a)),
                           clock=lambda:1.,viewport_width=620,viewport_height=540)
        display=TouchDisplay()
        touch.begin('first',100,150)
        before=touch.active
        display.sync(before,{1:'trackpad'},self.region(),enabled=True)
        self.assertEqual(touch.active,before)
        self.assertEqual(display.points,{1:(200,300)})
        touch.update('first',120,160)
        touch.end('first')
        display.sync(touch.active,{},self.region(),enabled=True)
        self.assertFalse(display.points)
        self.assertEqual([event[0] for event in events],['down','move','up'])


@unittest.skipUnless(sys.platform=='linux','Pixel and callback checks require Linux Cairo/GTK')
class TouchDisplayIntegrationTests(unittest.TestCase):
    def test_pixels_clip_to_input_surface_and_erase_cleanly(self):
        import cairo
        display=TouchDisplay()
        display.sync([NS(tid=1,x=300,y=480)],{1:'trackpad'},(0,124,1240,376),enabled=True)
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        display.draw(cairo.Context(surface))
        data=bytes(surface.get_data());stride=surface.get_stride()
        self.assertTrue(any(data[450*stride:500*stride]))
        self.assertFalse(any(data[500*stride:]))
        x,y,w,h=bounds((300,480))
        for row in range(1080):
            if row<y or row>=y+h:
                self.assertFalse(any(data[row*stride:(row+1)*stride]))
        display.clear()
        blank=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        display.draw(cairo.Context(blank))
        self.assertFalse(any(bytes(blank.get_data())))

    def test_panel_callbacks_queue_small_damage_and_clean_on_cancel(self):
        import test_panel_touch_recovery as fixture
        case=fixture.PanelTouchRecoveryTests('test_new_wayland_group_recovers_pointer_after_a_missing_end')
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.app.input_cfg={'touch_display_mode':True}
        case.app.touch_display=TouchDisplay()
        damage=[]
        case.app.drawing_area=NS(get_allocation=lambda:NS(width=1240,height=1080),
                                 queue_draw_area=lambda *r:damage.append(r),queue_draw=lambda:None)
        with patch.object(case.panel.GLib,'timeout_add',side_effect=AssertionError('No visual timer')):
            case.event('BEGIN','first',x=300,y=300,initial=True)
            case.event('BEGIN','second',x=500,y=300)
            self.assertEqual(len(case.app.touch_display.points),2)
            case.event('UPDATE','first',x=330,y=320)
            case.event('END','second')
            self.assertEqual(len(case.app.touch_display.points),1)
            case.event('CANCEL','first')
        self.assertFalse(case.app.touch_display.points)
        self.assertTrue(damage)
        self.assertTrue(all(w<110 and h<140 for _,_,w,h in damage))
