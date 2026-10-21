"""Validated application preferences and atomic persistence, without GTK/input."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import tempfile

from .scroll_output import read_scroll_scale
from .keyboard_languages import LANGUAGES, read_language


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
        NumberSetting("sensitivity", "鼠标移动速度", "数值越大，相同滑动移动越远", 1.5, .2, 5., .1, "×"),
        NumberSetting("scroll_speed", "滚轮速度档位", "双指滚动；1 最慢，5 最快", 3, 1, 5, 1),
        NumberSetting("scroll_scale", "滚轮输出倍率", "降低倍率可更精细地滚动", 1., .01, 1., .05, "×"),
        NumberSetting("friction", "滑行阻力", "松手后的滑行；越大停止越快", 5, 1, 10, 1),
        NumberSetting("position_sensitivity", "定位模式速度", "仅影响定位圆环，不影响直接触屏的绝对位置", 2., .1, 4., .1, "×"),
        NumberSetting("keyboard_repeat_delay_ms", "长按重复等待", "按住多久后开始重复输入", 350, 150, 800, 25, " ms"),
        NumberSetting("keyboard_repeat_interval_ms", "重复输入间隔", "间隔越短，重复输入越快", 60, 20, 200, 10, " ms"),
        NumberSetting("keyboard_caps_window_ms", "Shift 双击间隔", "此时间内双击 Shift 锁定大写", 350, 150, 800, 25, " ms"),
    )
}
BOOLEANS = {"tap_to_click": True, "glide": True, "keyboard_repeat_enabled": True}
CHOICES = {"keyboard_language": LANGUAGES}
DEFAULTS = {**{key: spec.default for key, spec in NUMBERS.items()}, **BOOLEANS,
            "keyboard_language": "en_US"}
SECTIONS = {
    "mouse": ("sensitivity", "scroll_speed", "scroll_scale", "tap_to_click", "glide", "friction"),
    "position": ("position_sensitivity",),
    "keyboard": ("keyboard_language", "keyboard_repeat_enabled", "keyboard_repeat_delay_ms",
                 "keyboard_repeat_interval_ms", "keyboard_caps_window_ms"),
}
SETTINGS_PAGES = (*SECTIONS, 'updates')


def read_settings(config):
    config = config if isinstance(config, dict) else {}
    values = {key: spec.read(config.get(key, spec.default)) for key, spec in NUMBERS.items()}
    # Older manual configs accepted every reduction >0. Do not silently speed
    # up those installations just by opening/saving another preference.
    values["scroll_scale"] = read_scroll_scale(config.get("scroll_scale", 1.))
    values.update({key: config[key] if isinstance(config.get(key), bool) else default
                   for key, default in BOOLEANS.items()})
    values["keyboard_language"] = read_language(config)
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


class SettingsDraft:
    """Edits stay local until Save. All hit geometry is in logical panel units."""
    def __init__(self, values):
        self.saved = read_settings(values)
        self.values = dict(self.saved)
        self.section = "mouse"
        self.drag = None
        self.message = "调整后点击保存；离开设置将放弃未保存的修改"
        self.error = False

    @property
    def dirty(self):
        return self.values != self.saved

    def change(self, key, value):
        if key in CHOICES:
            value = value if isinstance(value, str) and value in CHOICES[key] else DEFAULTS[key]
        else:
            value = NUMBERS[key].read(value) if key in NUMBERS else bool(value)
        self.values[key] = value
        self.error = False
        self.message = "有未保存的修改" if self.dirty else "设置未改变"

    def reset_section(self):
        for key in SECTIONS[self.section]:
            self.values[key] = DEFAULTS[key]
        self.error = False
        self.message = "已恢复本页默认值；点击保存后生效"

    def mark_saved(self):
        self.saved = dict(self.values)
        self.message, self.error = "已保存，设置已生效", False

    def discard(self):
        self.values = dict(self.saved)
        self.drag = None
        self.message, self.error = "已放弃未保存的修改", False

    def rows(self):
        return [(key, 300 + index * 98)
                for index, key in enumerate(SECTIONS[self.section])]

    def hit(self, x, y):
        for index, section in enumerate(SETTINGS_PAGES):
            if 24 + index * 204 <= x <= 216 + index * 204 and 220 <= y <= 280:
                return "section", section
        if self.section == 'updates':
            if 760 <= y <= 836:
                if 44 <= x <= 564:
                    return 'check_update', None
                if 620 <= x <= 1192:
                    return 'install_update', None
            if 850 <= y <= 914 and 620 <= x <= 1192:
                return 'cancel_update', None
            return None, None
        if 996 <= y <= 1060:
            for key, left, width in (("defaults", 24, 270), ("discard", 662, 250), ("save", 936, 280)):
                if left <= x <= left + width:
                    return key, None
        for key, top in self.rows():
            if not top <= y <= top + 88:
                continue
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
