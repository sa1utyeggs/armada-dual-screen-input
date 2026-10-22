"""Validated application preferences and atomic persistence, without GTK/input."""
from __future__ import annotations

from .i18n import msg, LocalizedState, UI_LANGUAGES, read_ui_language

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tempfile

from .scroll_output import read_scroll_scale
from .keyboard_languages import LANGUAGES, read_language
from .marker_frames import FRAME_RATES, read_frame_rate
from .marker_colors import COLOR_SETTINGS, COLOR_PRESETS, read_color


@dataclass(frozen=True)
class NumberSetting:
    key: str
    label: str
    note: str
    default: float
    low: float
    high: float
    step: float
    unit: str = ""

    def read(self, value):
        if isinstance(value, bool):
            return self.default
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return self.default
        if not math.isfinite(number):
            return self.default
        number = max(self.low, min(self.high, number))
        return int(round(number)) if self.step >= 1 else round(number, 4)

    def display(self, value):
        if self.key == "scroll_scale" and 0 < value < .01:
            return f"{value:.3g}×"
        return (str(int(value)) if self.step >= 1 else f"{value:.2f}") + self.unit


NUMBERS = {
    spec.key: spec for spec in (
        NumberSetting("sensitivity", msg('settings.pointer_speed'), msg('settings.pointer_speed_note'), 1.5, .2, 5., .1, "×"),
        NumberSetting("scroll_speed", msg('settings.scroll_speed'), msg('settings.scroll_speed_note'), 3, 1, 5, 1),
        NumberSetting("scroll_scale", msg('settings.scroll_scale'), msg('settings.scroll_scale_note'), 1., .01, 1., .05, "×"),
        NumberSetting("friction", msg('settings.friction'), msg('settings.friction_note'), 5, 1, 10, 1),
        NumberSetting("position_sensitivity", msg('settings.position_speed'), msg('settings.position_speed_note'), 2., .1, 4., .1, "×"),
        NumberSetting("keyboard_repeat_delay_ms", msg('settings.repeat_delay'), msg('settings.repeat_delay_note'), 350, 150, 800, 25, " ms"),
        NumberSetting("keyboard_repeat_interval_ms", msg('settings.repeat_interval'), msg('settings.repeat_interval_note'), 60, 20, 200, 10, " ms"),
        NumberSetting("keyboard_caps_window_ms", msg('settings.shift_interval'), msg('settings.shift_interval_note'), 350, 150, 800, 25, " ms"),
    )
}
BOOLEANS = {"tap_to_click": True, "glide": True, "keyboard_repeat_enabled": True}
CHOICES = {"keyboard_language": LANGUAGES, "marker_frame_rate": FRAME_RATES,
           "ui_language": {**UI_LANGUAGES, "auto": msg("settings.follow_system")}}
DEFAULTS = {**{key: spec.default for key, spec in NUMBERS.items()}, **BOOLEANS,
            "keyboard_language": "en_US", "ui_language": "en_US", "marker_frame_rate": "auto", **COLOR_SETTINGS}
SECTIONS = {
    "mouse": ("sensitivity", "scroll_speed", "scroll_scale", "tap_to_click", "glide", "friction"),
    "position": ("position_sensitivity", "marker_frame_rate", "marker_idle_color", "marker_pressed_color"),
    "keyboard": ("keyboard_language", "keyboard_repeat_enabled", "keyboard_repeat_delay_ms",
                 "keyboard_repeat_interval_ms", "keyboard_caps_window_ms"),
    "general": ("ui_language",),
}
SETTINGS_PAGES = (*SECTIONS, 'driver')
GENERAL_UPDATE_BUTTON_TOP = 618
GENERAL_UNINSTALL_BUTTON_TOP = 854


def settings_tabs():
    width = (1192 - 12 * (len(SETTINGS_PAGES) - 1)) / len(SETTINGS_PAGES)
    return tuple((section, 24 + index * (width + 12), width)
                 for index, section in enumerate(SETTINGS_PAGES))


def color_swatches():
    return tuple((650+index*68, color, caption) for index, (color, caption) in enumerate(COLOR_PRESETS))


def choice_caption(key, value, monitor_millihz=0):
    caption = str(CHOICES[key][value])
    if (key == 'marker_frame_rate' and value == 'auto' and type(monitor_millihz) is int
            and 30000 <= monitor_millihz <= 240000):
        caption = str(msg('choice.refresh', caption=caption, rate=round(monitor_millihz/1000)))
    return caption


def read_settings(config):
    config = config if isinstance(config, dict) else {}
    values = {key: spec.read(config.get(key, spec.default)) for key, spec in NUMBERS.items()}
    # Older manual configs accepted every reduction >0. Do not silently speed
    # up those installations just by opening/saving another preference.
    values["scroll_scale"] = read_scroll_scale(config.get("scroll_scale", 1.))
    values.update({key: config[key] if isinstance(config.get(key), bool) else default
                   for key, default in BOOLEANS.items()})
    values["ui_language"] = read_ui_language(config.get("ui_language"))
    values["keyboard_language"] = read_language(config)
    values["marker_frame_rate"] = read_frame_rate(config.get("marker_frame_rate"))
    values.update({key: read_color(config.get(key), default) for key, default in COLOR_SETTINGS.items()})
    return values


def write_settings(path, updates):
    """Merge owned preferences only. A failed write leaves the old file intact.

    Refuse unreadable/malformed existing config instead of erasing settings this
    page does not own. No window, system settings or input device is touched.
    """
    path = Path(path)
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Configuration is not an object")
    except FileNotFoundError:
        config = {}
    config.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class SettingsDraft(LocalizedState):
    """Edits stay local until Save. All hit geometry is in logical panel units."""
    def __init__(self, values):
        self.saved = read_settings(values)
        self.values = dict(self.saved)
        self.section = "mouse"
        self.drag = None
        self.message = msg('settings.draft')
        self.error = False

    @property
    def dirty(self):
        return self.values != self.saved

    def change(self, key, value):
        if key in COLOR_SETTINGS:
            value = read_color(value, COLOR_SETTINGS[key])
        elif key in CHOICES:
            value = value if isinstance(value, str) and value in CHOICES[key] else DEFAULTS[key]
        else:
            value = NUMBERS[key].read(value) if key in NUMBERS else bool(value)
        self.values[key] = value
        self.error = False
        self.message = msg('settings.dirty') if self.dirty else msg('settings.unchanged')

    def reset_section(self):
        for key in SECTIONS[self.section]:
            self.values[key] = DEFAULTS[key]
        self.error = False
        self.message = msg('settings.reset')

    def mark_saved(self):
        self.saved = dict(self.values)
        self.message, self.error = msg('settings.saved'), False

    def discard(self):
        self.values = dict(self.saved)
        self.drag = None
        self.message, self.error = msg('settings.discarded'), False

    def rows(self):
        return [(key, 300 + index * 98)
                for index, key in enumerate(SECTIONS.get(self.section, ()))]

    def hit(self, x, y):
        for section, left, width in settings_tabs():
            if left <= x <= left + width and 220 <= y <= 280:
                return "section", section
        if self.section == "general":
            if GENERAL_UPDATE_BUTTON_TOP <= y <= GENERAL_UPDATE_BUTTON_TOP + 60:
                if 44 <= x <= 564:
                    return 'update_left', None
                if 620 <= x <= 1192:
                    return 'install_update', None
            if GENERAL_UNINSTALL_BUTTON_TOP <= y <= GENERAL_UNINSTALL_BUTTON_TOP + 56:
                if 44 <= x <= 564:
                    return "uninstall_left", None
                if 620 <= x <= 1192:
                    return "uninstall_confirm", None
        if self.section == 'driver':
            if 760 <= y <= 836:
                if 44 <= x <= 564:
                    return 'driver_left', None
                if 620 <= x <= 1192:
                    return 'driver_right', None
            if 850 <= y <= 914 and 44 <= x <= 564:
                return 'driver_refresh', None
            return None, None
        if 996 <= y <= 1060:
            for key, left, width in (("defaults", 24, 270), ("discard", 662, 250), ("save", 936, 280)):
                if left <= x <= left + width:
                    return key, None
        for key, top in self.rows():
            if not top <= y <= top + 88:
                continue
            if key in COLOR_SETTINGS:
                for left, color, _ in color_swatches():
                    if left <= x <= left+60 and top+14 <= y <= top+74:
                        return 'color', (key, color)
                return None, None
            if key in CHOICES:
                return ("choice", key) if 790 <= x <= 1192 else (None, None)
            if key in BOOLEANS:
                return ("toggle", key) if 900 <= x <= 1192 else (None, None)
            if top + 20 <= y <= top + 80:
                if 552 <= x <= 612:
                    return "minus", key
                if 628 <= x <= 984:
                    return "slider", key
                if 1000 <= x <= 1060:
                    return "plus", key
        return None, None

    def slide(self, key, x):
        spec = NUMBERS[key]
        ratio = max(0., min(1., (x - 644) / 324))
        steps = round((spec.low + ratio * (spec.high - spec.low)) / spec.step)
        self.change(key, steps * spec.step)
