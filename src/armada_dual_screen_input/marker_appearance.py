"""Small marker sprites and shared visual geometry; never alter input points.

The two glove poses share a 64px canvas and one hotspot, anchored to the
positioning pose. Curling the index does not translate the palm or touch.
Only startup loads files; the render loop selects already cached pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path

from .i18n import msg
from .marker_colors import DEFAULT_COLORS, MarkerColors

POSITION_STYLES = {
    'ring': msg('choice.marker_ring'),
    'ring_white': msg('choice.marker_ring_white'),
    'glove': msg('choice.marker_glove'),
    'pixel_hand': msg('choice.marker_pixel_hand'),
    'reticle': msg('choice.marker_reticle'),
}
RING_PRESETS = {
    'ring': DEFAULT_COLORS,
    'ring_white': MarkerColors('#FFFFFF', '#58E38B'),
}
_PHASES = 8
_SPRITE_SIZE = 36
_SPRITE_ORIGIN = 18
GLOVE_SIZE = 64
GLOVE_ORIGIN = (19, 11)
_GLOVE_ROOT = Path(__file__).resolve().parents[2] / 'assets' / 'markers' / 'glove'
PIXEL_HAND_SIZE = 64
PIXEL_HAND_ORIGIN = (15, 5)
_PIXEL_HAND_ROOT = _GLOVE_ROOT.parent / 'pixel_hand'
RETICLE_SIZE = 64
RETICLE_ORIGIN = (32, 32)
RETICLE_COLORS = MarkerColors('#00CDEB', '#FFC21F')


def read_position_style(value):
    return value if isinstance(value, str) and value in POSITION_STYLES else 'ring'


def _stroke_ring(cr, x, y, rgba):
    for width, color in ((5, (0, 0, 0, .85)), (2.5, rgba)):
        cr.set_line_width(width)
        cr.set_source_rgba(*color)
        cr.new_sub_path()
        cr.arc(x, y, 12, 0, math.tau)
        cr.stroke()


@lru_cache(maxsize=128)
def _ring_sprite(rgba, phase_x, phase_y):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _SPRITE_SIZE, _SPRITE_SIZE)
    _stroke_ring(cairo.Context(surface), _SPRITE_ORIGIN + phase_x / _PHASES,
                 _SPRITE_ORIGIN + phase_y / _PHASES, rgba)
    surface.flush()
    return surface


def _png_source(root, size, pressed):
    import cairo
    surface = cairo.ImageSurface.create_from_png(str(root / ('pressed.png' if pressed else 'idle.png')))
    if (surface.get_width(), surface.get_height()) != (size, size):
        raise ValueError('invalid marker sprite dimensions')
    if surface.get_format() != cairo.FORMAT_ARGB32:
        raise ValueError('marker sprite requires an alpha channel')
    return surface


@lru_cache(maxsize=2)
def _glove_source(pressed):
    return _png_source(_GLOVE_ROOT, GLOVE_SIZE, pressed)


@lru_cache(maxsize=2)
def _pixel_hand_source(pressed):
    return _png_source(_PIXEL_HAND_ROOT, PIXEL_HAND_SIZE, pressed)


def _shifted_sprite(source, size, phase_x, phase_y, *, nearest=False):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    cr.set_source_surface(source, phase_x / _PHASES, phase_y / _PHASES)
    cr.get_source().set_filter(cairo.FILTER_NEAREST if nearest else cairo.FILTER_BILINEAR)
    cr.paint()
    surface.flush()
    return surface


@lru_cache(maxsize=128)
def _glove_sprite(pressed, phase_x, phase_y):
    return _shifted_sprite(_glove_source(pressed), GLOVE_SIZE, phase_x, phase_y)


@lru_cache(maxsize=128)
def _pixel_hand_sprite(pressed, phase_x, phase_y):
    return _shifted_sprite(_pixel_hand_source(pressed), PIXEL_HAND_SIZE, phase_x, phase_y, nearest=True)


@lru_cache(maxsize=128)
def _reticle_sprite(pressed, phase_x, phase_y):
    import cairo
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, RETICLE_SIZE, RETICLE_SIZE)
    cr = cairo.Context(surface)
    cr.translate(RETICLE_ORIGIN[0]+phase_x/_PHASES,
                 RETICLE_ORIGIN[1]+phase_y/_PHASES)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    rgba = RETICLE_COLORS.pressed_rgba if pressed else RETICLE_COLORS.idle_rgba
    outer, arm = (18, 9) if pressed else (24, 12)
    # Four symmetric corners. The thin white exterior and black inner border
    # keep the colored stroke readable over either light or dark content.
    for width, color in ((9, (1, 1, 1, 1)), (7, (0, 0, 0, 1)), (4, rgba)):
        cr.set_line_width(width)
        cr.set_source_rgba(*color)
        cr.new_path()
        for sx in (-1, 1):
            for sy in (-1, 1):
                cr.move_to(sx*outer, sy*(outer-arm))
                cr.line_to(sx*outer, sy*outer)
                cr.line_to(sx*(outer-arm), sy*outer)
        cr.stroke()
    if pressed:
        # The outline changes shape as the corners close; the target at the
        # fixed center stays completely transparent while holding a contact.
        for width, color in ((5, (1, 1, 1, 1)), (3.5, (0, 0, 0, 1)), (1.8, rgba)):
            cr.set_line_width(width)
            cr.set_source_rgba(*color)
            cr.new_path()
            cr.move_to(0, -8)
            cr.line_to(8, 0)
            cr.line_to(0, 8)
            cr.line_to(-8, 0)
            cr.close_path()
            cr.stroke()
    else:
        for radius, color in ((3.5, (1, 1, 1, 1)), (2.75, (0, 0, 0, 1)), (2, rgba)):
            cr.set_source_rgba(*color)
            cr.arc(0, 0, radius, 0, math.tau)
            cr.fill()
    surface.flush()
    return surface


@dataclass(frozen=True)
class MarkerAppearance:
    style: str = 'ring'
    colors: MarkerColors = DEFAULT_COLORS

    @property
    def tile_size(self):
        return 64 if self.style in ('glove', 'pixel_hand', 'reticle') else _SPRITE_SIZE

    @property
    def origin(self):
        if self.style == 'glove':
            return GLOVE_ORIGIN
        if self.style == 'pixel_hand':
            return PIXEL_HAND_ORIGIN
        if self.style == 'reticle':
            return RETICLE_ORIGIN
        return (_SPRITE_ORIGIN, _SPRITE_ORIGIN)

    def preview_bounds(self, pressed=False):
        """Visible alpha bounds for presentation, independent of input origin.

        Centering static thumbnails must not move the logical runtime hotspot.
        Glove bounds use alpha >15 to ignore the resize filter's faint fringe.
        """
        if self.style == 'glove':
            return (14, 17 if pressed else 9, 61, 62)
        if self.style == 'pixel_hand':
            return (8, 8 if pressed else 3, 56, 61)
        if self.style == 'reticle':
            return (9, 9, 55, 55) if pressed else (3, 3, 61, 61)
        return (3, 3, 33, 33)

    def for_mode(self, mode):
        # Direct contacts and the backwards-compatible legacy protocol stay
        # rings. No inference from the number or pressed state of contacts.
        return self if mode == 'position' or self.style == 'ring' else load_appearance('ring')

    def sprite(self, pressed, phase_x, phase_y):
        if self.style == 'glove':
            return _glove_sprite(pressed, phase_x, phase_y)
        if self.style == 'pixel_hand':
            return _pixel_hand_sprite(pressed, phase_x, phase_y)
        if self.style == 'reticle':
            return _reticle_sprite(pressed, phase_x, phase_y)
        rgba = self.colors.pressed_rgba if pressed else self.colors.idle_rgba
        return _ring_sprite(rgba, phase_x, phase_y)

    def bounds(self, x, y):
        if self.style == 'ring':
            x, y = round(x), round(y)
            return x - 17, y - 17, x + 18, y + 18
        # Include phase rounding and antialiased edges, at old and new poses.
        ox, oy = self.origin
        return (math.floor(x) - ox - 1, math.floor(y) - oy - 1,
                math.ceil(x) - ox + self.tile_size + 1,
                math.ceil(y) - oy + self.tile_size + 1)


@lru_cache(maxsize=16)
def load_appearance(style, colors=DEFAULT_COLORS):
    """Resolve optional artwork before mapping; both backends get one choice.

    Missing/corrupt optional PNGs fall back to rings at startup only. Runtime
    renderer/target failures retain the existing fail-closed input lifecycle.
    """
    style = read_position_style(style)
    # Retain the old colors argument/configuration for older callers and
    # rollback, but each selected preset owns both of its visible states.
    colors = RING_PRESETS.get(style, RING_PRESETS['ring'])
    if style in ('glove', 'pixel_hand'):
        try:
            import cairo
            source = _glove_source if style == 'glove' else _pixel_hand_source
            for pressed in (False, True):
                source(pressed)
        except (ImportError, OSError, ValueError):
            style = 'ring'
        except Exception as error:
            # pycairo's PNG decoder raises cairo.Error (not OSError).
            if not isinstance(error, cairo.Error):
                raise
            style = 'ring'
    if style == 'reticle':
        colors = RETICLE_COLORS
    return MarkerAppearance(style if style in ('glove', 'pixel_hand', 'reticle') else 'ring', colors)


def prepare_sprites(appearance):
    """Bounded startup work, including all subpixel phases of both poses."""
    for pressed in (False, True):
        for y in range(_PHASES):
            for x in range(_PHASES):
                appearance.sprite(pressed, x, y)
