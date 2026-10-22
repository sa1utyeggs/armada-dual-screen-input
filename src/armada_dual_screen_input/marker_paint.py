"""Marker scene and bounded damage, shared by expose and explicit frames."""
from __future__ import annotations

import math
from functools import lru_cache

from .marker_state import validate_rings
from .marker_colors import DEFAULT_COLORS


class MarkerScene:
    def __init__(self, canvas):
        if len(canvas) != 2 or not all(type(n) is int and 1 <= n <= 8192 for n in canvas):
            raise ValueError('invalid marker canvas')
        self.canvas = tuple(canvas)
        self.rings = ()
        self.damage = set()

    def _add(self, rings):
        width, height = self.canvas
        for u,v,_ in rings:
            x, y = round(u*(width-1)), round(v*(height-1))
            left, top = max(0,x-17), max(0,y-17)
            right, bottom = min(width,x+18), min(height,y+18)
            self.damage.add((left,top,right-left,bottom-top))
        if len(self.damage)>64:
            left = min(r[0] for r in self.damage)
            top = min(r[1] for r in self.damage)
            right = max(r[0]+r[2] for r in self.damage)
            bottom = max(r[1]+r[3] for r in self.damage)
            self.damage = {(left,top,right-left,bottom-top)}

    def update(self, rings):
        rings = validate_rings(rings)
        if rings == self.rings:
            return False
        # Keep damage across all unpainted changes. An unrelated partial
        # expose must not discard the bounds of an old visible ring.
        self._add((*self.rings,*rings))
        self.rings = rings
        return True

    def invalidate(self, *, full=False):
        if full:
            self.damage = {(0,0,*self.canvas)}
        else:
            self._add(self.rings)

    def take_damage(self):
        rectangles = tuple(sorted(self.damage))
        self.damage.clear()
        return rectangles


def _stroke_ring(cr, x, y, rgba):
    for width,color in ((5,(0,0,0,.85)), (2.5,rgba)):
        cr.set_line_width(width)
        cr.set_source_rgba(*color)
        cr.new_sub_path()
        cr.arc(x,y,12,0,math.tau)
        cr.stroke()


# Eight subpixel phases per axis keep the visual error <=1/16 pixel per axis.
# A worker uses only two colors: at most 128 tiny surfaces (648 KiB of pixels).
# This cache never stores a screen-sized image or changes native coordinates.
_PHASES = 8
_SPRITE_SIZE = 36
_SPRITE_ORIGIN = 18


@lru_cache(maxsize=128)
def _ring_sprite(rgba, phase_x, phase_y):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _SPRITE_SIZE, _SPRITE_SIZE)
    _stroke_ring(cairo.Context(surface), _SPRITE_ORIGIN+phase_x/_PHASES,
                 _SPRITE_ORIGIN+phase_y/_PHASES, rgba)
    surface.flush()
    return surface


def draw_rings(cr, rings, canvas, colors=DEFAULT_COLORS):
    import cairo
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0,0,0,0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    matrix = cr.get_matrix()
    # The production X11 marker has unit-scale device pixels. Preserve the
    # vector path on scaled/rotated contexts, including HiDPI offscreen tests.
    cached = (tuple(matrix) == (1.,0.,0.,1.,0.,0.)
              and cr.get_target().get_device_scale() == (1.,1.))
    for u,v,pressed in rings:
        x,y = u*(canvas[0]-1),v*(canvas[1]-1)
        rgba = colors.pressed_rgba if pressed else colors.idle_rgba
        if not cached:
            _stroke_ring(cr, x, y, rgba)
            continue
        qx, qy = round(x*_PHASES), round(y*_PHASES)
        sprite = _ring_sprite(rgba, qx % _PHASES, qy % _PHASES)
        left, top = qx//_PHASES-_SPRITE_ORIGIN, qy//_PHASES-_SPRITE_ORIGIN
        cr.set_source_surface(sprite, left, top)
        cr.rectangle(left, top, _SPRITE_SIZE, _SPRITE_SIZE)
        cr.fill()
