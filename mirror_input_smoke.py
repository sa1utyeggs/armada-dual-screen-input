#!/usr/bin/env python3
"""Bounded hardware check in this script's own upper-screen test window.

Never sends buttons or wheel unless Gamescope reports this exact window as
both visible and input-focused. Creates no Steam library entry or settings.
This is a developer test, not a background service or game automation tool.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
from pathlib import Path
import time

from ei_input import GamescopeTarget, InputUnavailable, LibEIInput
from gamescope_focus import Cookie, UpperFocus
from mirrored_touch import TouchIntent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--x-display', required=True)
    parser.add_argument('--upper-display', default='gamescope-primary')
    parser.add_argument('--steam-ui-parent', action='store_true',
                        help='attach only this test window to the idle Steam UI')
    args = parser.parse_args()
    focus = UpperFocus(args.x_display)  # validates explicit local display first
    initial = focus.snapshot()
    if args.steam_ui_parent and (initial.app_id != 769 or initial.graphics_app_id != 769):
        parser.error('Steam UI must be in front; no game or overlay may be active')
    os.environ.update(GDK_BACKEND='x11', DISPLAY=args.x_display, NO_AT_BRIDGE='1')
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gdk, GLib, Gtk, GdkX11
    window = Gtk.Window(title='Armada input test — closes automatically')
    window.set_decorated(False)
    window.fullscreen()
    area = Gtk.DrawingArea()
    area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                    | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.SCROLL_MASK
                    | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    window.add(area)
    area.connect('draw', lambda _, cr: (cr.set_source_rgb(.06, .14, .18), cr.paint())[-1])
    window.realize()
    xid = window.get_window().get_xid()
    # Property is set only on the test window that this process just created.
    focus.api.xcb_change_property.restype = Cookie
    focus.api.xcb_change_property.argtypes = [c.c_void_p, c.c_uint8, c.c_uint32,
                                             c.c_uint32, c.c_uint32, c.c_uint8,
                                             c.c_uint32, c.c_void_p]
    def property(name, value, atom_type=6):
        encoded = name.encode()
        cookie = focus.api.xcb_intern_atom(focus.connection, False, len(encoded), encoded)
        reply = focus._reply('xcb_intern_atom_reply', cookie)
        atom = c.c_uint32.from_address(reply + 8).value
        focus.libc.free(reply)
        data = c.c_uint32(value)
        focus.api.xcb_change_property(focus.connection, 0, xid, atom, atom_type, 32, 1, c.byref(data))
    property('STEAM_GAME', 769 if args.steam_ui_parent else 0x414453)
    if args.steam_ui_parent:
        property('WM_TRANSIENT_FOR', initial.window, 33)
    focus.api.xcb_flush.argtypes = [c.c_void_p]
    focus.api.xcb_flush(focus.connection)
    events = []
    sender = None
    started = time.monotonic()
    sent = 0
    outcome = {'passed': False, 'input_sent': False}
    actions = [TouchIntent('move', (.25, .3)), TouchIntent('down', (.25, .3)),
               TouchIntent('move', (.75, .7)), TouchIntent('up', (.75, .7)),
               TouchIntent('wheel', (.5, .5), (0, -120)),  # initialize GTK/XI2 valuator
               TouchIntent('wheel', (.5, .5), (0, -60)),  # half-notch: no output yet
               TouchIntent('wheel', (.5, .5), (0, -60)),  # accumulated whole notch
               TouchIntent('wheel', (.5, .5), (0, -240)),
               TouchIntent('wheel', (.5, .5), (0, 240)),
               TouchIntent('wheel', (.5, .5), (240, 0)),
               TouchIntent('wheel', (.5, .5), (-240, 0))]

    def event(_, ev):
        if ev.type in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
            events.append({'kind': 'down' if ev.type == Gdk.EventType.BUTTON_PRESS else 'up',
                           'button': ev.get_button()[1], 'x': round(ev.x), 'y': round(ev.y)})
        elif ev.type == Gdk.EventType.MOTION_NOTIFY:
            events.append({'kind': 'move', 'x': round(ev.x), 'y': round(ev.y)})
        elif ev.type == Gdk.EventType.SCROLL:
            scroll = ev.scroll
            events.append({'kind': 'wheel', 'direction': int(scroll.direction),
                           'delta': [scroll.delta_x, scroll.delta_y]})
        return True

    def step():
        nonlocal sender, sent
        try:
            current = focus.snapshot()
            if sender is None:
                if current.window != xid or current.app_id != current.graphics_app_id:
                    if time.monotonic() - started > 3:
                        raise InputUnavailable('test window did not receive upper focus; no input sent')
                    return True
                expected = current
                sender = LibEIInput(GamescopeTarget.resolve(
                    Path(os.environ['XDG_RUNTIME_DIR']), args.upper_display),
                    (current.width, current.height), x_server_pid=current.server_pid,
                    focus_check=lambda: focus.snapshot() == expected)
            sender.poll()
            if not sender.ready:
                if time.monotonic() - started > 4:
                    raise InputUnavailable('input handshake timed out')
                return True
            if sent < len(actions):
                sender.send(actions[sent])
                sent += 1
                outcome['input_sent'] = True
                return True
            presses = [e for e in events if e['kind'] == 'down']
            releases = [e for e in events if e['kind'] == 'up']
            scrolls = [e for e in events if e['kind'] == 'wheel']
            deltas = [event['delta'] for event in scrolls]
            outcome['passed'] = (len(presses) == len(releases) == 1
                                 and presses[0]['button'] == releases[0]['button'] == 1
                                 and any(abs(delta[1]) >= 1 for delta in deltas)
                                 and all(any(delta[axis] * sign > 0 for delta in deltas)
                                         for axis in (0, 1) for sign in (-1, 1)))
            Gtk.main_quit()
            return False
        except (InputUnavailable, OSError, ValueError) as error:
            outcome['error'] = str(error)
            Gtk.main_quit()
            return False

    area.connect('event', event)
    window.show_all()
    GLib.timeout_add(100, step)
    GLib.timeout_add_seconds(6, lambda: (Gtk.main_quit(), False)[-1])
    try:
        Gtk.main()
    finally:
        if sender:
            sender.close()
        window.destroy()
        focus.close()
        outcome['events'] = events
        print(json.dumps(outcome), flush=True)
    return 0 if outcome['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
