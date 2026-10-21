#!/usr/bin/env python3
"""Opt-in lower-window render comparison. No input devices or upper injection.

Temporarily covers the lower panel with its own non-focusable test keyboard.
Compares full redraw and bounded keycap damage on the actual Wayland target.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from keyboard_latency_bench import summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-own-window-test',action='store_true',required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--defer-status-during-typing',action='store_true')
    parser.add_argument('--short-taps',action='store_true',help='Compare sub-frame touch highlight coverage')
    args=parser.parse_args()
    if sys.platform!='linux': parser.error('Linux GTK required')
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
    os.environ.update(GDK_BACKEND='wayland',WAYLAND_DISPLAY='armada-plasma-bottom',NO_AT_BRIDGE='1')
    with tempfile.TemporaryDirectory(prefix='ads-render-bench-') as temp,patch.dict(os.environ,{'XDG_STATE_HOME':temp}):
        from armada_dual_screen_input import panel_app as panel
        from armada_dual_screen_input.keyboard_redraw import KeyboardRedraw
        from armada_dual_screen_input.key_feedback import KeyFeedback
        from keyboard_layout import KeyboardLayout
        from burn_in import BurnInProtector
        Gtk,Gdk,GLib,Layer=panel.Gtk,panel.Gdk,panel.GLib,panel.GtkLayerShell
        display=Gdk.Display.get_default()
        if display is None or not Layer.is_supported(): raise SystemExit('Lower layer-shell session unavailable')
        screen=display.get_default_screen()
        names=[screen.get_monitor_plug_name(i) for i in range(display.get_n_monitors())]
        index=panel.choose_bottom_monitor(names,panel.MODE_GAMEMODE)
        if index is None: raise SystemExit('No known lower output; no window opened')
        window=Gtk.Window(title='Keyboard render timing — automatic close')
        window.set_accept_focus(False); window.set_focus_on_map(False)
        Layer.init_for_window(window); Layer.set_monitor(window,display.get_monitor(index))
        Layer.set_layer(window,Layer.Layer.OVERLAY); Layer.set_keyboard_mode(window,Layer.KeyboardMode.NONE)
        Layer.set_exclusive_zone(window,0)
        for edge in (Layer.Edge.TOP,Layer.Edge.BOTTOM,Layer.Edge.LEFT,Layer.Edge.RIGHT): Layer.set_anchor(window,edge,True)
        area=Gtk.DrawingArea(); window.add(area)
        area.add_events(Gdk.EventMask.TOUCH_MASK)
        area.connect('touch-event',lambda *args:True)
        app=panel.PanelApp.__new__(panel.PanelApp)
        app._cleaned=False; app.collapsed=False; app.ui_hidden=False
        app.mode='split'; app.session_mode='game'; app.languages=None
        app.kb_layout=KeyboardLayout(0,500,1240,580); app.keyboard_redraw=KeyboardRedraw()
        app._install_language_key()
        app.active_key_press=None; app.pen_mode='off'; app.touch_mode='position'; app.held_ui_button=None
        app.stats=SimpleNamespace(get_stats=lambda:{})
        app.drawing_area=area; app.show_debug_hud=False
        app.frame_count=0; app.last_fps_calc=time.time(); app.fps=0
        app.burn_in=BurnInProtector(idle_floor=1)
        loop=GLib.MainLoop(); state={'phase':0,'step':0,'error':None,'last':time.perf_counter()}
        records=[{'mode':name,'draw':[],'heartbeat':[],'partial_draw':[],'full_draw':[]}
                 for name in (('live-state','visible-feedback') if args.short_taps else
                              ('english-full','english-keycap','ime-full','ime-candidate'))]
        seen=[set() for _ in records]; trials=[{} for _ in records]; current_taps={}
        sources=[]
        def draw(_,cr):
            try:
                allocation=area.get_allocation()
                cr.scale(allocation.width/1240,allocation.height/1080)
                clip=cr.clip_extents(); partial=clip!=(0.,0.,1240.,1080.)
                began=time.perf_counter(); app._paint(cr)
                if args.short_taps:
                    visible=app._visible_key_codes()
                    codes=set() if visible is None else {visible} if isinstance(visible,int) else visible
                    for key in (key for row in app.kb_layout.rows for key in row if key.code in codes):
                        if all(cr.in_clip(x,y) for x in (key.x,key.x+key.w) for y in (key.y,key.y+key.h)):
                            if key.code in current_taps: seen[state['phase']].add(current_taps[key.code])
                elapsed=(time.perf_counter()-began)*1000
                record=records[state['phase']]; record['draw'].append(elapsed)
                record['partial_draw' if partial else 'full_draw'].append(elapsed)
            except Exception as error:
                state['error']=str(error); loop.quit()
            return True
        area.connect('draw',draw)
        def short_event(index,code,down):
            if down: current_taps[code]=index
            app.active_key_press=code if down else None
            app._queue_keyboard_draw()
            return False
        def short_phase():
            for i in range(70):
                duration=(0,2,5,8,12,20,40)[i%7]; code=(30,31,32,33,36,37,38)[(i//7+i)%7]
                trials[state['phase']][i]=duration
                if duration==0:
                    def coalesced(index=i,key=code):
                        short_event(index,key,True); short_event(index,key,False)
                        return False
                    sources.append(GLib.timeout_add(100+i*100,coalesced))
                else:
                    sources.append(GLib.timeout_add(100+i*100,short_event,i,code,True))
                    sources.append(GLib.timeout_add(100+i*100+duration,short_event,i,code,False))
        def tick():
            state['step']+=1
            # Alternating key press/release at 8 keys per second.
            if state['phase']<2:
                app.active_key_press=30 if state['step']%2 else None
                if state['phase']==0: area.queue_draw()
                else: app._queue_keyboard_draw()
            else:
                app.languages.preedit=('n','ni','nih','niha','nihao','')[state['step']%6]
                app.languages.candidates=['你','呢','泥','拟','逆','尼'] if app.languages.preedit else []
                if state['phase']==2: area.queue_draw()
                else: app._queue_language_draw()
            return True
        def heartbeat():
            now=time.perf_counter(); records[state['phase']]['heartbeat'].append(max(0,(now-state['last'])*1000-5))
            state['last']=now; return True
        def phase():
            if args.short_taps:
                if state['phase']==0:
                    state['phase']=1; current_taps.clear(); app.active_key_press=None
                    app.key_feedback=KeyFeedback(GLib.timeout_add,GLib.source_remove,app._invalidate_keyboard)
                    area.queue_draw(); short_phase(); return True
                loop.quit(); return False
            if state['phase']<3:
                state['phase']+=1; state['step']=0; app.active_key_press=None
                if state['phase']==2:
                    app.languages=SimpleNamespace(language='zh_CN',ready=True,preedit='',
                        candidates=[],page=0,message='中文全拼')
                area.queue_draw(); return True
            loop.quit(); return False
        def status():
            if args.defer_status_during_typing: app._queue_stats_draw()
            else: area.queue_draw()
            return True
        try:
            window.show_all()
            sources=[GLib.timeout_add(5,heartbeat),GLib.timeout_add(7300 if args.short_taps else 6000,phase),
                     GLib.timeout_add(1000,status)]
            if args.short_taps: short_phase()
            else: sources.append(GLib.timeout_add(62,tick))
            loop.run()
        finally:
            app._cleaned=True
            if getattr(app,'key_feedback',None) is not None: app.key_feedback.close()
            for source in sources:
                if GLib.MainContext.default().find_source_by_id(source): GLib.source_remove(source)
            window.destroy()
    result={'scope':'own-lower-wayland-window-no-input','error':state['error'],
            'defer_status_during_typing':args.defer_status_during_typing,
            'cases':[{key:summary(value) if isinstance(value,list) else value for key,value in record.items()} for record in records]}
    result['passed']=not result['error'] and all(c['draw']['count']>=30 for c in result['cases'])
    if args.short_taps:
        for i,record in enumerate(result['cases']):
            record['highlighted_taps']=len(seen[i]); record['planned_taps']=len(trials[i])
            record['by_duration_ms']={'coalesced' if ms==0 else str(ms):{'shown':sum(1 for tap,duration in trials[i].items()
                if duration==ms and tap in seen[i]),'planned':sum(1 for duration in trials[i].values() if duration==ms)}
                for ms in (0,2,5,8,12,20,40)}
        result['passed']=result['passed'] and len(seen[1])==len(trials[1])==70
    encoded=json.dumps(result,indent=2)
    if args.output: args.output.write_text(encoded+'\n')
    print(encoded)
    return 0 if result['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
