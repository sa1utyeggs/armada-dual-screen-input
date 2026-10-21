"""Shared drawing/hit geometry for the touch page's secondary tabs."""
from .input_geometry import Rect

TABS = (
    ('position', '定位', Rect(20, 136, 596, 56)),
    ('direct', '直接触屏', Rect(624, 136, 596, 56)),
)
CONTENT_TOP = 240
PAD = Rect(0, CONTENT_TOP, 1240, 1080-CONTENT_TOP)


def hit(x, y):
    return next((mode for mode, _, rect in TABS if rect.contains(x, y)), None)


def draw(cr, selected):
    from . import steam_style

    for mode, label, rect in TABS:
        steam_style.button(cr, rect.x, rect.y, rect.width, rect.height,
                           label, mode == selected, tab=True)
