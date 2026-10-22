"""Touch submode dropdown, drawn inside the existing panel without taking focus."""
from .i18n import msg
from .input_geometry import Rect

BUTTON = Rect(572, 8, 212, 64)
MENU = Rect(572, 82, 212, 140)
OPTIONS = (
    ('position', msg('touch.position'), Rect(576, 86, 204, 64)),
    ('direct', msg('touch.direct'), Rect(576, 154, 204, 64)),
)
# The selector lives in the header, so it needs no second row or reserved pad area.
PAD = Rect(0, 124, 1240, 956)


def hit_option(x, y):
    return next((mode for mode, _, rect in OPTIONS if rect.contains(x, y)), None)


def draw_button(cr, selected, opened=False):
    from . import steam_style as style

    r = BUTTON
    style.rounded(cr, r.x, r.y, r.width, r.height, 5,
                  style.KEY_LATCHED if opened else style.KEY_MOD, style.BORDER)
    label = next(label for mode, label, _ in OPTIONS if mode == selected)
    cr.set_source_rgb(*style.FG)
    style.label(cr, label, r.x+(r.width-28)/2, r.y+r.height/2,
                25, max_width=r.width-50, centered=True)
    cx, cy = r.x+r.width-20, r.y+r.height/2
    cr.move_to(cx-6, cy+(3 if opened else -3))
    cr.line_to(cx+6, cy+(3 if opened else -3))
    cr.line_to(cx, cy+(-4 if opened else 4))
    cr.close_path()
    cr.fill()


def draw_menu(cr, selected):
    from . import steam_style as style

    r = MENU
    style.rounded(cr, r.x, r.y, r.width, r.height, 6, style.PANEL, style.BORDER, 2)
    for mode, label, rect in OPTIONS:
        style.button(cr, rect.x, rect.y, rect.width, rect.height,
                     label, mode == selected)
