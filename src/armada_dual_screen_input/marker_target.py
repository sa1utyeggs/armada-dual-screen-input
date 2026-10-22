"""Validated binding for our passive same-app X11 decoration window."""
from dataclasses import asdict, dataclass
import json
import re

from .gamescope_focus import FocusSnapshot


@dataclass(frozen=True)
class MarkerTarget:
    window: int
    app_id: int
    width: int
    height: int
    server_pid: int
    surface_display: str
    x: int = 0
    y: int = 0

    def __post_init__(self):
        for name, maximum in (('window', 2**32-1), ('app_id', 2**32-1),
                              ('width', 8192), ('height', 8192), ('server_pid', 2**31-1)):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError('invalid marker target '+name)
        for value in (self.x, self.y):
            if type(value) is not int or not -32768 <= value <= 32767:
                raise ValueError('invalid marker target origin')
        if self.window == 1 or not isinstance(self.surface_display, str) or not re.fullmatch(
                r':[0-9]+(?:\.[0-9]+)?', self.surface_display):
            raise ValueError('an explicit local marker surface is required')

    @classmethod
    def from_focus(cls, focus):
        if (not isinstance(focus, FocusSnapshot) or not focus.input_in_surface
                or focus.app_id != focus.graphics_app_id or focus.touch_mode not in (1, 4)):
            raise ValueError('marker requires a verified visible input surface')
        return cls(focus.window, focus.app_id, focus.width, focus.height,
                   focus.server_pid, focus.surface_display, focus.x, focus.y)

    def matches_focus(self, focus):
        try:
            return self == self.from_focus(focus)
        except ValueError:
            return False

    def encode(self):
        return json.dumps(asdict(self), separators=(',', ':'))

    @classmethod
    def decode(cls, payload):
        if len(payload) > 1024:
            raise ValueError('oversized marker target')
        values = json.loads(payload)
        if not isinstance(values, dict) or set(values) != set(cls.__dataclass_fields__):
            raise ValueError('invalid marker target fields')
        return cls(**values)

    def properties(self):
        # Same-app, cross-process override-redirect + these non-interactive
        # styles select Gamescope's decoration path, leaving mangoapp's
        # external-overlay slot available. All writes target our window only.
        return (('STEAM_GAME', self.app_id, 6),
                ('_WINE_HWND_EXSTYLE', 0x80020, 6),  # LAYERED | TRANSPARENT
                ('_WINE_HWND_STYLE', 0x88000000, 6),  # POPUP | DISABLED
                ('WM_TRANSIENT_FOR', self.window, 33),
                ('_NET_WM_WINDOW_OPACITY', 0xffffffff, 6))
