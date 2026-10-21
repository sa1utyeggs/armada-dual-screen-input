"""Logical dirty regions; never alter touch coordinates or input timing."""
from __future__ import annotations


def clip_regions(cr):
    """Keep disjoint GTK damage rectangles separate, with a safe fallback."""
    try:
        return tuple(tuple(rect) for rect in cr.copy_clip_rectangle_list())
    except Exception:
        # Cairo cannot express every transformed clip as rectangles. Falling
        # back to its bounding box may paint extra content, never omit pixels.
        left, top, right, bottom = cr.clip_extents()
        return ((left, top, right-left, bottom-top),)


def intersects(regions, rect):
    x, y, width, height = rect
    return any(x < left+w and x+width > left and y < top+h and y+height > top
               for left, top, w, h in regions if w > 0 and h > 0)


def ring_damage(old, new, pad):
    """Cover old/new circles, their stroke and antialiasing, in panel units."""
    changed = set(old).symmetric_difference(new)
    return tuple((pad.x+u*pad.width-28, pad.y+v*pad.height-28, 56, 56)
                 for u, v, _ in sorted(changed))
