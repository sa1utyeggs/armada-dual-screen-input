"""Steam-like dark visuals for the Thor adapter; rendering only.

The palette is an original approximation of Steam's default dark keyboard.
No Valve assets are copied. Input rectangles and key codes stay in the existing
layout. Flat fills avoid extra animation, blur or compositor dependencies.
"""
from __future__ import annotations

from .i18n import msg
from .power_status import battery_label

import math

from .text_render import draw_text


def color(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


BG = color("#171a21")
PANEL = color("#1b2029")
SURFACE = color("#202630")
KEY = color("#343b46")
KEY_MOD = color("#292f39")
KEY_PRESSED = color("#1a9fff")
KEY_LATCHED = color("#285f85")
BORDER = color("#454d59")
FG = color("#f1f3f5")
MUTED = color("#9ba7b7")
ACCENT = color("#1a9fff")
SUBTLE = color("#303946")
DANGER = color("#e4a0a6")
GOOD = color("#a1c77d")


def rounded(cr, x, y, w, h, r, fill, border=None, border_width=1.0):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, math.pi * 1.5)
    cr.close_path()
    cr.set_source_rgb(*fill)
    cr.fill_preserve()
    if border is not None:
        cr.set_source_rgb(*border)
        cr.set_line_width(border_width)
        cr.stroke()
    else:
        cr.new_path()


def label(cr, text, x, y, size, *, bold=False, max_width=None, centered=False):
    return draw_text(cr, text, x, y, size, bold=bold,
                     max_width=max_width, centered=centered)


def line(cr, x1, y1, x2, y2, tone=SUBTLE, width=1.0):
    cr.set_source_rgb(*tone)
    cr.set_line_width(width)
    cr.move_to(x1, y1)
    cr.line_to(x2, y2)
    cr.stroke()


def button(cr, x, y, w, h, text, active=False, *, tab=False, danger=False):
    fill = KEY_LATCHED if active else PANEL if tab else KEY_MOD
    rounded(cr, x, y, w, h, 5, fill)
    if tab and active:
        rounded(cr, x + 14, y + h - 5, w - 28, 3, 1, ACCENT)
    cr.set_source_rgb(*(DANGER if danger else FG if active else MUTED))
    label(cr, text, x + w / 2, y + h / 2 - (2 if tab else 0),
          25, bold=active, max_width=w - 14, centered=True)


def draw_header(app, cr, buttons, y, h, width):
    cr.set_source_rgb(*PANEL)
    cr.rectangle(0, 0, width, 80)
    cr.fill()
    for key, x, w in buttons:
        if app.mode == "preferences" and key in ("left", "right"):
            continue
        text, active, _ = app._header_button_look(key)
        button(cr, x, y, w, h, text, active and key != "close",
               tab=key in ("trackpad", "split", "position", "preferences"),
               danger=key == "close")
    line(cr, 0, 79.5, width, 79.5)


def draw_status(app, cr, y, h, width):
    stats = app.stats.get_stats()
    cr.set_source_rgb(*PANEL)
    cr.rectangle(0, y, width, h)
    cr.fill()
    items = [
        (battery_label(stats), GOOD),
        (f"CPU {stats.get('cpu_load', 0)}%  {stats.get('cpu_temp', 0)}°C", MUTED),
        (f"GPU {stats.get('gpu_mhz', 0)}MHz  {stats.get('gpu_temp', 0)}°C", MUTED),
        (f"RAM {stats.get('ram_used_gb', 0)}/{stats.get('ram_total_gb', 0)}GB", MUTED),
        (msg('status.muted') if stats.get('vol_muted') else msg('status.volume', value=stats.get('vol_pct', 0)), MUTED),
        (msg('status.brightness', top=stats.get('top_bright_pct', 100), bottom=stats.get('bot_bright_pct', 100)), MUTED),
    ]
    x = 16
    cy = y + h / 2
    # Give temperatures and memory more room without shrinking every label.
    weights = (252, 212, 244, 214, 140, 178)
    for i, ((text, tone), weight) in enumerate(zip(items, weights)):
        cell_w = (width - 32) * weight / sum(weights)
        cr.set_source_rgb(*tone)
        label(cr, text, x + cell_w / 2, cy, 22, max_width=cell_w - 18, centered=True)
        if i != len(items) - 1:
            line(cr, x + cell_w, cy - 9, x + cell_w, cy + 9)
        x += cell_w
    line(cr, 0, y + h - 0.5, width, y + h - 0.5)


def mouse_outline(cr, cx, cy, size):
    rounded(cr, cx - size * 0.34, cy - size * 0.5,
            size * 0.68, size, size * 0.28, SURFACE, MUTED, 2.2)
    line(cr, cx, cy - size * 0.5, cx, cy - size * 0.04, MUTED, 2)
    line(cr, cx - size * 0.32, cy - size * 0.04,
         cx + size * 0.32, cy - size * 0.04, MUTED, 2)
    rounded(cr, cx - 2, cy - size * 0.31, 4, size * 0.14, 2, ACCENT)


def draw_trackpad(app, cr, y, h, width):
    x, top, w, height = 20, y + 20, width - 40, h - 40
    rounded(cr, x, top, w, height, 12, SURFACE, SUBTLE)
    cr.set_source_rgb(*MUTED)
    label(cr, msg('header.pad'), x + 24, top + 19, 22, max_width=180)
    compact = height < 400
    cy = top + height * (0.38 if compact else 0.43)
    mouse_outline(cr, width / 2, cy, 44 if compact else 62)
    cr.set_source_rgb(*FG)
    label(cr, msg('pad.move'), width / 2, cy + (47 if compact else 65),
          28 if compact else 34, max_width=w - 50, centered=True)
    cr.set_source_rgb(*MUTED)
    label(cr, msg('pad.gestures'), width / 2,
          cy + (86 if compact else 111), 22 if compact else 24,
          max_width=w - 60, centered=True)
    if not compact:
        line(cr, x + 26, top + height - 68, x + w - 26, top + height - 68)
        cr.set_source_rgb(*MUTED)
        label(cr, msg('pad.drag'), width / 2,
              top + height - 34, 22, max_width=w - 70, centered=True)


def draw_monitor(app, cr, top, width, height):
    stats = app.stats.get_stats()
    cr.set_source_rgb(*FG)
    label(cr, msg('monitor.title'), 28, top + 30, 34, bold=True, max_width=400)
    cr.set_source_rgb(*MUTED)
    label(cr, msg('monitor.readonly'), width - 105, top + 50, 22, max_width=150, centered=True)
    cards = [
        ("CPU", f"{stats.get('cpu_load', 0)}%", msg('monitor.temp', value=stats.get('cpu_temp', 0))),
        ("GPU", f"{stats.get('gpu_mhz', 0)} MHz", msg('monitor.temp', value=stats.get('gpu_temp', 0))),
        (msg('monitor.memory'), f"{stats.get('ram_used_gb', 0)} GB", msg('monitor.total', value=stats.get('ram_total_gb', 0))),
        (msg('monitor.battery'), battery_label(stats), msg('monitor.charging') if stats.get('bat_status', '').lower() == "charging" else msg('monitor.charge')),
        (msg('monitor.volume'), msg('monitor.muted') if stats.get('vol_muted') else f"{stats.get('vol_pct', 0)}%", msg('monitor.system_volume')),
        (msg('monitor.brightness'), f"{stats.get('top_bright_pct', 100)} / {stats.get('bot_bright_pct', 100)}%", msg('monitor.screens')),
    ]
    gap, margin = 20, 24
    card_w = (width - margin * 2 - gap) / 2
    card_h = (height - top - 190) / 3
    for i, (title, value, note) in enumerate(cards):
        x = margin + i % 2 * (card_w + gap)
        y = top + 108 + i // 2 * (card_h + gap)
        rounded(cr, x, y, card_w, card_h, 10, SURFACE, SUBTLE)
        cr.set_source_rgb(*MUTED)
        label(cr, title, x + 24, y + 20, 23, max_width=card_w - 48)
        cr.set_source_rgb(*FG)
        label(cr, value, x + 24, y + 63, 47, max_width=card_w - 48)
        cr.set_source_rgb(*MUTED)
        label(cr, note, x + 24, y + card_h - 47, 23, max_width=card_w - 48)
    cr.set_source_rgb(*MUTED)
    label(cr, msg('monitor.control'), width / 2, height - 26,
          22, max_width=width - 60, centered=True)


def draw_collapsed(cr, width, height):
    cr.set_source_rgb(*PANEL)
    cr.paint()
    line(cr, 0, 0.5, width, 0.5, SUBTLE)
    rounded(cr, 16, height / 2 - 12, 4, 24, 2, ACCENT)
    cr.set_source_rgb(*FG)
    label(cr, msg('app.name'), 34, height / 2 - 11, 22, max_width=width - 150)
    cr.set_source_rgb(*MUTED)
    label(cr, msg('header.expand'), width - 64, height / 2, 20, max_width=100, centered=True)
