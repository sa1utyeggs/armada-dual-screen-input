from dataclasses import replace
import json
import unittest

from armada_dual_screen_input.gamescope_focus import FocusSnapshot
from armada_dual_screen_input.marker_target import MarkerTarget


class MarkerTargetTests(unittest.TestCase):
    def setUp(self):
        self.focus = FocusSnapshot(10,42,42,1280,720,123,':1',11,True,1,37,-12)

    def test_binding_round_trip_keeps_verified_surface_and_scaled_geometry(self):
        target=MarkerTarget.from_focus(self.focus)
        self.assertEqual(MarkerTarget.decode(target.encode()),target)
        self.assertEqual((target.width,target.height),(1280,720))
        self.assertEqual((target.x,target.y),(37,-12))
        self.assertTrue(target.matches_focus(replace(self.focus,input_window=12)))
        self.assertTrue(target.matches_focus(replace(self.focus,touch_mode=4)))

    def test_new_surface_application_display_server_or_size_requires_new_binding(self):
        target=MarkerTarget.from_focus(self.focus)
        for change in ({'window':20},{'app_id':43,'graphics_app_id':43},
                       {'surface_display':':0'},{'server_pid':124},
                       {'width':1920,'height':1080},{'x':0},{'y':0}):
            with self.subTest(change=change):
                self.assertFalse(target.matches_focus(replace(self.focus,**change)))

    def test_overlay_unverified_input_and_unsupported_touch_policy_are_rejected(self):
        for change in ({'graphics_app_id':43},{'input_in_surface':False},{'touch_mode':0},
                       {'window':0},{'window':1},{'app_id':0,'graphics_app_id':0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                MarkerTarget.from_focus(replace(self.focus,**change))

    def test_worker_payload_rejects_unknown_fields_remote_displays_and_invalid_numbers(self):
        values=json.loads(MarkerTarget.from_focus(self.focus).encode())
        cases=[dict(values,extra=1),dict(values,surface_display='host:0'),
               dict(values,surface_display=':0\n'),dict(values,width=8193),
               dict(values,window=True),dict(values,server_pid=-1),dict(values,app_id='42'),
               dict(values,x=32768),dict(values,y=True)]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):
                MarkerTarget.decode(json.dumps(case))
        for payload in ('[]','null','x'*1025):
            with self.assertRaises(ValueError):MarkerTarget.decode(payload)

    def test_decoration_leaves_fps_and_steam_interactive_overlay_slots_unclaimed(self):
        properties={name:(value,kind) for name,value,kind in MarkerTarget.from_focus(self.focus).properties()}
        self.assertNotIn('GAMESCOPE_EXTERNAL_OVERLAY',properties)
        self.assertNotIn('STEAM_OVERLAY',properties)
        self.assertEqual(properties['STEAM_GAME'],(42,6))
        self.assertEqual(properties['WM_TRANSIENT_FOR'],(10,33))
        self.assertEqual(properties['_WINE_HWND_EXSTYLE'][0]&0x80020,0x80020)
        self.assertEqual(properties['_WINE_HWND_STYLE'][0]&0x08000000,0x08000000)
