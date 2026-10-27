"""Passive EGL worker; the input path remains in PanelPosition unchanged.

Only setup before IPC/map can report NativeUnavailable. Once activated, any
failure closes this worker and lets the parent's normal freshness guard
release input; it never falls back onto a live window or another target.
"""
from __future__ import annotations

import ctypes as c
import json
import os
import socket
import time

from .marker_colors import DEFAULT_COLORS
from .marker_appearance import load_appearance


class NativeUnavailable(RuntimeError):
    """Native setup failed with no published/mapped window or consumed IPC."""


def run(fd, target, frame_rate='auto', *, colors=DEFAULT_COLORS, position_style='ring', appearance=None):
    appearance = appearance or load_appearance(position_style, colors)
    os.environ.update(GDK_BACKEND='x11', DISPLAY=target.surface_display, NO_AT_BRIDGE='1')
    import gi
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    from gi.repository import Gdk, GdkX11, GLib
    from .gamescope_focus import UpperFocus, Geometry
    from .marker_egl import Surface
    from .marker_gpu import Renderer
    from .marker_sample import decode_sample
    from .marker_motion import MarkerMotion
    from .marker_frames import MarkerFrames
    from .marker_paint import MarkerScene

    control = UpperFocus(':0')
    focus = surface = renderer = display = frames = channel = None
    sources = []
    loop = GLib.MainLoop()
    state = {'ready': False, 'updates': 0, 'draws': 0}

    def root_size():
        reply = control._reply('xcb_get_geometry_reply',
                               control.api.xcb_get_geometry(control.connection, control.root))
        try:
            geometry = Geometry.from_address(reply)
            return geometry.width, geometry.height
        finally:
            control.libc.free(reply)

    def send(value):
        try:
            channel.send(json.dumps(value).encode())
        except BlockingIOError:
            pass
        except OSError:
            loop.quit()

    try:
        expected = control.snapshot()
        if not target.matches_focus(expected):
            raise RuntimeError('marker foreground changed before setup')
        focus = UpperFocus(target.surface_display, _controller=control)
        if focus.server_pid != target.server_pid:
            raise RuntimeError('marker and upper focus belong to different Gamescopes')
        size = root_size()
        if not all(1 <= n <= 8192 for n in size):
            raise RuntimeError('invalid upper output geometry')
        if not expected.compatible(size):
            raise RuntimeError('marker requires a full-frame matching-aspect surface')
        canvas = (target.width, target.height)

        # Before this succeeds, no IPC has been consumed and no window mapped.
        # Cleanup in finally completes before the dispatcher starts GTK fallback.
        try:
            surface = Surface(focus, target)
            renderer = Renderer(canvas, colors, position_style=position_style, appearance=appearance)
            display = Gdk.Display.open(target.surface_display)
            if display is None:
                raise RuntimeError('upper monitor display unavailable')
            foreign = GdkX11.X11Window.foreign_new_for_display(display, surface.window)
            if foreign is None:
                raise RuntimeError('owned native window wrapper unavailable')
        except (OSError, RuntimeError, AttributeError, ValueError) as error:
            raise NativeUnavailable(str(error)) from error

        if not target.matches_focus(control.snapshot()):
            raise RuntimeError('marker foreground changed during setup')
        channel = socket.socket(fileno=fd)
        channel.setblocking(False)
        scene, motion = MarkerScene(canvas), MarkerMotion(canvas)

        def refresh_rate():
            monitor = display.get_monitor_at_window(foreign)
            return monitor.get_refresh_rate() if monitor is not None else 0

        def paint_pending():
            scene.update(motion.sample(time.monotonic()), appearance.for_mode(motion.mode))
            rectangles = scene.take_damage()
            if not rectangles:
                if motion.animating:
                    frames.request()
                return
            renderer.draw(scene.rings, mode=motion.mode)
            surface.swap(rectangles)
            state['draws'] += 1
            if not state['ready']:
                renderer.check()
                state['ready'] = True
                send({'ready': True, 'size': size,
                      'refresh_millihz': frames.monitor_millihz})
            if motion.animating:
                frames.request()  # Visual tail only; never synthetic input.

        def failed(error):
            send({'error': 'native marker frame failed: '+str(error)})
            loop.quit()

        frames = MarkerFrames(GLib.timeout_add, GLib.source_remove, paint_pending, failed,
                              frame_rate=frame_rate)
        frames.set_refresh(refresh_rate())

        def incoming(_, condition):
            if condition & (GLib.IO_HUP | GLib.IO_ERR):
                loop.quit()
                return False
            latest = None
            snap = restore = False
            try:
                for _ in range(64):
                    try:
                        message = json.loads(channel.recv(4096))
                    except BlockingIOError:
                        break
                    if message is None:
                        loop.quit()
                        return False
                    if isinstance(message, dict) and message == {'restore': True}:
                        restore = True
                        continue
                    latest = decode_sample(message)
                    snap |= latest.snap  # Preserve press/lift barriers in a batch.
                    state['updates'] += 1
                if latest is not None and motion.accept(latest, time.monotonic(), force_snap=snap):
                    frames.request()
                if restore:
                    surface.raise_window()  # Own decoration only, never focus.
                    scene.invalidate()
                    if scene.damage:
                        frames.request()
                return True
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                failed(error)
                return False

        def xevents(_, condition):
            if condition & (GLib.IO_HUP | GLib.IO_ERR):
                loop.quit()
                return False
            if focus.api.xcb_connection_has_error(focus.connection):
                loop.quit()
                return False
            while True:
                event = focus.api.xcb_poll_for_event(focus.connection)
                if not event:
                    break
                try:
                    kind = c.c_uint8.from_address(event).value & 127
                    if kind == 12:  # Expose: repaint our complete backbuffer.
                        scene.invalidate(full=True)
                        frames.request()
                    elif kind in (0, 17):  # X error / DestroyNotify.
                        loop.quit()
                        return False
                finally:
                    focus.libc.free(event)
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

        sources.append(GLib.io_add_watch(channel.fileno(),
                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, incoming))
        sources.append(GLib.io_add_watch(focus.api.xcb_get_file_descriptor(focus.connection),
                       GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, xevents))
        sources.append(GLib.timeout_add(500, heartbeat))
        # All passive-window properties and input shape have been checked.
        # Publishing the XID before map lets the parent exclude our own window.
        channel.send(json.dumps({'window': surface.window}).encode())
        surface.map()
        scene.invalidate(full=True)
        frames.request()
        loop.run()
    finally:
        if frames is not None:
            frames.close()
        for source in sources:
            if GLib.MainContext.default().find_source_by_id(source):
                GLib.source_remove(source)
        try:
            if renderer is not None:
                renderer.close()
        finally:
            if surface is not None:
                surface.close()
            if display is not None:
                display.close()
            if focus is not None:
                focus.close()
            control.close()
            if channel is not None:
                channel.close()
