"""Steam-inspired keycaps drawn inside the existing keyboard hit rectangles.

This module is deliberately presentation-only: the layout, keycodes, modifier
state, and touch handling remain owned by the panel's existing input code.
"""
from __future__ import annotations

from math import pi

from . import steam_style as style
_SHADOW = (0.055, 0.065, 0.083)
_RADIUS = 6.0
_MODIFIER_CODES = {1, 14, 15, 28, 29, 42, 54, 56, 103, 105, 106, 108, 125}


def _source(cr, color) -> None:
    cr.set_source_rgb(*color)


def _modifier_latched(layout, key, shift_on: bool) -> bool:
    if key.special == "shift":
        return shift_on
    if key.special in ("ctrl", "alt", "super"):
        return bool(getattr(layout, f"{key.special}_active", False))
    return False


def _arrow(cr, cx: float, cy: float, size: float, code: int) -> None:
    """Use the same left-pointing stroke, rotated for the other directions."""
    rotation = {105: 0.0, 103: pi / 2.0, 106: pi, 108: -pi / 2.0}[code]
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(rotation)
    cr.move_to(size, 0)
    cr.line_to(-size, 0)
    cr.move_to(-size * 0.2, -size * 0.8)
    cr.line_to(-size, 0)
    cr.line_to(-size * 0.2, size * 0.8)
    cr.stroke()
    cr.restore()


def _icon(cr, key, cx: float, cy: float, caps_lock: bool) -> bool:
    """Render font-independent editing icons; return False for text keys."""
    code = key.code
    if code not in (14, 28, 42, 54, 103, 105, 106, 108):
        return False
    size = min(16.0, key.w * 0.22, key.h * 0.19)
    cr.save()
    cr.set_line_width(2.2)
    cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
    cr.set_line_join(1)  # cairo.LINE_JOIN_ROUND
    cr.new_path()
    if code in (103, 105, 106, 108):
        _arrow(cr, cx, cy, size, code)
    elif code == 14:
        # Backspace: outlined key and a cross, readable at small output sizes.
        cr.move_to(cx - size * 1.15, cy)
        cr.line_to(cx - size * 0.45, cy - size * 0.72)
        cr.line_to(cx + size * 1.05, cy - size * 0.72)
        cr.line_to(cx + size * 1.05, cy + size * 0.72)
        cr.line_to(cx - size * 0.45, cy + size * 0.72)
        cr.close_path()
        cr.move_to(cx - size * 0.08, cy - size * 0.28)
        cr.line_to(cx + size * 0.48, cy + size * 0.28)
        cr.move_to(cx + size * 0.48, cy - size * 0.28)
        cr.line_to(cx - size * 0.08, cy + size * 0.28)
        cr.stroke()
    elif code == 28:
        # Enter: the familiar return stroke without depending on a glyph font.
        cr.move_to(cx + size, cy - size * 0.75)
        cr.line_to(cx + size, cy + size * 0.15)
        cr.line_to(cx - size, cy + size * 0.15)
        cr.move_to(cx - size * 0.25, cy - size * 0.55)
        cr.line_to(cx - size, cy + size * 0.15)
        cr.line_to(cx - size * 0.25, cy + size * 0.85)
        cr.stroke()
    else:
        # Shift remains the same key when locked; the underline denotes Caps.
        cr.move_to(cx, cy - size)
        cr.line_to(cx + size, cy)
        cr.line_to(cx + size * 0.45, cy)
        cr.line_to(cx + size * 0.45, cy + size * 0.8)
        cr.line_to(cx - size * 0.45, cy + size * 0.8)
        cr.line_to(cx - size * 0.45, cy)
        cr.line_to(cx - size, cy)
        cr.close_path()
        cr.stroke()
        if caps_lock:
            cr.move_to(cx - size * 0.45, cy + size * 1.15)
            cr.line_to(cx + size * 0.45, cy + size * 1.15)
            cr.stroke()
    cr.new_path()
    cr.restore()
    return True


def _labels(cr, key, shift_on: bool, pressed: bool, caps_lock: bool) -> None:
    cx = key.x + key.w / 2.0
    cy = key.y + (key.h - 2.0) / 2.0
    _source(cr, style.FG)
    if _icon(cr, key, cx, cy, caps_lock):
        return

    if key.has_sub_symbol:
        main, secondary = (key.shift_label, key.label) if shift_on else (key.label, key.shift_label)
        size = min(36.0, key.h * 0.35, key.w * 0.49)
        style.label(cr, main, cx, cy, size, max_width=key.w - 14.0, centered=True)
        _source(cr, style.FG if pressed else style.MUTED)
        style.label(cr, secondary, key.x + key.w - 14.0, key.y + 18.0,
                    min(17.0, key.h * 0.19), max_width=key.w * 0.3, centered=True)
        return

    text = key.shift_label if shift_on and key.is_letter else key.label
    size = min(36.0, key.h * 0.35, key.w * 0.49) if len(text) == 1 else min(24.0, key.h * 0.28)
    style.label(cr, text, cx, cy, size, max_width=key.w - 14.0, centered=True)


def draw_keyboard(app, cr) -> None:
    """Paint every key using its unmodified input rectangle and current flags."""
    layout = app.kb_layout
    shift_on = bool(layout.shift_active or layout.caps_lock)
    caps_lock = bool(layout.caps_lock)
    feedback = getattr(app,'key_feedback',None)
    pressed_codes = feedback.visible if feedback is not None else {app.active_key_press}
    left,top,right,bottom = cr.clip_extents()
    cr.save()
    for row in layout.rows:
        for key in row:
            if key.x+key.w <= left or key.x >= right or key.y+key.h <= top or key.y >= bottom:
                continue
            pressed = key.code in pressed_codes
            latched = _modifier_latched(layout, key, shift_on)
            if key.special == "language":
                latched = getattr(getattr(app, "languages", None), "language", "en_US") == "zh_CN"
            modifier = key.is_modifier or key.code in _MODIFIER_CODES
            fill = (style.KEY_PRESSED if pressed else style.KEY_LATCHED if latched
                    else style.KEY_MOD if modifier else style.KEY)

            # The shallow shadow and cap both stay inside the input rectangle.
            x, y, w, h = key.x + 0.7, key.y + 0.6, key.w - 1.4, key.h - 1.2
            style.rounded(cr, x, y + 2.0, w, h - 2.0, _RADIUS, _SHADOW)
            style.rounded(cr, x, y, w, h - 2.0, _RADIUS, fill,
                          border=style.ACCENT if pressed else style.BORDER, border_width=0.8)
            _labels(cr, key, shift_on, pressed, caps_lock)

            if latched:
                _source(cr, style.FG if pressed else style.ACCENT)
                cr.new_path()
                cr.arc(key.x + key.w - 11.0, key.y + key.h - 12.0, 2.6, 0, 2.0 * pi)
                cr.fill()
    cr.restore()
