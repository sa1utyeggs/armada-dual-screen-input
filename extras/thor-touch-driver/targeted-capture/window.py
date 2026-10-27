#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Owned lower X11 window, manual touches and read-only physical evdev capture.

Run only after the actual lower X display has been identified. This program
does not stop/start services, grab evdev, inject input or manage kernel modules.
"""
from __future__ import annotations

import argparse
import array
import fcntl
import json
import math
import os
from pathlib import Path
import select
import signal
import struct
import sys
import threading
import time

from capture_core import LifetimeBudget, Protocol, SlotState
from ui_catalogs import text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--target', choices=('A', 'B'), default='A')
    parser.add_argument('--language', choices=('en', 'zh-CN'), default='en')
    parser.add_argument('--display', required=True)
    parser.add_argument('--trace-required', action='store_true')
    parser.add_argument('--post-hold-seconds', type=int, choices=(0, 3), default=0)
    parser.add_argument('--scan-mode', choices=('moving', 'stationary'), default='moving')
    parser.add_argument('--wait-seconds', type=int, default=600)
    parser.add_argument('--continuous-secondary', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 600:
        parser.error('Waiting budget must be 1..600 seconds')
    if args.scan_mode == 'stationary' and args.post_hold_seconds != 3:
        parser.error('Stationary control requires --post-hold-seconds 3')
    if args.continuous_secondary and args.scan_mode != 'stationary':
        parser.error('--continuous-secondary requires --scan-mode stationary')
    if args.display != ':2':
        parser.error('This prepared helper is restricted to the previously verified lower display :2')
    folder = args.folder
    if not folder.is_dir() or any((folder/name).exists() for name in ('window-events.jsonl', 'ready', 'done', 'status.json', 'capture-request', 'capture.done', 'trace-ready', 'trace-failed', 'trace-result.json', 'register-trace.txt')):
        parser.error('Use a fresh existing folder')
    if not os.environ.get('ADS_TARGETED_READY'):
        app = Path.home()/'.local/share/thor-panel/current'
        sys.path.insert(0, str(app/'src'))
        from armada_dual_screen_input.session_detect import detect_target_session
        from armada_dual_screen_input.supervisor import child_environment
        target = detect_target_session(game_only=True)
        if target is None:
            raise SystemExit('No lower Game Mode session')
        env = child_environment(target)
        env.update(ADS_TARGETED_READY='1', GDK_BACKEND='x11', DISPLAY=args.display)
        os.execve(sys.executable, [sys.executable, '-B', *sys.argv], env)
    if os.environ.get('DISPLAY') != args.display or os.environ.get('GDK_BACKEND') != 'x11':
        raise SystemExit('Unexpected display/backend')
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkX11', '3.0')
    gi.require_version('PangoCairo', '1.0')
    from gi.repository import Gtk, Gdk, GdkX11, GLib, Pango, PangoCairo

    descriptor = os.open(folder/'window-events.jsonl', os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    stream = os.fdopen(descriptor, 'w', buffering=1)
    lock, running = threading.Lock(), threading.Event()
    running.set()
    start, contacts, next_id, written = time.monotonic(), {}, 1, 0
    positions = {}
    contact_begins = {}
    budget = LifetimeBudget(start, wait_seconds=args.wait_seconds)
    log_full = False
    protocol = Protocol(trace_required=args.trace_required, post_hold_seconds=args.post_hold_seconds,
                        scan_mode=args.scan_mode, continuous_secondary=args.continuous_secondary)
    raw_ready = threading.Event()
    loop = GLib.MainLoop()
    window = Gtk.Window(title=text('title', args.language))
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_decorated(False)
    window.set_default_size(1240, 1080)
    window.fullscreen()
    area = Gtk.DrawingArea()
    area.add_events(Gdk.EventMask.TOUCH_MASK)
    window.add(area)
    fixed_y = 760 if args.target == 'A' else 540
    prior_phase = None
    requested = captured = False

    def record(**value):
        nonlocal written, log_full
        line = json.dumps(dict(at=time.monotonic(), **value), ensure_ascii=False)+'\n'
        with lock:
            if log_full:
                return False
            written += len(line.encode())
            if written > 8*1024*1024:
                log_full = True
                GLib.idle_add(invalid, 'raw_error', 'Diagnostic event log reached 8 MiB bound')
                return False
            stream.write(line)
        return True

    def invalid(reason, detail=None):
        protocol.fail(reason)
        record(kind='invalid', reason=reason, detail=detail)
        (folder/'capture.done').touch()
        area.queue_draw()
        GLib.timeout_add_seconds(2, lambda: (loop.quit(), False)[1])
        return False

    def physical_reader():
        fd = None
        try:
            nodes = [p.parent.parent.name for p in Path('/sys/class/input').glob('event*/device/name')
                     if p.read_text().strip() == 'bottom_touchscreen']
            if len(nodes) != 1:
                raise RuntimeError('Cannot identify unique lower physical event node')
            node = '/dev/input/'+nodes[0]
            fd = os.open(node, os.O_RDONLY|os.O_NONBLOCK)
            info = array.array('i', [0]*6)
            fcntl.ioctl(fd, (2<<30)|(24<<16)|(ord('E')<<8)|(0x40+0x2f), info, True)
            slot, low, high = info[:3]
            if low != 0 or not 0 <= high < 32:
                raise RuntimeError('Unexpected Type-B slot bounds')
            initial = {i: {} for i in range(high+1)}
            for code, name in ((0x39, 'id'), (0x35, 'x'), (0x36, 'y')):
                values = array.array('i', [code]+[0]*(high+1))
                fcntl.ioctl(fd, (2<<30)|(len(values)*values.itemsize<<16)|(ord('E')<<8)|0x0a, values, True)
                for i, value in enumerate(values[1:]):
                    initial[i][name] = value
            state = SlotState(initial, slot)
            if any(v['id'] >= 0 for v in initial.values()):
                raise RuntimeError('Physical contacts already held at setup')
            record(kind='raw_ready', node=node, initial=initial, slot=slot,
                   realtime=time.time(), monotonic=time.monotonic())
            raw_ready.set()
            event, tail = struct.Struct('llHHi'), b''
            while running.is_set():
                if not select.select([fd], [], [], .2)[0]:
                    continue
                data = os.read(fd, 65536)
                if not data:
                    raise RuntimeError('Physical event stream closed')
                tail += data
                usable = len(tail)//event.size*event.size
                for offset in range(0, usable, event.size):
                    sec, usec, etype, code, value = event.unpack_from(tail, offset)
                    snapshot = state.feed(etype, code, value)
                    if snapshot is not None:
                        record(kind='raw', source=sec+usec/1e6, slots=snapshot)
                tail = tail[usable:]
        except Exception as error:
            GLib.idle_add(invalid, 'raw_error', repr(error))
        finally:
            if fd is not None:
                os.close(fd)

    def touch(_, event):
        nonlocal next_id
        sequence, kind = event.get_event_sequence(), event.type
        allocation = area.get_allocation()
        point = (event.x*1240/allocation.width, event.y*1080/allocation.height)
        if kind == Gdk.EventType.TOUCH_BEGIN:
            if event.y < 70:
                invalid('cancelled')
                return True
            if sequence in contacts or not raw_ready.is_set():
                invalid('raw_error', 'Duplicate begin or physical reader not ready')
                return True
            if protocol.phase == 'hold' and not contacts and math.dist(point, (260, fixed_y)) > 100:
                invalid('wrong_start')
                return True
            contacts[sequence] = next_id
            contact_begins[next_id] = time.monotonic()
            next_id += 1
            name = 'begin'
        elif kind == Gdk.EventType.TOUCH_UPDATE:
            name = 'move'
        elif kind == Gdk.EventType.TOUCH_END:
            name = 'end'
        else:
            name = 'cancel'
        tid = contacts.get(sequence)
        if tid is not None and name in ('begin', 'move'):
            positions[tid] = point
        record(kind='gtk', phase=name, tid=contacts.get(sequence), x=event.x,
               y=event.y, source_ms=event.get_time(), emulating_pointer=bool(event.touch.emulating_pointer))
        if kind in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            contacts.pop(sequence, None)
            positions.pop(tid, None)
            contact_begins.pop(tid, None)
        if name == 'cancel':
            invalid('cancelled')
        return True

    def label(cr, key, x, y, width, size, **values):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription(f'Sans {size}'))
        layout.set_width(width*Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_text(text(key, args.language, **values), -1)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    def draw(_, cr):
        allocation = area.get_allocation()
        cr.scale(allocation.width/1240, allocation.height/1080)
        cr.set_source_rgb(.025, .06, .09)
        cr.paint()
        cr.set_source_rgb(.9, .93, .96)
        label(cr, 'close', 32, 15, 1100, 23)
        label(cr, 'run', 32, 85, 1140, 28, target=args.target)
        values = dict(remaining=protocol.remaining(time.monotonic()), index=protocol.point_index+1)
        if protocol.phase == 'invalid':
            values['reason'] = text(protocol.reason, args.language)
        phase_label = 'add_stationary' if args.scan_mode == 'stationary' and protocol.phase == 'add' else protocol.phase
        if args.continuous_secondary and protocol.phase in ('add', 'goto_point'):
            phase_label = 'add_stationary_continuous' if protocol.phase == 'add' else 'goto_point_continuous'
        label(cr, phase_label, 32, 135, 1140, 27, **values)
        cr.new_path()
        cr.set_source_rgb(.3, .8, 1)
        cr.set_line_width(4)
        cr.arc(260, fixed_y, 35, 0, 6.283185)
        cr.stroke()
        cr.move_to(210, fixed_y)
        cr.line_to(310, fixed_y)
        cr.move_to(260, fixed_y-50)
        cr.line_to(260, fixed_y+50)
        cr.stroke()
        label(cr, 'fixed', 85, fixed_y+70, 420, 25)
        cr.set_source_rgb(1, .6, .2)
        cr.set_line_width(8)
        cr.move_to(950, 300)
        cr.line_to(950, 900)
        cr.stroke()
        for y in (300, 900):
            cr.arc(950, y, 16, 0, 6.283185)
            cr.fill()
        if args.scan_mode == 'stationary' and protocol.phase not in ('release_second', 'postbaseline', 'lift', 'done', 'invalid'):
            x, y = protocol.POINTS[protocol.point_index]
            cr.new_path()
            cr.set_source_rgba(1, .7, .15, .22)
            cr.arc(x, y, 65, 0, 6.283185)
            cr.fill()
            cr.set_source_rgb(1, .85, .3)
            cr.set_line_width(6)
            cr.arc(x, y, 42, 0, 6.283185)
            cr.stroke()
            cr.arc(x, y, 22, 0, 6.283185)
            cr.fill()
        second_label = ('continuous_secondary_label' if args.continuous_secondary else
                        'fixed_secondary' if args.scan_mode == 'stationary' else 'moving')
        label(cr, second_label, 720, 925, 490, 24)
        cr.set_source_rgb(.85, .9, .94)
        label(cr, 'note', 32, 1010, 1160, 21)
        return False

    def tick():
        nonlocal prior_phase, requested, captured
        now = time.monotonic()
        if protocol.phase == 'invalid':
            return True
        if (folder/'trace-failed').exists():
            return invalid('trace_error')
        states = [p.read_text().strip() for p in Path('/sys/class/drm').glob('card*-DSI-1/dpms')]
        if states != ['On']:
            return invalid('display_off', states)
        if raw_ready.is_set():
            protocol.step(now, list(contacts.values()), (folder/'trace-ready').exists(), positions=positions)
        if protocol.primary is not None and not requested:
            if not budget.start_active(now, observed_at=contact_begins.get(protocol.primary, now)):
                return invalid('waiting_timeout')
            (folder/'capture-request').write_text(json.dumps(dict(at=now, primary=protocol.primary,
                                                                  budgets=budget.metadata())))
            requested = True
        reason = budget.timeout_reason(now)
        if reason is not None:
            return invalid(reason)
        phase_key = (protocol.phase, protocol.point_index if args.scan_mode == 'stationary' else None)
        if phase_key != prior_phase:
            record(kind='phase', phase=protocol.phase, primary=protocol.primary,
                   secondary_ids=sorted(protocol.secondary_ids), target=args.target,
                   point_index=protocol.point_index+1 if args.scan_mode == 'stationary' else None,
                   point_target=protocol.POINTS[protocol.point_index] if args.scan_mode == 'stationary' else None,
                   fixed_secondary=protocol.fixed_secondary)
            prior_phase = phase_key
        status = dict(at=now, phase=protocol.phase, reason=protocol.reason,
                      primary=protocol.primary, contacts=len(contacts),
                      ids=list(contacts.values()), raw_ready=raw_ready.is_set(),
                      target=args.target, remaining=protocol.remaining(now), scan_mode=args.scan_mode,
                      point_index=protocol.point_index+1 if args.scan_mode == 'stationary' else None,
                      point_target=protocol.POINTS[protocol.point_index] if args.scan_mode == 'stationary' else None,
                      budgets=budget.metadata(), fixed_secondary=protocol.fixed_secondary)
        temporary = folder/'status.tmp'
        temporary.write_text(json.dumps(status))
        temporary.replace(folder/'status.json')
        if protocol.capture_should_stop and not captured:
            (folder/'capture.done').touch()
            captured = True
        if protocol.phase == 'done':
            GLib.timeout_add_seconds(1, lambda: (loop.quit(), False)[1])
            return False
        if protocol.phase == 'invalid':
            GLib.timeout_add_seconds(2, lambda: (loop.quit(), False)[1])
            return False
        area.queue_draw()
        return True

    area.connect('touch-event', touch)
    area.connect('draw', draw)
    window.connect('destroy', lambda *_: loop.quit())
    window.connect('map-event', lambda *_: record(kind='mapped', xid=window.get_window().get_xid()) or False)
    thread = threading.Thread(target=physical_reader, daemon=True)
    thread.start()
    window.show_all()
    record(kind='ready', pid=os.getpid(), display=args.display, language=args.language,
           target=args.target, fixed=(260, fixed_y), rail=(950, 300, 900),
           post_hold_seconds=args.post_hold_seconds,
           scan_mode=args.scan_mode,
           continuous_secondary=args.continuous_secondary,
           stationary_timing=dict(travel_seconds=6, hold_seconds=3, point_maximum_seconds=9) if args.scan_mode == 'stationary' else None,
           budgets=budget.metadata(),
           start_monotonic=start, wall_time=time.time())
    (folder/'ready').write_text(str(os.getpid()))
    GLib.timeout_add(50, tick)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (invalid('cancelled'), False)[1])
    try:
        loop.run()
    finally:
        running.clear()
        thread.join(timeout=1)
        window.destroy()
        record(kind='closed', phase=protocol.phase, reason=protocol.reason,
               primary=protocol.primary, secondary_ids=sorted(protocol.secondary_ids))
        stream.close()
        (folder/'capture.done').touch()
        (folder/'done').touch()


if __name__ == '__main__':
    main()
