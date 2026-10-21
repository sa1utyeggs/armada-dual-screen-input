#!/usr/bin/env python3
"""Measure real GLib input timing with offscreen panel drawing and fake devices.

Default: no window, input device, Steam connection or personal config is created.
--run-own-window-test additionally checks delivery into this helper's own upper
GTK input field. It requires idle Steam and stops if that window loses focus.
Neither mode measures the physical digitizer or display scanout.
Run on Linux with GTK dependencies: python3 -B tools/keyboard_latency_bench.py.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


def summary(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), **{name: round(values[round((len(values)-1)*p)], 3)
                                   for name, p in (('p50_ms', .5), ('p95_ms', .95),
                                                   ('p99_ms', .99), ('max_ms', 1))}}


def own_window():
    """Initialize X11 before importing the lower Wayland panel's GTK adapter."""
    import ctypes as c
    from armada_dual_screen_input.gamescope_focus import Cookie, UpperFocus
    focus = UpperFocus(':0'); initial = focus.snapshot()
    if initial.app_id != 769 or initial.graphics_app_id != 769:
        focus.close(); raise RuntimeError('Idle Steam required; no test window or input created')
    os.environ.update(GDK_BACKEND='x11', DISPLAY=':0', NO_AT_BRIDGE='1')
    import gi
    gi.require_version('Gtk', '3.0'); gi.require_version('GdkX11', '3.0')
    from gi.repository import GdkX11, GLib, Gtk
    Gtk.init_check()
    window = Gtk.Window(title='Keyboard latency test — closes automatically')
    window.set_decorated(False); window.fullscreen()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20); box.set_border_width(100)
    box.pack_start(Gtk.Label(label='Keyboard latency test · synthetic text only'), False, False, 0)
    entry = Gtk.Entry(); box.pack_start(entry, False, False, 0); window.add(box); window.realize()
    xid = GdkX11.X11Window.get_xid(window.get_window())
    focus.api.xcb_change_property_checked.restype = Cookie
    focus.api.xcb_change_property_checked.argtypes = [c.c_void_p,c.c_uint8,c.c_uint32,c.c_uint32,
                                                    c.c_uint32,c.c_uint8,c.c_uint32,c.c_void_p]
    focus.api.xcb_request_check.restype = c.c_void_p
    focus.api.xcb_request_check.argtypes = [c.c_void_p, Cookie]
    for name, value, kind in (('STEAM_GAME',769,6), ('WM_TRANSIENT_FOR',initial.window,33)):
        encoded = name.encode()
        reply = focus._reply('xcb_intern_atom_reply', focus.api.xcb_intern_atom(
            focus.connection, False, len(encoded), encoded))
        atom = c.c_uint32.from_address(reply+8).value; focus.libc.free(reply)
        data = c.c_uint32(value)
        error = focus.api.xcb_request_check(focus.connection,
            focus.api.xcb_change_property_checked(focus.connection,0,xid,atom,kind,32,1,c.byref(data)))
        if error:
            focus.libc.free(error); window.destroy(); focus.close()
            raise RuntimeError('Could not prepare the helper window')
    def guard():
        snapshot = focus.snapshot()
        if snapshot.window != xid or not snapshot.input_in_surface:
            raise RuntimeError('Helper lost focus; input stopped')
    seen = []
    entry.connect('key-press-event', lambda _, event:
                  (seen.append((time.perf_counter(),event.hardware_keycode-8)),False)[1])
    window.show_all(); entry.grab_focus()
    loop = GLib.MainLoop(); started = time.perf_counter(); ready = [False]
    def wait():
        try:
            guard()
            if time.perf_counter()-started >= .3:
                ready[0] = True; loop.quit(); return False
        except RuntimeError: pass
        if time.perf_counter()-started > 3: loop.quit(); return False
        return True
    GLib.timeout_add(20, wait); loop.run()
    if not ready[0]:
        window.destroy(); focus.close(); raise RuntimeError('Helper window did not gain focus')
    return SimpleNamespace(window=window, entry=entry, seen=seen, guard=guard, focus=focus, bridge=None)


def run_case(panel, *, rate, count, render, repeat_interval, own=None, hold=False, backspace=False):
    import cairo
    from keyboard_layout import KeyboardLayout
    from modifiers import ModifierState
    from armada_dual_screen_input.keyboard_languages import KeyboardLanguages
    from armada_dual_screen_input.keyboard_pulses import KeyboardPulses
    from armada_dual_screen_input.input_settings import DEFAULTS

    GLib = panel.GLib
    loop = GLib.MainLoop()
    clock = time.perf_counter
    app = panel.PanelApp.__new__(panel.PanelApp)
    app.mode, app.ui_hidden, app.session_mode = 'split', False, 'game'
    app.collapsed = app._cleaned = False
    app.preferences = app.position = app.keyboard_guard = None
    app._touch_owner = {}; app._slider_drag = None; app._language_consumed = set()
    app.held_ui_button = app.held_ui_button_tid = None
    app.held_key = app.held_key_tid = None
    app.active_key_press = app.active_key_tid = None
    app.last_key_label = ''; app.last_event_time = 0
    app._repeat_stop = threading.Event(); app._repeat_thread = None
    app.input_lock = threading.RLock(); app.mods = ModifierState()
    app.keyboard_cfg = dict(panel.upstream.keyboard_settings.DEFAULTS)
    app.keyboard_cfg['keyboard_repeat_interval_ms'] = repeat_interval
    app.input_cfg = dict(DEFAULTS)
    app.kb_layout = KeyboardLayout(0, 500, 1240, 580)
    app.stats = SimpleNamespace(get_stats=lambda: {})
    app.pen_mode = 'off'; app.touch_mode = 'position'
    state = {'draw': True, 'running': True, 'error': None}
    sent, held, dispatch_ms, handler_ms, draw_ms, heartbeat_ms = [], set(), [], [], [], []

    def send(code, down):
        if own:
            if down:
                try:
                    own.guard()
                except Exception as error:
                    state['error'] = str(error)
                    loop.quit()
                    raise
            own.bridge.key(code, down)
        sent.append((clock(), code, down))
        (held.add if down else held.discard)(code)

    def release_all():
        for code in tuple(held): send(code, False)

    app.bridge = SimpleNamespace(key=send, release_all=release_all)
    app.key_pulses = KeyboardPulses(app._send_key_pulse, GLib.timeout_add, GLib.source_remove)
    app.raw_key_pulses = KeyboardPulses(send, GLib.timeout_add, GLib.source_remove)
    app.bridge.tap_key = app.key_pulses.tap
    app.drawing_area = SimpleNamespace(queue_draw=lambda: state.update(draw=True))
    app.languages = KeyboardLanguages('en_US', mode='game', runtime='/unused',
        changed=app.drawing_area.queue_draw, dispatch=GLib.idle_add,
        forward_key=app.raw_key_pulses.tap)
    app.languages.sync(True); app._install_language_key()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1240, 1080)
    cr = cairo.Context(surface)
    keys = [next(k for row in app.kb_layout.rows for k in row if k.label == label)
            for label in 'asdfjkl']
    if backspace:
        keys = [next(k for row in app.kb_layout.rows for k in row if k.code == 14)]
    expected = []
    if own:
        own.guard(); own.seen.clear()
        own.entry.set_text('x'*400 if backspace else '')
        own.entry.set_position(-1)
    start = clock()+.1
    last_beat = clock()

    def heartbeat():
        nonlocal last_beat
        now = clock(); heartbeat_ms.append(max(0, (now-last_beat)*1000-5)); last_beat = now
        return state['running']

    def paint():
        if state['draw'] and render:
            state['draw'] = False
            try:
                began = clock(); app._draw_ui(cr); draw_ms.append((clock()-began)*1000)
            except Exception as error:
                state['error'] = str(error); loop.quit(); return False
        return state['running']

    def event(due, tid, key, down):
        if not state['running']: return False
        dispatch_ms.append(max(0, (clock()-due)*1000))
        began = clock()
        try:
            if down:
                expected.append(key.code)
                app._handle_touch_down(tid, key.x+key.w/2, key.y+key.h/2, time.monotonic())
            else:
                app._handle_touch_up(tid, time.monotonic())
        except Exception as error:
            state['error'] = str(error); loop.quit()
        handler_ms.append((clock()-began)*1000)
        return False

    sources = [GLib.timeout_add(5, heartbeat),
               GLib.timeout_add(16, paint, priority=GLib.PRIORITY_HIGH_IDLE)]
    try:
        for i in range(1 if hold else count):
            key = keys[i % len(keys)]; due = start+i/rate
            # A modest overlap at 15 Hz exercises two-finger rollover too.
            for down, at in ((True, due), (False, due+(2 if hold else .09))):
                sources.append(GLib.timeout_add(max(1, round((at-clock())*1000)),
                                                event, at, i+1, key, down))
        sources.append(GLib.timeout_add(round((start+(2 if hold else (count-1)/rate)+.25-clock())*1000),
                                        lambda: (loop.quit(), False)[1]))
        loop.run()
    finally:
        state['running'] = False
        for source in sources:
            if GLib.MainContext.default().find_source_by_id(source): GLib.source_remove(source)
        app.key_pulses.close(); app.raw_key_pulses.close(); app.languages.close()
    actual = [code for _, code, down in sent if down]
    ordering = (bool(actual) and all(code == keys[0].code for code in actual)) if hold else actual == expected and len(actual) == count
    down_times = [at for at, _, down in sent if down]
    report = {'case': 'hold' if hold else 'typing', 'rate_hz': rate, 'render': render,
            'backspace': backspace,
            'expected_keys': None if hold else count, 'sent_keys': len(actual), 'ordering_exact': ordering,
            'keys_left_held': len(held), 'dispatch': summary(dispatch_ms),
            'handler': summary(handler_ms), 'render_cost': summary(draw_ms),
            'event_loop_lateness': summary(heartbeat_ms), 'error': state['error']}
    if hold and len(down_times) > 1:
        report['first_repeat_ms'] = round((down_times[1]-down_times[0])*1000,3)
        report['repeat_gap'] = summary([(b-a)*1000 for a,b in zip(down_times[1:],down_times[2:])])
    if own:
        received = [code for _,code in own.seen]
        report['received_keys'] = len(received)
        report['received_exact'] = received == actual
        expected_text = ('x'*max(0,400-len(actual)) if backspace else
                         ''.join(next(key.label for key in keys if key.code == code) for code in actual))
        report['text_exact'] = own.entry.get_text() == expected_text
        if received == actual:
            report['send_to_receiver'] = summary([(r-s)*1000 for (r,_),s in zip(own.seen,down_times)])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--repeat-interval-ms', type=int, default=20)
    parser.add_argument('--run-own-window-test', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux' or not 5 <= args.count <= 300:
        parser.error('Linux GTK and a count from 5 through 300 are required')
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root/'src'))
    with tempfile.TemporaryDirectory(prefix='ads-keyboard-bench-') as temp, \
            patch.dict(os.environ, {'XDG_STATE_HOME': temp}):
        own = own_window() if args.run_own_window_test else None
        try:
            from armada_dual_screen_input import panel_app as panel
            if own:
                own.bridge = panel.upstream.UInputBridge(logger=SimpleNamespace(log=lambda *a:None))
            with patch.object(panel.Gtk, 'Window', side_effect=AssertionError('No other window')), \
                    patch.object(panel.upstream, 'UInputBridge', side_effect=AssertionError('No other input device')):
                cases = []
                for render in (False, True):
                    for rate in (5,10,15):
                        cases.append(run_case(panel,rate=rate,count=args.count,render=render,
                                              repeat_interval=args.repeat_interval_ms,own=own))
                        if cases[-1]['error']: raise RuntimeError(cases[-1]['error'])
                    for backspace in (False, True):
                        cases.append(run_case(panel,rate=1,count=1,render=render,
                            repeat_interval=args.repeat_interval_ms,own=own,hold=True,backspace=backspace))
                        if cases[-1]['error']: raise RuntimeError(cases[-1]['error'])
        finally:
            if own:
                if own.bridge: own.bridge.close()
                own.window.destroy(); own.focus.close()
    result = {'scope': 'own-gtk-window-uinput' if own else 'real-glib-offscreen-fake-devices', 'cases': cases,
              'passed': all(c['ordering_exact'] and not c['keys_left_held'] and not c['error']
                            and c.get('received_exact',True) for c in cases)}
    result['passed'] = result['passed'] and all(c.get('text_exact',True) for c in cases)
    encoded = json.dumps(result, indent=2)
    if args.output: args.output.write_text(encoded+'\n')
    print(encoded)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
