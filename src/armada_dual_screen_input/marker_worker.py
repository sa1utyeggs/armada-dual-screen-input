#!/usr/bin/env python3
"""Draw a passive aiming ring in Gamescope; never inject pointer input.

This child must use X11, not the lower panel's Wayland GDK backend. Own-window
properties only: no root focus settings, cursor changes, or other app writes.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import math
import os
import socket


def run(fd, display, server_pid):
    os.environ['GDK_BACKEND'] = 'x11'
    os.environ['DISPLAY'] = display
    os.environ['NO_AT_BRIDGE'] = '1'
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gtk, Gdk, GdkX11, GLib
    import cairo
    from .gamescope_focus import UpperFocus, Cookie, Geometry
    from .marker_state import decode_rings

    channel = socket.socket(fileno=fd)
    channel.setblocking(False)
    loop = GLib.MainLoop()
    focus = UpperFocus(display)
    window = None
    if focus.server_pid != server_pid:
        raise RuntimeError('marker and upper focus belong to different Gamescopes')

    def root_size():
        reply = focus._reply('xcb_get_geometry_reply',
                             focus.api.xcb_get_geometry(focus.connection, focus.root))
        try:
            geometry = Geometry.from_address(reply)
            return geometry.width, geometry.height
        finally:
            focus.libc.free(reply)

    size = root_size()
    if not all(1 <= n <= 8192 for n in size):
        raise RuntimeError('invalid upper output geometry')
    state = {'rings': (), 'ready': False, 'updates': 0, 'draws': 0}

    def send(message):
        try:
            channel.send(json.dumps(message).encode())
        except BlockingIOError:
            pass
        except OSError:
            loop.quit()

    def property32(xid, name, value):
        encoded = name.encode('ascii')
        reply = focus._reply('xcb_intern_atom_reply', focus.api.xcb_intern_atom(
            focus.connection, False, len(encoded), encoded))
        try:
            atom = c.c_uint32.from_address(reply+8).value
        finally:
            focus.libc.free(reply)
        data = c.c_uint32(value)
        cookie = focus.api.xcb_change_property_checked(focus.connection, 0, xid, atom, 6, 32, 1, c.byref(data))
        error = focus.api.xcb_request_check(focus.connection, cookie)
        if error:
            focus.libc.free(error)
            raise RuntimeError('marker window property could not be set')

    focus.api.xcb_change_property_checked.restype = Cookie
    focus.api.xcb_change_property_checked.argtypes = [c.c_void_p, c.c_uint8, c.c_uint32,
        c.c_uint32, c.c_uint32, c.c_uint8, c.c_uint32, c.c_void_p]
    focus.api.xcb_request_check.restype = c.c_void_p
    focus.api.xcb_request_check.argtypes = [c.c_void_p, Cookie]
    focus.api.xcb_flush.restype = c.c_int
    focus.api.xcb_flush.argtypes = [c.c_void_p]

    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_title('Armada positioning marker')
    window.set_default_size(*size)
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_app_paintable(True)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    visual = window.get_screen().get_rgba_visual()
    if visual is None:
        raise RuntimeError('upper overlay has no transparent visual')
    window.set_visual(visual)

    def realize(widget):
        native = widget.get_window()
        native.input_shape_combine_region(cairo.Region(), 0, 0)
        native.set_accept_focus(False)
        xid = GdkX11.X11Window.get_xid(native)
        property32(xid, 'GAMESCOPE_EXTERNAL_OVERLAY', 1)
        property32(xid, '_NET_WM_WINDOW_OPACITY', 0xffffffff)
        focus.api.xcb_flush(focus.connection)

    def draw(widget, cr):
        state['draws'] += 1
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        for u, v, pressed in state['rings']:
            x, y = u*(size[0]-1), v*(size[1]-1)
            for width, color in ((5, (0, 0, 0, .85)),
                                 (2.5, (1., .65, .15, 1.) if pressed else (.35, .85, 1., 1.))):
                cr.set_line_width(width)
                cr.set_source_rgba(*color)
                cr.new_sub_path()
                cr.arc(x, y, 12, 0, math.tau)
                cr.stroke()
        # Open center keeps small card text and targets visible.
        if not state['ready']:
            state['ready'] = True
            send({'ready': True, 'size': size})
        return True

    def input_ready(source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            loop.quit()
            return False
        latest = None
        restore = False
        try:
            for _ in range(64):
                try:
                    packet = channel.recv(4096)
                except BlockingIOError:
                    break
                message = json.loads(packet)
                if message is None:
                    loop.quit()
                    return False
                if isinstance(message, dict) and message == {'restore': True}:
                    restore = True
                    continue
                latest = decode_rings(message)
                state['updates'] += 1
        except (OSError, ValueError, TypeError):
            loop.quit()
            return False
        if latest is not None:
            old = state['rings']
            state['rings'] = latest
            # Redraw the old/new ring bounds, not every pixel of the output.
            for point in (*old, *state['rings']):
                window.queue_draw_area(round(point[0]*(size[0]-1))-17,
                                       round(point[1]*(size[1]-1))-17, 35, 35)
        if restore:
            # Legacy Gamescope selects one external overlay by opacity and
            # stacking order. Steam's quick-access menu can restack mangoapp
            # above this window. Raise only our input-transparent window once
            # when the controller has verified the foreground target again;
            # never present(), take focus, or fight another overlay on a timer.
            window.get_window().raise_()
            for point in state['rings']:
                window.queue_draw_area(round(point[0]*(size[0]-1))-17,
                                       round(point[1]*(size[1]-1))-17, 35, 35)
            window.get_display().flush()
        return True

    def heartbeat():
        try:
            if root_size() != size:
                raise RuntimeError('upper output geometry changed')
            send({'alive': True, 'updates': state['updates'], 'draws': state['draws']})
            return True
        except Exception:
            loop.quit()
            return False

    window.connect('draw', draw)
    window.connect('destroy', lambda *_: loop.quit())
    GLib.io_add_watch(channel.fileno(), GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, input_ready)
    GLib.timeout_add(500, heartbeat)
    try:
        # Complete and acknowledge all setup before mapping. Exceptions from a
        # GTK signal handler would otherwise be swallowed and could map an
        # ordinary focusable window instead of a registered passive overlay.
        window.realize()
        realize(window)
        window.show_all()
        loop.run()
    finally:
        window.destroy()
        focus.close()
        channel.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fd', type=int, required=True)
    parser.add_argument('--display', required=True)
    parser.add_argument('--server-pid', type=int, required=True)
    args = parser.parse_args()
    try:
        run(args.fd, args.display, args.server_pid)
    except Exception as error:
        try:
            socket.socket(fileno=args.fd).send(json.dumps({'error': str(error)}).encode())
        except OSError:
            pass
        raise SystemExit(1)
