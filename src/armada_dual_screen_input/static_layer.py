"""One bounded Cairo raster layer for the touch page's static illustration."""
from __future__ import annotations

import math
from .i18n import active_language


class StaticLayer:
    def __init__(self):
        self.key = self.surface = None

    def paint(self, cr, content_key, width, height, draw):
        import cairo
        from .text_render import PangoCairo

        matrix = cr.get_matrix()
        scale = cr.get_target().get_device_scale()
        options = cr.get_target().get_font_options()
        options.merge(cr.get_font_options())
        fontmap = PangoCairo.FontMap.get_default()
        key = (active_language(), content_key, tuple(matrix), scale, options.hash(),
               fontmap.get_serial(), fontmap.get_resolution(), width, height)
        # This layer is used by the unrotated touch page only. Unsupported
        # transforms retain the original vector rendering path.
        pixels = (math.ceil(width*matrix.xx*scale[0]),
                  math.ceil(height*matrix.yy*scale[1]))
        if (matrix.xy or matrix.yx or matrix.x0 or matrix.y0
                or min(pixels) <= 0 or max(pixels) > 4096
                or pixels[0]*pixels[1] > 8_000_000):
            self.key = self.surface = None
            draw(cr)
            return
        if key != self.key:
            try:
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *pixels)
            except (cairo.Error, MemoryError):
                self.key = self.surface = None
                draw(cr)
                return
            surface.set_device_scale(*scale)
            cached = cairo.Context(surface)
            cached.set_matrix(matrix)
            cached.set_font_options(options)
            draw(cached)
            self.surface, self.key = surface, key
        cr.save()
        try:
            # Cached pixels already use the destination's transform and device
            # scale. Replay them 1:1 while retaining GTK's device-space clip.
            cr.identity_matrix()
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()
        finally:
            cr.restore()
