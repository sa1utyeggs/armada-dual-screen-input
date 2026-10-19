"""Pango/Cairo text drawing with Chinese font fallback.

This module does not initialize GTK, connect to a display, or create input
devices, so labels can also be checked on an offscreen image surface.
"""
from __future__ import annotations

import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo


def make_layout(cr, text: str, size: float, *, bold: bool = False, max_width: float | None = None):
    layout = PangoCairo.create_layout(cr)
    layout.get_context().set_language(Pango.Language.from_string("zh-cn"))
    layout.set_single_paragraph_mode(True)
    layout.set_text(text, -1)
    font = Pango.FontDescription()
    font.set_family("Noto Sans CJK SC, Sans")
    font.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    font.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(font)
    ink, logical = layout.get_pixel_extents()
    width = max(ink.width, logical.width)
    if max_width is not None and 0 < max_width < width:
        font.set_absolute_size(size * max(1.0, max_width - 1.0) / width * Pango.SCALE)
        layout.set_font_description(font)
    return layout


def draw_text(cr, text: str, x: float, y: float, size: float, *, bold: bool = False,
              max_width: float | None = None, centered: bool = False):
    """Draw using the current source colour, aligning by the actual ink box."""
    layout = make_layout(cr, text, size, bold=bold, max_width=max_width)
    ink, _ = layout.get_pixel_extents()
    if centered:
        cr.move_to(x - ink.x - ink.width / 2.0, y - ink.y - ink.height / 2.0)
    else:
        cr.move_to(x - ink.x, y - ink.y)
    PangoCairo.show_layout(cr, layout)
    return layout
