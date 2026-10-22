import sys
from types import SimpleNamespace
import unittest

from armada_dual_screen_input.keyboard_redraw import KeyboardRedraw, widget_rect


class DamageTests(unittest.TestCase):
    def layout(self):
        return SimpleNamespace(shift_active=False,caps_lock=False,rows=[[
            SimpleNamespace(code=30,x=10,y=500,w=80,h=80),
            SimpleNamespace(code=31,x=100,y=500,w=80,h=80)]])

    def test_old_and_new_highlights_are_both_invalidated(self):
        layout=self.layout(); damage=KeyboardRedraw()
        self.assertIsNone(damage.regions(layout,30))
        damage.remember(layout,30)
        self.assertEqual(damage.regions(layout,31),[(5,495,90,90),(95,495,90,90)])
        self.assertEqual(damage.regions(layout,None),[(5,495,90,90)])

    def test_modifiers_and_unknown_codes_request_full_redraw(self):
        layout=self.layout(); damage=KeyboardRedraw(); damage.remember(layout,None)
        layout.shift_active=True
        self.assertIsNone(damage.regions(layout,30))
        damage.remember(layout,None)
        self.assertIsNone(damage.regions(layout,777))
        self.assertEqual(damage.regions(layout,None),[])

    def test_scaling_rounds_outward_in_widget_coordinates(self):
        self.assertEqual(widget_rect((5.5,495.5,90,90),620,540),(2,247,46,46))

    def test_candidate_damage_cannot_hide_an_old_pressed_key(self):
        layout=self.layout(); damage=KeyboardRedraw(); damage.remember(layout,30)
        candidate_only=SimpleNamespace(in_clip=lambda x,y:y<500)
        damage.painted(layout,31,candidate_only)
        self.assertEqual(damage.regions(layout,31),[(5,495,90,90),(95,495,90,90)])
        full=SimpleNamespace(in_clip=lambda x,y:True)
        damage.painted(layout,31,full)
        self.assertEqual(damage.regions(layout,None),[(95,495,90,90)])


@unittest.skipUnless(sys.platform=='linux','Linux Pango/Cairo required')
class DamagePixels(unittest.TestCase):
    def test_touch_status_tick_only_invalidates_the_ribbon(self):
        from unittest.mock import Mock
        from armada_dual_screen_input import panel_app as panel
        app=panel.PanelApp.__new__(panel.PanelApp)
        app.mode='position'; app.collapsed=False
        app.drawing_area=SimpleNamespace(queue_draw=Mock(),queue_draw_area=Mock(),
            get_allocation=lambda:SimpleNamespace(width=620,height=540))
        app._queue_stats_draw()
        app.drawing_area.queue_draw.assert_not_called()
        self.assertEqual(app.drawing_area.queue_draw_area.call_args.args,(-3,37,626,28))
        app.collapsed=True
        app._queue_stats_draw()
        app.drawing_area.queue_draw.assert_called_once()

    def test_partial_status_repaint_matches_full_frame_after_values_change(self):
        import cairo
        from armada_dual_screen_input.panel_app import PanelApp
        from keyboard_layout import KeyboardLayout
        app=PanelApp.__new__(PanelApp)
        app.mode='split'; app.kb_layout=KeyboardLayout(0,500,1240,580)
        app.active_key_press=30; app.keyboard_redraw=KeyboardRedraw()
        app.pen_mode='off'; app.touch_mode='position'; app.held_ui_button=None; app.languages=None
        values={'bat_cap':100,'bat_watts':None,'cpu_load':1,'cpu_temp':31}
        app.stats=SimpleNamespace(get_stats=lambda:values)
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        def paint(target,partial=False):
            cr=cairo.Context(target)
            if partial: cr.rectangle(-5,75,1250,54); cr.clip()
            cr.set_source_rgb(0,0,0); cr.paint(); cr.translate(.4,1.2)
            app._draw_ui(cr)
        paint(surface)
        values.update(bat_cap=9,bat_watts=-5.1,cpu_load=100,cpu_temp=100,ram_used_gb=12.3)
        paint(surface,True)
        reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        paint(reference)
        self.assertEqual(bytes(surface.get_data()),bytes(reference.get_data()))

    def test_status_updates_during_typing_do_not_redraw_the_keyboard(self):
        from unittest.mock import Mock, patch
        from armada_dual_screen_input import panel_app as panel
        app=panel.PanelApp.__new__(panel.PanelApp)
        app.mode='split'; app.ui_hidden=app.collapsed=False
        app.held_key=None; app._last_keyboard_activity=99.9
        app.drawing_area=SimpleNamespace(queue_draw=Mock(),queue_draw_area=Mock(),
            get_allocation=lambda:SimpleNamespace(width=1240,height=1080))
        with patch.object(panel.time,'monotonic',return_value=100):
            app._queue_stats_draw()
        app.drawing_area.queue_draw.assert_not_called()
        x,y,w,h=app.drawing_area.queue_draw_area.call_args.args
        self.assertLessEqual(y+h,panel.upstream.HEADER_HEIGHT+6)
        self.assertGreaterEqual(y,panel.upstream.HEADER_BUTTONS_H-6)
        app.held_key=object(); app._last_keyboard_activity=0
        with patch.object(panel.time,'monotonic',return_value=100):
            app._queue_stats_draw()
        self.assertEqual(app.drawing_area.queue_draw_area.call_count,2)

    def test_quiet_keyboard_restores_full_status_and_orbital_repaint(self):
        from unittest.mock import Mock, patch
        from armada_dual_screen_input import panel_app as panel
        app=panel.PanelApp.__new__(panel.PanelApp)
        app.mode='split'; app.ui_hidden=app.collapsed=False
        app.held_key=None; app._last_keyboard_activity=99.7
        app.drawing_area=SimpleNamespace(queue_draw=Mock(),queue_draw_area=Mock())
        with patch.object(panel.time,'monotonic',return_value=100):
            app._queue_stats_draw()
        app.drawing_area.queue_draw.assert_called_once()
        app.mode='trackpad'; app._last_keyboard_activity=100
        with patch.object(panel.time,'monotonic',return_value=100):
            app._queue_stats_draw()
        self.assertEqual(app.drawing_area.queue_draw.call_count,2)
        app.drawing_area.queue_draw_area.assert_not_called()

    def test_candidate_overlay_partial_repaint_clears_back_to_trackpad(self):
        import cairo
        from armada_dual_screen_input.panel_app import PanelApp
        from keyboard_layout import KeyboardLayout
        app=PanelApp.__new__(PanelApp)
        app.mode='split'; app.kb_layout=KeyboardLayout(0,500,1240,580)
        app.active_key_press=None; app.keyboard_redraw=KeyboardRedraw()
        app.pen_mode='off'; app.touch_mode='position'; app.held_ui_button=None
        app.stats=SimpleNamespace(get_stats=lambda:{})
        app.languages=SimpleNamespace(language='zh_CN',ready=True,preedit='',candidates=[],
                                      page=0,message='中文全拼')
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        def paint(target,partial=False):
            cr=cairo.Context(target)
            if partial:
                cr.rectangle(-5,app._language_top()-5,1250,98); cr.clip()
            cr.set_source_rgb(0,0,0); cr.paint(); cr.translate(.4,1.2)
            app._draw_ui(cr)
        paint(surface)
        for preedit,candidates in (('nihao',['你好','拟好']),('n',['你','呢']),('',[])):
            app.languages.preedit=preedit; app.languages.candidates=candidates
            paint(surface,True)
            reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
            paint(reference)
            self.assertEqual(bytes(surface.get_data()),bytes(reference.get_data()))

    def test_keyboard_and_language_callbacks_request_only_their_areas(self):
        from unittest.mock import Mock, patch
        from armada_dual_screen_input import panel_app as panel
        from keyboard_layout import KeyboardLayout
        app=panel.PanelApp.__new__(panel.PanelApp)
        app._cleaned=False; app.mode='split'; app.ui_hidden=app.collapsed=False
        app.kb_layout=KeyboardLayout(0,500,1240,580); app.keyboard_redraw=KeyboardRedraw()
        app.active_key_press=30; app.keyboard_redraw.remember(app.kb_layout,None)
        app.drawing_area=SimpleNamespace(queue_draw=Mock(),queue_draw_area=Mock(),
            get_allocation=lambda:SimpleNamespace(width=1240,height=1080))
        with patch.object(panel.GLib,'idle_add',side_effect=lambda cb:cb()):
            app._queue_keyboard_draw()
        app.drawing_area.queue_draw.assert_not_called()
        self.assertEqual(app.drawing_area.queue_draw_area.call_count,1)
        app._queue_language_draw()
        x,y,w,h=app.drawing_area.queue_draw_area.call_args.args
        self.assertLess(y,app.kb_layout.y)
        self.assertLessEqual(y+h,app.kb_layout.y+6)
        app.kb_layout.shift_active=True
        with patch.object(panel.GLib,'idle_add',side_effect=lambda cb:cb()):
            app._queue_keyboard_draw()
        app.drawing_area.queue_draw.assert_called_once()

    def test_partial_origin_stays_consistent_until_full_repaint(self):
        import cairo
        from armada_dual_screen_input.panel_app import PanelApp
        app=PanelApp.__new__(PanelApp)
        app.burn_in=SimpleNamespace(get_orbital_offset=lambda now:(now,now/2))
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
        cr=cairo.Context(surface)
        self.assertEqual(app._paint_orbital_offset(cr,1),(1,.5))
        cr.rectangle(5,495,90,90); cr.clip()
        self.assertEqual(app._paint_orbital_offset(cr,2),(1,.5))
        cr.reset_clip()
        self.assertEqual(app._paint_orbital_offset(cr,3),(3,1.5))

    def test_partial_keyboard_matches_full_repaint_without_ghosts(self):
        import cairo
        from armada_dual_screen_input import steam_keys, steam_style
        # A pure geometry import; no window, GTK main loop or input device.
        from pathlib import Path
        import importlib.util
        path=Path(__file__).resolve().parent.parent/'vendor/ratatoskr/bin/keyboard_layout.py'
        spec=importlib.util.spec_from_file_location('damage_layout',path)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for scale,offset in ((1,0),(.55,.3),(1,1.2)):
            with self.subTest(scale=scale,offset=offset):
                layout=module.KeyboardLayout(0,500,1240,580)
                app=SimpleNamespace(kb_layout=layout,active_key_press=None,languages=None)
                damage=KeyboardRedraw()
                surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
                def paint(target,regions=None):
                    cr=cairo.Context(target); cr.scale(scale,scale)
                    if regions is not None:
                        for x,y,w,h in regions: cr.rectangle(x,y,w,h)
                        cr.clip()
                    cr.set_source_rgb(*steam_style.BG); cr.paint()
                    cr.translate(offset,offset); steam_keys.draw_keyboard(app,cr)
                paint(surface); damage.remember(layout,None)
                for code in (30,31,frozenset((30,31)),frozenset((31,)),None,42,30,None):
                    app.key_feedback=SimpleNamespace(visible=code) if isinstance(code,frozenset) else None
                    app.active_key_press=code if isinstance(code,int) else None
                    if code==42: layout.shift_active=True
                    regions=damage.regions(layout,code)
                    paint(surface,regions); damage.remember(layout,code)
                    reference=cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
                    paint(reference)
                    self.assertEqual(bytes(surface.get_data()),bytes(reference.get_data()))
