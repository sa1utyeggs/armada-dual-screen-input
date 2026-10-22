"""Opaque marker colors, validated once outside the drawing/input hot paths."""
from dataclasses import dataclass, field
import re

DEFAULT_IDLE_COLOR = '#59D9FF'
DEFAULT_PRESSED_COLOR = '#FFA626'
COLOR_SETTINGS = {'marker_idle_color': DEFAULT_IDLE_COLOR,
                  'marker_pressed_color': DEFAULT_PRESSED_COLOR}
COLOR_PRESETS = (
    (DEFAULT_IDLE_COLOR, '冰蓝'), (DEFAULT_PRESSED_COLOR, '橙色'),
    ('#58E38B', '绿色'), ('#FFE066', '黄色'),
    ('#FF5D73', '红色'), ('#B494FF', '紫色'),
    ('#FF8BD1', '粉色'), ('#FFFFFF', '白色'),
)


def parse_color(value):
    if not isinstance(value, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', value) is None:
        raise ValueError('marker color must be an opaque #RRGGBB value')
    return value.upper()


def read_color(value, default):
    try:
        return parse_color(value)
    except ValueError:
        return default


def color_rgb(value):
    value = parse_color(value)
    return tuple(int(value[i:i+2], 16)/255 for i in (1, 3, 5))


@dataclass(frozen=True)
class MarkerColors:
    idle: str = DEFAULT_IDLE_COLOR
    pressed: str = DEFAULT_PRESSED_COLOR
    idle_rgba: tuple = field(init=False, repr=False)
    pressed_rgba: tuple = field(init=False, repr=False)

    def __post_init__(self):
        for name in ('idle', 'pressed'):
            value = parse_color(getattr(self, name))
            object.__setattr__(self, name, value)
            # Preserve the existing default strokes exactly. Other saved hex
            # values are decoded once, never for each motion sample/frame.
            rgb = ((.35, .85, 1.) if value == DEFAULT_IDLE_COLOR else
                   (1., .65, .15) if value == DEFAULT_PRESSED_COLOR else color_rgb(value))
            object.__setattr__(self, name+'_rgba', (*rgb, 1.))


DEFAULT_COLORS = MarkerColors()
