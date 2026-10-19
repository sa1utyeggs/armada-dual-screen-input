#!/usr/bin/env python3
"""Bounded Game Mode native-touch route test in this program's own windows.

Run as the normal handheld user. No persistent device, service, udev rule or
Steam setting is changed. The upper test window must remain focused and the
virtual device must be opened only by its Gamescope before any contact is sent.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from gamescope_focus import Cookie, UpperFocus
from native_touch import VirtualTouchProbe
from session_detect import detect_target_session
from supervisor import child_environment


def owners(node: Path) -> set[int]:
    """Inspect descriptor links, never open or read input event nodes."""
    result = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    if os.readlink(fd) == str(node):
                        result.add(int(process.name))
                        break
                except OSError:
                    pass
        except OSError:
            pass
    return result


def observe_bottom(folder: Path) -> int:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    if os.environ.get('WAYLAND_DISPLAY') != 'armada-plasma-bottom' or not GtkLayerShell.is_supported():
        raise RuntimeError('verified bottom KWin session is required')
    display = Gdk.Display.get_default()
    if display is None or display.get_n_monitors() != 1:
        raise RuntimeError('unambiguous lower output required')
    window = Gtk.Window(title='Native touch route observer')
    window.set_accept_focus(False)
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_monitor(window, display.get_monitor(0))
    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.TOP)
    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
    for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                 GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
        GtkLayerShell.set_anchor(window, edge, True)
    area = Gtk.EventBox()
    area.add(Gtk.Label(label='原生触摸路由验证中\n请暂勿触摸屏幕；测试结束后自动恢复'))
    area.add_events(Gdk.EventMask.TOUCH_MASK)
    window.add(area)
    counts = {'begin': 0, 'move': 0, 'end': 0, 'cancel': 0}
    phases = {Gdk.EventType.TOUCH_BEGIN: 'begin', Gdk.EventType.TOUCH_UPDATE: 'move',
              Gdk.EventType.TOUCH_END: 'end', Gdk.EventType.TOUCH_CANCEL: 'cancel'}
    def event(_, ev):
        phase = phases.get(ev.type)
        if phase:
            counts[phase] += 1
        return True
    area.connect('touch-event', event)
    loop = GLib.MainLoop()
    window.show_all()
    GLib.timeout_add(150, lambda: ((folder / 'bottom-ready').write_text('ready'), False)[1])
    GLib.timeout_add(7000, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        window.destroy()
        (folder / 'bottom-result.json').write_text(json.dumps(counts))
    return 0


def property_atom(focus, name):
    encoded = name.encode()
    cookie = focus.api.xcb_intern_atom(focus.connection, False, len(encoded), encoded)
    reply = focus._reply('xcb_intern_atom_reply', cookie)
    try:
        return c.c_uint32.from_address(reply + 8).value
    finally:
        focus.libc.free(reply)


def touch_mode(focus):
    cookie = focus.api.xcb_get_property(focus.connection, False, focus.root,
                                        property_atom(focus, 'STEAM_TOUCH_CLICK_MODE'), 0, 0, 1)
    reply = focus._reply('xcb_get_property_reply', cookie)
    try:
        if focus.api.xcb_get_property_value_length(reply) != 4:
            return None
        return c.c_uint32.from_address(focus.api.xcb_get_property_value(reply)).value
    finally:
        focus.libc.free(reply)


def upper_test(args, folder: Path, child) -> dict:
    focus = UpperFocus(args.x_display)
    initial = focus.snapshot()
    if initial.app_id != 769 or initial.graphics_app_id != 769 or touch_mode(focus) != 4:
        focus.close()
        raise RuntimeError('idle Steam UI with native touch passthrough is required; no input sent')
    os.environ.update(GDK_BACKEND='x11', DISPLAY=args.x_display, NO_AT_BRIDGE='1')
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gdk, GLib, Gtk, GdkX11
    window = Gtk.Window(title='Armada native touch test — automatic close')
    window.set_decorated(False)
    window.fullscreen()
    area = Gtk.DrawingArea()
    area.add_events(Gdk.EventMask.TOUCH_MASK)
    window.add(area)
    area.connect('draw', lambda _, cr: (cr.set_source_rgb(.04, .15, .18), cr.paint())[-1])
    window.realize()
    xid = window.get_window().get_xid()
    focus.api.xcb_change_property.restype = Cookie
    focus.api.xcb_change_property.argtypes = [c.c_void_p, c.c_uint8, c.c_uint32,
                                             c.c_uint32, c.c_uint32, c.c_uint8,
                                             c.c_uint32, c.c_void_p]
    for name, value, kind in [('STEAM_GAME', 769, 6), ('WM_TRANSIENT_FOR', initial.window, 33)]:
        data = c.c_uint32(value)
        focus.api.xcb_change_property(focus.connection, 0, xid, property_atom(focus, name),
                                      kind, 32, 1, c.byref(data))
    focus.api.xcb_flush.argtypes = [c.c_void_p]
    focus.api.xcb_flush(focus.connection)
    loop = GLib.MainLoop()
    events, active = [], set()
    outcome = {'passed': False, 'input_sent': False, 'max_contacts': 0}
    phases = {Gdk.EventType.TOUCH_BEGIN: 'begin', Gdk.EventType.TOUCH_UPDATE: 'move',
              Gdk.EventType.TOUCH_END: 'end', Gdk.EventType.TOUCH_CANCEL: 'cancel'}
    def event(_, ev):
        phase = phases.get(ev.type)
        if not phase:
            return True
        seq = ev.get_event_sequence()
        if phase == 'begin': active.add(seq)
        elif phase in ('end', 'cancel'): active.discard(seq)
        outcome['max_contacts'] = max(outcome['max_contacts'], len(active))
        device = ev.get_source_device()
        events.append({'phase': phase, 'point': [round(ev.x), round(ev.y)],
                       'source': device.get_source().value_nick if device else 'unknown'})
        return True
    area.connect('touch-event', event)
    sender = None
    expected = None
    ready_at = 0.0
    started = time.monotonic()
    sent = 0
    actions = [('down', 1, .5, .5), ('move', 1, .25, .3), ('move', 1, .75, .7), ('up', 1),
               ('down', 2, .3, .5), ('down', 3, .7, .5),
               ('move', 2, .3, .4), ('move', 3, .7, .4), ('up', 2), ('up', 3)]
    def guard():
        return (expected is not None and focus.snapshot() == expected
                and touch_mode(focus) == 4 and owners(sender.node) == {expected.server_pid})
    def step():
        nonlocal sender, expected, ready_at, sent
        try:
            if child.poll() is not None:
                raise RuntimeError('bottom observer exited early; no further input')
            current = focus.snapshot()
            if sender is None:
                if current.window != xid or not current.input_in_surface or not (folder / 'bottom-ready').exists():
                    if time.monotonic() - started > 3:
                        raise RuntimeError('own windows did not become ready; no input sent')
                    return True
                expected = current
                sender = VirtualTouchProbe(rotation=args.rotation, guard=guard)
                outcome['surface_size'] = [expected.width, expected.height]
                ready_at = time.monotonic()
                return True
            if time.monotonic() - ready_at < 1:
                return True  # udev/libinput hotplug; no contact events yet
            if sent < len(actions):
                sender.contact(*actions[sent])
                sent += 1
                outcome['input_sent'] = True
                return True
            counts = {phase: sum(e['phase'] == phase for e in events) for phase in phases.values()}
            points = [e['point'] for e in events if e['phase'] == 'move']
            expected_points = [[round(expected.width * u), round(expected.height * v)]
                               for u, v in ((.25, .3), (.75, .7))]
            coords_ok = all(any(abs(p[0] - want[0]) <= 3 and abs(p[1] - want[1]) <= 3
                               for p in points) for want in expected_points)
            outcome.update(upper_counts=counts, coordinate_match=coords_ok,
                           native_source=all(e['source'] == 'touchscreen' for e in events))
            outcome['passed'] = (counts['begin'] == counts['end'] == 3 and counts['move'] >= 4
                                 and not counts['cancel'] and not active
                                 and outcome['max_contacts'] == 2 and coords_ok and outcome['native_source'])
            loop.quit()
            return False
        except Exception as error:
            outcome['error'] = str(error)
            loop.quit()
            return False
    window.show_all()
    GLib.timeout_add(120, step)
    GLib.timeout_add(5500, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        if sender:
            node = sender.node
            sender.close()
            time.sleep(.05)
            outcome['device_removed'] = not node.exists()
        window.destroy()
        focus.close()
        outcome['events_in_own_test_window'] = events
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--x-display', default=':0')
    parser.add_argument('--rotation', choices=('normal', 'right', 'left', 'inverted'),
                        help='explicit virtual-device transform; do not copy physical panel rotation')
    parser.add_argument('--gtk-runtime-root', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--observe-bottom', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.getuid() == 0 or not sys.platform.startswith('linux'):
        parser.error('run as the normal handheld Linux user')
    if args.observe_bottom:
        return observe_bottom(args.observe_bottom)
    if args.rotation is None:
        parser.error('select an explicit virtual-device rotation for the bounded test')
    target = detect_target_session(game_only=True)
    if target is None:
        parser.error('verified Game Mode bottom session required')
    env = child_environment(target)
    if args.gtk_runtime_root:
        lib = args.gtk_runtime_root.resolve(strict=True) / 'usr/lib64'
        env['LD_LIBRARY_PATH'] = str(lib)
        env['GI_TYPELIB_PATH'] = str(lib / 'girepository-1.0')
    outcome = {'passed': False}
    with tempfile.TemporaryDirectory(prefix='ads-native-probe.') as temporary:
        folder = Path(temporary)
        with (folder / 'bottom.log').open('wb') as log:
            child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()),
                                      '--observe-bottom', temporary], env=env,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            try:
                outcome = upper_test(args, folder, child)
            except Exception as error:
                outcome['error'] = str(error)
            finally:
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()
        result = folder / 'bottom-result.json'
        outcome['bottom_counts'] = json.loads(result.read_text()) if result.exists() else None
        outcome['passed'] &= (outcome['bottom_counts'] is not None
                              and not any(outcome['bottom_counts'].values())
                              and outcome.get('device_removed', False))
        if outcome['bottom_counts'] is None:
            outcome['bottom_error'] = (folder / 'bottom.log').read_text()[-1000:]
    print(json.dumps(outcome), flush=True)
    if args.report:
        args.report.write_text(json.dumps(outcome, indent=2) + '\n')
    return 0 if outcome['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
