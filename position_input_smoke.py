#!/usr/bin/env python3
"""Bounded positioning-input check against this program's own upper window.

Requires idle Steam UI in touch mode 4. No game input, focus/root-property
writes, capture stream, persistent input device, or settings changes.
"""
from __future__ import annotations

import ctypes as c
import json
import os
from pathlib import Path
import time

from gamescope_focus import Cookie, UpperFocus
from panel_position import PanelPosition


def main():
    focus=UpperFocus(':0')
    initial=focus.snapshot()
    if initial.app_id!=769 or initial.graphics_app_id!=769 or initial.touch_mode!=4:
        raise SystemExit('Idle Steam UI with native touch passthrough required; no input sent')
    os.environ.update(GDK_BACKEND='x11',DISPLAY=':0',NO_AT_BRIDGE='1')
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0');gi.require_version('GdkX11','3.0')
    from gi.repository import Gdk,GLib,Gtk,GdkX11
    window=Gtk.Window(title='Armada positioning touch test — automatic close')
    window.set_decorated(False);window.fullscreen()
    area=Gtk.DrawingArea()
    area.add_events(Gdk.EventMask.TOUCH_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
    area.connect('draw',lambda _,cr:(cr.set_source_rgb(.06,.14,.18),cr.paint())[-1])
    window.add(area);window.realize()
    xid=GdkX11.X11Window.get_xid(window.get_window())
    focus.api.xcb_change_property_checked.restype=Cookie
    focus.api.xcb_change_property_checked.argtypes=[c.c_void_p,c.c_uint8,c.c_uint32,c.c_uint32,
                                                   c.c_uint32,c.c_uint8,c.c_uint32,c.c_void_p]
    focus.api.xcb_request_check.restype=c.c_void_p
    focus.api.xcb_request_check.argtypes=[c.c_void_p,Cookie]
    for name,value,kind in [('STEAM_GAME',769,6),('WM_TRANSIENT_FOR',initial.window,33)]:
        b=name.encode()
        reply=focus._reply('xcb_intern_atom_reply',focus.api.xcb_intern_atom(focus.connection,False,len(b),b))
        atom=c.c_uint32.from_address(reply+8).value;focus.libc.free(reply)
        data=c.c_uint32(value)
        cookie=focus.api.xcb_change_property_checked(focus.connection,0,xid,atom,kind,32,1,c.byref(data))
        error=focus.api.xcb_request_check(focus.connection,cookie)
        if error:focus.libc.free(error);raise RuntimeError('own test window setup failed')
    loop=GLib.MainLoop();p=PanelPosition()
    events=[];active=set();mouse_moves=[];nodes=[];markers=[]
    result={};state={'phase':'focus','at':time.monotonic(),'started':time.monotonic()}
    phases={Gdk.EventType.TOUCH_BEGIN:'begin',Gdk.EventType.TOUCH_UPDATE:'move',
            Gdk.EventType.TOUCH_END:'end',Gdk.EventType.TOUCH_CANCEL:'cancel'}

    def event(_,ev):
        phase=phases.get(ev.type)
        if phase:
            sequence=ev.get_event_sequence()
            if phase=='begin':active.add(sequence)
            elif phase in ('end','cancel'):active.discard(sequence)
            device=ev.get_source_device()
            events.append(dict(phase=phase,point=[round(ev.x),round(ev.y)],
                               source=device.get_source().value_nick if device else None))
        return True
    area.connect('touch-event',event)
    area.connect('motion-notify-event',lambda *_:mouse_moves.append(True) or True)

    def step():
        now=time.monotonic()
        try:
            if now-state['started']>9:raise RuntimeError('own-window positioning test timed out')
            current=focus.snapshot()
            if current.window!=xid or not current.input_in_surface:
                if state['phase'] in ('focus','arm'):return True
                raise RuntimeError('own test window lost focus; no further input')
            if not p.active and state['phase']=='focus':p.start();state['phase']='arm'
            if p.active:p.tick()
            phase=state['phase']
            if phase=='arm' and p.armed and p.expected.window==xid:
                nodes.append(Path(p.sender.node));markers.append(p.marker.process)
                result['surface_size']=[current.width,current.height]
                state.update(phase='warm',at=now)
            elif phase=='warm' and now-state['at']>.3:
                result['initial_mouse_moves']=len(mouse_moves)
                p.touch('begin',1,now,500,500)
                p.touch('move',1,now,624,500)
                state.update(phase='aim',at=now)
            elif phase=='aim' and now-state['at']>.5:
                result.update(aim_touch_events=len(events),aim_mouse_moves=len(mouse_moves),
                              aiming_native_sent=p.sender.native_events_sent)
                assert not events and len(mouse_moves)==result['initial_mouse_moves'] and p.sender.native_events_sent==0
                result['aim_has_no_touch_or_hover']=True
                p.touch('begin',2,now,1100,1000)
                state.update(phase='down',at=now)
            elif phase=='down' and now-state['at']>.15:
                p.touch('move',1,now,748,595.6)
                state.update(phase='drag',at=now)
            elif phase=='drag' and now-state['at']>.15:
                p.touch('end',2,now)
                state.update(phase='up',at=now)
            elif phase=='up' and now-state['at']>.15:
                p.touch('begin',3,now,20,1000)
                state.update(phase='held',at=now)
            elif phase=='held' and now-state['at']>.15:
                assert p.gesture.held
                p.stop();state.update(phase='closed',at=now)
            elif phase=='closed' and now-state['at']>.3:
                counts={phase:sum(e['phase']==phase for e in events) for phase in phases.values()}
                coordinates=all(any(e['phase']==phase and abs(e['point'][0]-u*current.width)<4
                                    and abs(e['point'][1]-v*current.height)<4 for e in events)
                                for phase,u,v in [('begin',.6,.5),('move',.7,.6),('end',.7,.6)])
                result.update(counts=counts,coordinates_match=coordinates,native_source=all(
                    e['source']=='touchscreen' for e in events),no_contacts_held=not active)
                result['passed']=(counts['begin']==counts['end']==2 and counts['move']>=1
                                  and counts['cancel']==0 and coordinates and not active
                                  and result['native_source'])
                loop.quit();return False
        except Exception as error:
            result.update(error=repr(error),phase=state['phase'],last_error=p.last_error,passed=False)
            loop.quit();return False
        return True

    window.show_all();GLib.timeout_add(20,step)
    try:loop.run()
    finally:
        p.stop();p.wait();window.destroy();focus.close()
        result.update(device_removed=all(not n.exists() for n in nodes),
                      marker_removed=all(child.poll() is not None for child in markers))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
