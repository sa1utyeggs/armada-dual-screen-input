"""Conservative keyboard damage regions; no input or toolkit side effects."""
from __future__ import annotations

import math


class KeyboardRedraw:
    def __init__(self):
        self.drawn = None

    @staticmethod
    def state(layout, pressed):
        return (layout.shift_active, layout.caps_lock,
                bool(getattr(layout, 'ctrl_active', False)),
                bool(getattr(layout, 'alt_active', False)),
                bool(getattr(layout, 'super_active', False)), pressed)

    def remember(self, layout, pressed):
        self.drawn = self.state(layout, pressed)

    def painted(self, layout, pressed, cr):
        """A candidate-only draw must not claim that key highlights changed."""
        current = self.state(layout, pressed)
        keys = [key for row in layout.rows for key in row]
        if self.drawn is not None and self.drawn[:-1] == current[:-1]:
            codes = {self.drawn[-1], pressed} - {None}
            keys = [key for key in keys if key.code in codes]
            if {key.code for key in keys} != codes:
                return
        if all(cr.in_clip(x,y) for key in keys
               for x in (key.x,key.x+key.w) for y in (key.y,key.y+key.h)):
            self.drawn = current

    def regions(self, layout, pressed):
        current = self.state(layout, pressed)
        if self.drawn is None or self.drawn[:-1] != current[:-1]:
            return None  # Font/label/modifier changes need the full keyboard.
        codes = {self.drawn[-1], pressed} - {None}
        keys = [key for row in layout.rows for key in row if key.code in codes]
        if {key.code for key in keys} != codes:
            return None
        # Include antialiasing, shadows and the +/-1.5px OLED orbital shift.
        return [(key.x-5,key.y-5,key.w+10,key.h+10) for key in keys]


def widget_rect(rect, width, height, logical_width=1240, logical_height=1080):
    x,y,w,h = rect
    left,top = math.floor(x*width/logical_width), math.floor(y*height/logical_height)
    right,bottom = math.ceil((x+w)*width/logical_width), math.ceil((y+h)*height/logical_height)
    return left,top,right-left,bottom-top
