"""Marker scene and bounded damage, shared by expose and explicit frames."""
from __future__ import annotations

import math

from .marker_state import validate_rings


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


def draw_rings(cr, rings, canvas):
    import cairo
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0,0,0,0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    for u,v,pressed in rings:
        x,y = u*(canvas[0]-1),v*(canvas[1]-1)
        for width,color in ((5,(0,0,0,.85)),
                            (2.5,(1.,.65,.15,1.) if pressed else (.35,.85,1.,1.))):
            cr.set_line_width(width)
            cr.set_source_rgba(*color)
            cr.new_sub_path()
            cr.arc(x,y,12,0,math.tau)
            cr.stroke()
