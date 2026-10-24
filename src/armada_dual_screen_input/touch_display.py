"""Optional, passive finger illustrations of actual lower-panel contacts.

Consumes ToolkitTouch snapshots only; no timers, devices, focus or input output.
The caller repaints returned old/new bounds and paints after its normal UI.
"""
from __future__ import annotations

import math


def input_region(mode, *, header, split, width, height, candidate_top=None,
                 hidden=False, collapsed=False, menu_open=False):
    """Keep illustrations inside the visible pointer/touch input surface."""
    if hidden or collapsed or menu_open or mode not in ('trackpad', 'split', 'position'):
        return None
    bottom = min(split, candidate_top) if mode == 'split' and candidate_top is not None else (
        split if mode == 'split' else height)
    return (0, header, width, max(0, bottom-header))


def bounds(point):
    x, y = point
    # Includes the contact halo, finger outline and antialiasing/shadow margin.
    return (x-28, y-28, 92, 114)


class TouchDisplay:
    def __init__(self):
        self.points = {}
        self.region = None

    def sync(self, contacts, owners, region, *, enabled):
        points = {}
        if enabled and region is not None:
            left, top, width, height = region
            for contact in contacts:
                x, y = contact.x, contact.y
                if (owners.get(contact.tid) in ('trackpad', 'position')
                        and math.isfinite(x) and math.isfinite(y)
                        and left <= x < left+width and top <= y < top+height):
                    points[contact.tid] = (x, y)
        dirty = []
        for tid in self.points.keys() | points.keys():
            before, after = self.points.get(tid), points.get(tid)
            if before != after or self.region != region:
                dirty.extend(bounds(point) for point in (before, after) if point is not None)
        self.points, self.region = points, region if enabled else None
        return dirty

    def clear(self):
        return self.sync((), {}, None, enabled=False)

    def draw(self, cr):
        if not self.points or self.region is None:
            return
        cr.save()
        cr.rectangle(*self.region)
        cr.clip()
        for point in self.points.values():
            draw_finger(cr, *point)
        cr.restore()


def draw_finger(cr, x, y):
    """A vector fingertip at the exact contact, with a translucent hand below."""
    cr.save()
    cr.translate(x, y)
    cr.set_line_width(3)
    cr.set_source_rgba(0.12, 0.72, 1., .28)
    cr.arc(0, 0, 22, 0, math.tau)
    cr.fill_preserve()
    cr.set_source_rgba(.48, .86, 1., .94)
    cr.stroke()
    cr.new_path()
    cr.move_to(-9, 24)
    cr.line_to(-9, 0)
    cr.curve_to(-9, -12, 10, -12, 10, 0)
    cr.line_to(10, 23)
    cr.curve_to(10, 12, 25, 12, 25, 25)
    cr.curve_to(27, 16, 40, 19, 39, 30)
    cr.curve_to(44, 23, 53, 29, 51, 40)
    cr.line_to(49, 55)
    cr.curve_to(47, 78, 17, 80, 6, 61)
    cr.line_to(-13, 35)
    cr.curve_to(-20, 22, -12, 16, -9, 24)
    cr.close_path()
    cr.set_source_rgba(.91, .96, 1., .78)
    cr.fill_preserve()
    cr.set_source_rgba(.025, .055, .09, .95)
    cr.set_line_width(3)
    cr.stroke()
    cr.move_to(10, 28)
    cr.line_to(10, 42)
    cr.move_to(25, 29)
    cr.line_to(25, 43)
    cr.move_to(39, 34)
    cr.line_to(38, 46)
    cr.set_source_rgba(.10, .23, .32, .65)
    cr.set_line_width(2)
    cr.stroke()
    cr.restore()
