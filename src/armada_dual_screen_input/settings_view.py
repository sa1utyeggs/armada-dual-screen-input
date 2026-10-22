"""Focus-free settings surface using the same logical hit rectangles as input."""
from .i18n import msg
from . import steam_style as s
import math
from .input_settings import BOOLEANS, CHOICES, NUMBERS, SETTINGS_PAGES, choice_caption, color_swatches
from .marker_colors import COLOR_SETTINGS, COLOR_PRESETS, color_rgb

TITLES = {"mouse": msg('settings.mouse'), "position": msg('common.touch'), "keyboard": msg('settings.keyboard'), "updates": msg('settings.updates'),
          "general": msg("settings.general")}
TOGGLES = {
    "tap_to_click": (msg('settings.tap'), msg('settings.tap_note')),
    "glide": (msg('settings.glide'), msg('settings.glide_note')),
    "keyboard_repeat_enabled": (msg('settings.repeat'), msg('settings.repeat_note')),
}
CHOICE_LABELS = {
    "ui_language": (msg("settings.ui_language"), msg("settings.ui_language_note")),
    'keyboard_language': (msg('settings.input_language'), msg('settings.input_language_note')),
    'marker_frame_rate': (msg('settings.fps'), msg('settings.fps_note')),
}
COLOR_LABELS = {'marker_idle_color': msg('settings.idle_color'),
                'marker_pressed_color': msg('settings.pressed_color')}


def draw(cr, draft, updates=None, *, monitor_millihz=0, uninstall=None):
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('common.settings'), 28, 150, 34, bold=True)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('settings.update_instructions') if draft.section == 'updates'
            else msg('settings.instructions'), 28, 194, 22)
    for index, section in enumerate(SETTINGS_PAGES):
        s.button(cr, 24 + index * 204, 220, 192, 60,
                 TITLES[section], draft.section == section, tab=True)
    if draft.section == 'updates':
        draw_updates(cr, draft, updates, blocked=bool(uninstall and uninstall.busy))
        return
    for key, top in draft.rows():
        s.rounded(cr, 24, top, 1192, 88, 8, s.SURFACE)
        if key in COLOR_SETTINGS:
            value = draft.values[key]
            caption = dict(COLOR_PRESETS).get(value, msg('common.custom'))
            cr.set_source_rgb(*s.FG)
            s.label(cr, COLOR_LABELS[key], 44, top+12, 26, max_width=490)
            cr.set_source_rgb(*s.MUTED)
            s.label(cr, msg('settings.palette', caption=caption, value=value), 44, top+55, 21, max_width=550)
            for left, color, _ in color_swatches():
                s.button(cr, left, top+14, 60, 60, '', value == color)
                for width, rgb in ((6, (0,0,0)), (3, color_rgb(color))):
                    cr.set_line_width(width)
                    cr.set_source_rgb(*rgb)
                    cr.new_sub_path()
                    cr.arc(left+30, top+44, 16, 0, math.tau)
                    cr.stroke()
            continue
        if key in CHOICES:
            title, note = CHOICE_LABELS[key]
            cr.set_source_rgb(*s.FG)
            s.label(cr, title, 44, top + 12, 26)
            cr.set_source_rgb(*s.MUTED)
            s.label(cr, note, 44, top + 55, 21, max_width=700)
            s.button(cr, 790, top + 12, 402, 64,
                     choice_caption(key, draft.values[key], monitor_millihz), True)
            continue
        spec = NUMBERS.get(key)
        title, note = (spec.label, spec.note) if spec else TOGGLES[key]
        cr.set_source_rgb(*s.FG)
        s.label(cr, title, 44, top + 12, 26, max_width=490)
        cr.set_source_rgb(*s.MUTED)
        s.label(cr, note, 44, top + 55, 21, max_width=490)
        value = draft.values[key]
        if key in BOOLEANS:
            s.button(cr, 900, top + 12, 292, 64, msg('common.on') if value else msg('common.off'), value)
            continue
        s.button(cr, 552, top + 20, 60, 60, "−")
        s.button(cr, 1000, top + 20, 60, 60, "+")
        ratio = max(0., min(1., (value - spec.low) / (spec.high - spec.low)))
        s.line(cr, 644, top + 50, 968, top + 50, s.BORDER, 8)
        s.line(cr, 644, top + 50, 644 + 324 * ratio, top + 50, s.ACCENT, 8)
        s.rounded(cr, 634 + 324 * ratio, top + 35, 20, 30, 9, s.FG)
        cr.set_source_rgb(*s.ACCENT)
        s.label(cr, spec.display(value), 1134, top + 49, 25, centered=True, max_width=126)
    if draft.section == "general":
        cr.set_source_rgb(*s.MUTED)
        s.label(cr, msg("settings.general_note"), 44, 460, 25, max_width=1140)
        draw_uninstall(cr, draft, uninstall, updates)
    if draft.section == "position":
        cr.set_source_rgb(*s.MUTED)
        for text, y in ((msg('settings.touch_idle'), 730),
                        (msg('settings.touch_gesture'), 780),
                        (msg('settings.touch_style'), 830),
                        (msg('settings.touch_scope'), 880)):
            s.label(cr, text, 44, y, 25, max_width=1140)
    cr.set_source_rgb(*(s.DANGER if draft.error else s.ACCENT if draft.dirty else s.MUTED))
    s.label(cr, draft.message, 28, 934, 24, max_width=1180)
    s.button(cr, 24, 996, 270, 64, msg('settings.defaults'))
    s.button(cr, 662, 996, 250, 64, msg('settings.discard'))
    s.button(cr, 936, 996, 280, 64, msg('settings.save'), True)


def draw_updates(cr, draft, updates, *, blocked=False):
    s.rounded(cr, 24, 310, 1192, 380, 8, s.SURFACE)
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('app.name'), 44, 342, 34, bold=True)
    cr.set_source_rgb(*s.MUTED)
    current = updates.current if updates else msg('common.unknown')
    latest = updates.latest.tag if updates and updates.latest else msg('update.not_checked')
    for text, y in ((msg('update.current_version', current=current), 410), (msg('update.latest_version', latest=latest), 465),
                    (msg('update.source'), 520)):
        s.label(cr, text, 44, y, 26, max_width=1120)
    message = updates.message if updates else msg('update.unavailable')
    cr.set_source_rgb(*(s.DANGER if updates and updates.phase == 'error' else s.ACCENT))
    s.label(cr, message, 44, 590, 25, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    if draft.dirty:
        note = msg('update.unsaved')
    elif updates and not updates.managed:
        note = msg('update.source_only')
    elif updates and updates.confirming:
        note = msg('update.confirm_note')
    else:
        note = msg('update.manual_note')
    s.label(cr, note, 44, 708, 23, max_width=1140)
    can_check = bool(updates and not updates.busy and not blocked)
    can_install = bool(updates and updates.available and not draft.dirty and not blocked)
    s.button(cr, 44, 760, 520, 76, msg('update.check') if can_check else msg('update.busy'), can_check)
    caption = (msg('update.confirm') if updates and updates.confirming else msg('update.to', tag=updates.latest.tag)
               if updates and updates.latest and can_install else msg('common.update'))
    s.button(cr, 620, 760, 572, 76, caption, can_install)
    if updates and updates.confirming:
        s.button(cr, 620, 850, 572, 64, msg('common.cancel'))


def draw_uninstall(cr, draft, uninstall, updates=None):
    s.rounded(cr, 24, 520, 1192, 374, 8, s.SURFACE)
    confirming = bool(uninstall and uninstall.confirming)
    busy = bool(uninstall and uninstall.busy)
    managed = bool(uninstall and uninstall.managed)
    blocked = bool(draft.dirty or (updates and updates.busy))
    enabled = managed and not busy and not blocked and uninstall.phase != 'success'
    cr.set_source_rgb(*s.DANGER)
    s.label(cr, msg('uninstall.confirm_title' if confirming else 'uninstall.title'),
            44, 548, 30, bold=True, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('uninstall.scope'), 44, 600, 24, max_width=1120)
    s.label(cr, msg('uninstall.keep'), 44, 644, 24, max_width=1120)
    message = (msg('uninstall.managed_only') if not managed else
               msg('uninstall.unsaved') if draft.dirty else
               msg('uninstall.update_busy') if updates and updates.busy else uninstall.message)
    cr.set_source_rgb(*(s.DANGER if uninstall and uninstall.phase == 'error' else s.MUTED))
    s.label(cr, message, 44, 690, 22, max_width=1120)
    if confirming:
        s.button(cr, 44, 742, 520, 68, msg('common.cancel'))
        s.button(cr, 620, 742, 572, 68, msg('uninstall.confirm'), enabled, danger=True)
    else:
        s.button(cr, 44, 742, 520, 68, msg('update.busy') if busy else msg('uninstall.title'),
                 enabled, danger=True)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('uninstall.record'), 44, 850, 20, max_width=1120)
