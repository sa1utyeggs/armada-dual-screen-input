#!/usr/bin/env python3
"""Draw a passive aiming ring in Gamescope; never inject pointer input.

This child must use X11, not the lower panel's Wayland GDK backend. Own-window
properties only: no root focus settings, cursor changes, or other app writes.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
import socket
import time
from .marker_colors import DEFAULT_COLORS, MarkerColors, parse_color
from .marker_appearance import load_appearance, prepare_sprites


def run(fd, target, frame_rate='auto', *, colors=DEFAULT_COLORS, position_style='ring', appearance=None):
    appearance = appearance or load_appearance(position_style, colors)
    prepare_sprites(appearance)
    if appearance.style != 'ring':
        prepare_sprites(appearance.for_mode('direct'))
    os.environ['GDK_BACKEND'] = 'x11'
    os.environ['DISPLAY'] = target.surface_display
    os.environ['NO_AT_BRIDGE'] = '1'
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gtk, Gdk, GdkX11, GLib
    import cairo
    from .gamescope_focus import UpperFocus, Cookie, Geometry
    from .marker_sample import decode_sample
    from .marker_motion import MarkerMotion
    from .marker_frames import MarkerFrames
    from .marker_paint import MarkerScene, draw_rings

    channel = socket.socket(fileno=fd)
    channel.setblocking(False)
    loop = GLib.MainLoop()
    control = UpperFocus(':0')
    expected = control.snapshot()
    if not target.matches_focus(expected):
        raise RuntimeError('marker foreground changed before setup')
    focus = UpperFocus(target.surface_display, _controller=control)
    window = None
    if focus.server_pid != target.server_pid:
        raise RuntimeError('marker and upper focus belong to different Gamescopes')

    def root_size():
        reply = control._reply('xcb_get_geometry_reply',
                               control.api.xcb_get_geometry(control.connection, control.root))
        try:
            geometry = Geometry.from_address(reply)
            return geometry.width, geometry.height
        finally:
            control.libc.free(reply)

    size = root_size()
    if not all(1 <= n <= 8192 for n in size):
        raise RuntimeError('invalid upper output geometry')
    if not expected.compatible(size):
        raise RuntimeError('marker requires a full-frame matching-aspect surface')
    canvas = (target.width, target.height)
    scene = MarkerScene(canvas)
    motion = MarkerMotion(canvas)
    state = {'ready': False, 'updates': 0, 'draws': 0}

    def send(message):
        try:
            channel.send(json.dumps(message).encode())
        except BlockingIOError:
            pass
        except OSError:
            loop.quit()

    def property32(xid, name, value, kind=6):
        encoded = name.encode('ascii')
        reply = focus._reply('xcb_intern_atom_reply', focus.api.xcb_intern_atom(
            focus.connection, False, len(encoded), encoded))
        try:
            atom = c.c_uint32.from_address(reply+8).value
        finally:
            focus.libc.free(reply)
        data = c.c_uint32(value)
        cookie = focus.api.xcb_change_property_checked(focus.connection, 0, xid, atom, kind, 32, 1, c.byref(data))
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
    window.set_default_size(*canvas)
    window.move(target.x, target.y)
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_app_paintable(True)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    window.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
    visual = window.get_screen().get_rgba_visual()
    if visual is None:
        raise RuntimeError('upper overlay has no transparent visual')
    window.set_visual(visual)

    def realize(widget):
        native = widget.get_window()
        native.set_override_redirect(True)
        native.input_shape_combine_region(cairo.Region(), 0, 0)
        native.set_accept_focus(False)
        xid = GdkX11.X11Window.get_xid(native)
        for name, value, kind in target.properties():
            property32(xid, name, value, kind)
        focus.api.xcb_flush(focus.connection)
        # Publish our XID before mapping so the controller can never bind
        # an unexpected self-focus snapshot as a new application target.
        channel.send(json.dumps({'window': xid}).encode())

    def draw(widget, cr):
        state['draws'] += 1
        draw_rings(cr, scene.rings, canvas, colors, scene.appearance)
        if not state['ready']:
            state['ready'] = True
            send({'ready': True, 'size': size, 'refresh_millihz': frames.monitor_millihz})
        return True

    def refresh_rate():
        monitor = window.get_display().get_monitor_at_window(window.get_window())
        return monitor.get_refresh_rate() if monitor is not None else 0

    def paint_pending():
        if not window.get_mapped():
            return  # Keep damage; map-event requests a frame when visible.
        scene.update(motion.sample(time.monotonic()), appearance.for_mode(motion.mode))
        rectangles = scene.take_damage()
        if not rectangles:
            if motion.animating:
                frames.request()
            return
        region = cairo.Region()
        for rectangle in rectangles:
            region.union(cairo.RectangleInt(*rectangle))
        native = window.get_window()
        # GTK 3's public synchronous update path maintains GL buffer-age
        # damage/repair before invoking our draw signal. Direct partial
        # begin/end_draw_frame skips that history and leaves stale rings.
        # This API is deprecated in GTK 3, but available in our supported
        # GTK 3.24 runtime; it touches only our own marker window.
        native.invalidate_region(region, False)
        native.process_updates(False)
        if motion.animating:
            frames.request()  # Only the short visual tail; no input synthesis.

    def paint_failed(error):
        send({'error': 'marker frame failed: '+str(error)})
        loop.quit()

    frames = MarkerFrames(GLib.timeout_add, GLib.source_remove, paint_pending, paint_failed,
                          frame_rate=frame_rate)

    def mapped(*_):
        frames.set_refresh(refresh_rate())
        scene.invalidate(full=True)
        frames.request()
        return False

    def input_ready(source, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            loop.quit()
            return False
        latest = None
        restore = False
        snap = False
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
                latest = decode_sample(message)
                snap |= latest.snap  # Preserve click/lift barriers across a batch.
                state['updates'] += 1
        except (OSError, ValueError, TypeError):
            loop.quit()
            return False
        if latest is not None:
            if motion.accept(latest, time.monotonic(), force_snap=snap):
                frames.request()
        if restore:
            # Reassert only our matching-app, input-transparent decoration.
            # It does not compete for mangoapp's external-overlay slot.
            # Never present(), take focus, or restack on a timer.
            window.get_window().raise_()
            scene.invalidate()
            if scene.damage:
                frames.request()
            window.get_display().flush()
        return True

    def heartbeat():
        try:
            if root_size() != size:
                raise RuntimeError('upper output geometry changed')
            frames.set_refresh(refresh_rate())
            send({'alive': True, 'updates': state['updates'], 'draws': state['draws'],
                  'refresh_millihz': frames.monitor_millihz})
            return True
        except Exception:
            loop.quit()
            return False

    window.connect('draw', draw)
    window.connect('map-event', mapped)
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
        frames.close()
        window.destroy()
        focus.close()
        control.close()
        channel.close()


