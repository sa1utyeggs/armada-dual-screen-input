"""Focus-free settings surface using the same logical hit rectangles as input."""
from .i18n import msg
from . import steam_style as s
from functools import lru_cache
from .input_settings import (BOOLEANS, CHOICES, NUMBERS, settings_tabs, choice_caption,
                             position_preview_top, row_height, marker_style_tiles,
                             GENERAL_UPDATE_BUTTON_TOP, GENERAL_UNINSTALL_BUTTON_TOP,
                             GENERAL_ACTION_HEIGHT)
from .marker_colors import MarkerColors

TITLES = {"mouse": msg('settings.mouse'), "position": msg('common.touch'), "keyboard": msg('settings.keyboard'),
          "general": msg("settings.general"), 'driver': msg('driver.tab')}
TOGGLES = {
    "tap_to_click": (msg('settings.tap'), msg('settings.tap_note')),
    "glide": (msg('settings.glide'), msg('settings.glide_note')),
    "keyboard_repeat_enabled": (msg('settings.repeat'), msg('settings.repeat_note')),
    "touch_display_mode": (msg('settings.touch_display'), msg('settings.touch_display_note')),
}
CHOICE_LABELS = {
    "ui_language": (msg("settings.ui_language"), msg("settings.ui_language_note")),
    'keyboard_language': (msg('settings.input_language'), msg('settings.input_language_note')),
    'marker_frame_rate': (msg('settings.fps'), msg('settings.fps_note')),
    'position_marker_style': (msg('settings.position_marker_style'), msg('settings.position_marker_style_note')),
}


def draw(cr, draft, updates=None, *, monitor_millihz=0, uninstall=None, driver=None):
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('common.settings'), 28, 150, 34, bold=True)
    cr.set_source_rgb(*(s.DANGER if draft.error else s.ACCENT if draft.dirty else s.MUTED))
    s.label(cr, draft.message if draft.section == 'general' else
            msg('driver.component_note') if draft.section == 'driver'
            else msg('settings.instructions'), 28, 194, 22)
    for section, left, width in settings_tabs():
        s.button(cr, left, 220, width, 60,
                 TITLES[section], draft.section == section, tab=True)
    if draft.section == 'driver':
        draw_driver(cr, draft, driver, blocked=bool((updates and updates.busy) or
                                                   (uninstall and uninstall.busy)))
        return
    for key, top in draft.rows():
        s.rounded(cr, 24, top, 1192, row_height(key), 8, s.SURFACE)
        if key == 'position_marker_style':
            draw_marker_style_tiles(cr, draft, top)
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
        s.label(cr, msg("settings.general_note"), 44, 410, 21, max_width=1140)
        draw_updates(cr, draft, updates, blocked=bool((uninstall and uninstall.busy) or
                                                    (driver and driver.busy)))
        draw_uninstall(cr, draft, uninstall, updates, blocked=bool(driver and driver.busy))
    if draft.section == "position":
        cr.set_source_rgb(*s.MUTED)
        top = position_preview_top(draft)
        for text, y in ((msg('settings.touch_gesture'), top+30),
                        (msg('settings.touch_style'), top+76)):
            s.label(cr, text, 390, y, 21, max_width=802)
    if draft.section != 'general':
        cr.set_source_rgb(*(s.DANGER if draft.error else s.ACCENT if draft.dirty else s.MUTED))
        s.label(cr, draft.message, 28, 934, 24, max_width=1180)
    s.button(cr, 24, 996, 270, 64, msg('settings.defaults'))
    s.button(cr, 662, 996, 250, 64, msg('settings.discard'))
    s.button(cr, 936, 996, 280, 64, msg('settings.save'), True)


@lru_cache(maxsize=16)
def _preview_appearance(style, idle, pressed):
    # Resolve bundled pixels only on this settings page. Repainting an
    # unchanged draft never decodes or rescales the source artwork again.
    from .marker_appearance import load_appearance
    try:
        appearance = load_appearance(style, colors=MarkerColors(idle, pressed))
        expected = 'ring' if style.startswith('ring') else style
        return appearance if appearance.style == expected else None
    except (OSError, ValueError, RuntimeError):
        return None


def marker_preview_transform(appearance, center_x, center_y, *, pressed=False):
    """Center visible artwork; runtime touch hotspots are irrelevant here."""
    left, top, right, bottom = appearance.preview_bounds(pressed)
    target = {'ring': 45, 'glove': 60, 'pixel_hand': 56, 'reticle': 44}[appearance.style]
    extent = max(max(x2-x1, y2-y1) for x1, y1, x2, y2 in
                 (appearance.preview_bounds(False), appearance.preview_bounds(True)))
    if extent <= 0:
        raise ValueError('invalid marker preview bounds')
    scale = target/extent
    return (center_x-(left+right)*scale/2,
            center_y-(top+bottom)*scale/2, scale)


def draw_marker_style_tiles(cr, draft, top):
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('settings.position_marker_style'), 44, top+12, 26, max_width=310)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('settings.marker_style_pick_note'), 390, top+16, 21, max_width=802)
    for style, left, tile_top, width, height in marker_style_tiles():
        selected = draft.values['position_marker_style'] == style
        s.rounded(cr, left, tile_top, width, height, 8,
                  s.KEY_LATCHED if selected else s.PANEL,
                  border=s.ACCENT if selected else s.BORDER, border_width=2 if selected else 1)
        if selected:
            s.line(cr, left+16, tile_top+height-5, left+width-16, tile_top+height-5, s.ACCENT, 3)
        appearance = _preview_appearance(style, draft.values['marker_idle_color'],
                                         draft.values['marker_pressed_color'])
        failed = appearance is None
        if not failed:
            for pressed, center in ((False, left+width*.28), (True, left+width*.72)):
                cr.save()
                try:
                    sprite = appearance.sprite(pressed, 0, 0)
                    x, y, scale = marker_preview_transform(appearance, center, tile_top+height/2,
                                                           pressed=pressed)
                    cr.translate(x, y)
                    cr.scale(scale, scale)
                    cr.set_source_surface(sprite, 0, 0)
                    if appearance.style == 'pixel_hand':
                        import cairo
                        cr.get_source().set_filter(cairo.FILTER_NEAREST)
                    cr.paint()
                except (OSError, ValueError, RuntimeError):
                    failed = True
                finally:
                    cr.restore()
                if failed:
                    break
        if failed:
            cr.set_source_rgb(*s.MUTED)
            s.label(cr, msg('settings.marker_preview_unavailable'), left+width/2,
                    tile_top+height/2, 20, centered=True, max_width=width-32)


def draw_updates(cr, draft, updates, *, blocked=False):
    s.rounded(cr, 24, 432, 1192, 214, 8, s.SURFACE)
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('settings.updates'), 44, 448, 24, bold=True)
    cr.set_source_rgb(*s.MUTED)
    current = updates.current if updates else msg('common.unknown')
    latest = updates.latest.tag if updates and updates.latest else msg('update.not_checked')
    s.label(cr, msg('update.current_version', current=current), 44, 480, 22, max_width=550)
    s.label(cr, msg('update.latest_version', latest=latest), 620, 480, 22, max_width=550)
    s.label(cr, msg('update.source'), 44, 508, 18, max_width=1120)
    message = updates.message if updates else msg('update.unavailable')
    cr.set_source_rgb(*(s.DANGER if updates and updates.phase == 'error' else s.ACCENT))
    s.label(cr, message, 44, 534, 20, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    if draft.dirty:
        note = msg('update.unsaved')
    elif updates and not updates.managed:
        note = msg('update.source_only')
    elif updates and updates.confirming:
        note = msg('update.confirm_note')
    else:
        note = msg('update.manual_note')
    s.label(cr, note, 44, 560, 18, max_width=1140)
    can_check = bool(updates and not updates.busy and not blocked)
    can_install = bool(updates and updates.available and not draft.dirty and not blocked)
    s.button(cr, 44, GENERAL_UPDATE_BUTTON_TOP, 520, GENERAL_ACTION_HEIGHT,
             msg('common.cancel') if updates and updates.confirming else
             msg('update.check') if can_check else msg('update.busy'), can_check)
    caption = (msg('update.confirm') if updates and updates.confirming else msg('update.to', tag=updates.latest.tag)
               if updates and updates.latest and can_install else msg('common.update'))
    s.button(cr, 620, GENERAL_UPDATE_BUTTON_TOP, 572, GENERAL_ACTION_HEIGHT, caption, can_install)


def draw_uninstall(cr, draft, uninstall, updates=None, *, blocked=False):
    s.rounded(cr, 24, 658, 1192, 216, 8, s.SURFACE)
    confirming = bool(uninstall and uninstall.confirming)
    busy = bool(uninstall and uninstall.busy)
    managed = bool(uninstall and uninstall.managed)
    blocked = bool(blocked or draft.dirty or (updates and updates.busy))
    enabled = managed and not busy and not blocked and uninstall.phase != 'success'
    cr.set_source_rgb(*s.DANGER)
    s.label(cr, msg('uninstall.confirm_title' if confirming else 'uninstall.title'),
            44, 674, 24, bold=True, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('uninstall.scope'), 44, 706, 20, max_width=1120)
    s.label(cr, msg('uninstall.keep'), 44, 732, 20, max_width=1120)
    message = (msg('uninstall.managed_only') if not managed else
               msg('uninstall.unsaved') if draft.dirty else
               msg('uninstall.update_busy') if updates and updates.busy else uninstall.message)
    cr.set_source_rgb(*(s.DANGER if uninstall and uninstall.phase == 'error' else s.MUTED))
    s.label(cr, message, 44, 758, 20, max_width=1120)
    if confirming:
        s.button(cr, 44, GENERAL_UNINSTALL_BUTTON_TOP, 520, GENERAL_ACTION_HEIGHT, msg('common.cancel'))
        s.button(cr, 620, GENERAL_UNINSTALL_BUTTON_TOP, 572, GENERAL_ACTION_HEIGHT, msg('uninstall.confirm'), enabled, danger=True)
    else:
        s.button(cr, 44, GENERAL_UNINSTALL_BUTTON_TOP, 520, GENERAL_ACTION_HEIGHT, msg('update.busy') if busy else msg('uninstall.title'),
                 enabled, danger=True)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('uninstall.record'), 44, 850, 18, max_width=1120)


def draw_driver(cr, draft, driver, *, blocked=False):
    s.rounded(cr, 24, 310, 1192, 405, 8, s.SURFACE)
    cr.set_source_rgb(*s.FG)
    s.label(cr, msg('driver.title'), 44, 342, 30, bold=True, max_width=1120)
    info = driver.info if driver else {'kernel': '', 'active': False}
    message = driver.message if driver else msg('driver.not_checked')
    cr.set_source_rgb(*s.ACCENT)
    s.label(cr, message, 44, 404, 26, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    for text,y in ((msg('driver.kernel', value=info.get('kernel') or msg('common.unknown')), 460),
                   (msg('driver.scope'), 512), (msg('driver.lifetime'), 557),
                   (msg('driver.authentication'), 602), (msg('driver.caution'), 647)):
        s.label(cr, text, 44, y, 23, max_width=1120)
    blocked = blocked or draft.dirty
    confirming = driver.confirming if driver else None
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, msg('driver.unsaved') if draft.dirty else msg('driver.confirm_note')
            if confirming else msg('driver.component_note'), 44, 724, 22, max_width=1140)
    if confirming:
        s.button(cr, 44, 760, 520, 76, msg('common.cancel'))
        s.button(cr, 620, 760, 572, 76, msg('driver.confirm_apply' if confirming == 'apply'
            else 'driver.confirm_revert'), bool(driver and driver.can(confirming) and not blocked), danger=True)
    else:
        s.button(cr, 44, 760, 520, 76, msg('driver.enable'),
                 bool(driver and driver.can('apply') and not blocked))
        s.button(cr, 620, 760, 572, 76, msg('driver.revert'),
                 bool(driver and driver.can('revert') and not blocked))
    s.button(cr, 44, 850, 520, 64, msg('driver.refresh'), bool(driver and not driver.busy))
