#!/usr/bin/env python3
"""Read-only structural checks for a two-state transparent marker PNG pair.

Requires Pillow. JSON output describes pixels and supplied hotspot range;
visual alignment, hotspot intent and renderer behavior still need review.
"""
import argparse
import json
from pathlib import Path
import struct
import sys


def inspect(path, args, issues):
    from PIL import Image

    record = {'path': str(path), 'visible_bounds': None}
    try:
        with path.open('rb') as stream:
            header = stream.read(26)
        if len(header) < 26 or header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
            raise ValueError('expected a PNG with an IHDR header')
        width, height, depth, color_type = struct.unpack('>IIBB', header[16:26])
        record.update(size=[width, height], bit_depth=depth, png_color_type=color_type)
        if (width, height) != (args.size, args.size):
            issues.append(f'{path}: expected {args.size}x{args.size}, got {width}x{height}')
            return record, None
        if depth != 8 or color_type != 6:
            issues.append(f'{path}: expected an 8-bit RGBA PNG')
            return record, None
        with Image.open(path) as image:
            image.load()
            record['mode'] = image.mode
            if image.mode != 'RGBA':
                issues.append(f'{path}: decoded mode is {image.mode}, expected RGBA')
                return record, None
            alpha = image.getchannel('A')
            values = list(alpha.getdata())
            bounds = alpha.point(lambda value: 255 if value > args.alpha_threshold else 0).getbbox()
            record.update(visible_bounds=list(bounds) if bounds else None,
                          transparent_pixels=values.count(0),
                          partial_alpha_pixels=sum(0 < value < 255 for value in values))
            if not record['transparent_pixels']:
                issues.append(f'{path}: no fully transparent pixels; inspect for a baked background')
            if bounds is None:
                issues.append(f'{path}: no artwork above the alpha threshold')
            else:
                padding = [bounds[0], bounds[1], width-bounds[2], height-bounds[3]]
                record['visible_padding'] = padding
                if min(padding) < args.min_padding:
                    issues.append(f'{path}: visible artwork violates {args.min_padding}px minimum padding')
            # Hidden RGB under alpha=0 must not make visually identical
            # states appear distinct. Compare premultiplied pixel values.
            pixels = bytearray(image.tobytes())
            for offset in range(0, len(pixels), 4):
                opacity = pixels[offset+3]
                for channel in range(3):
                    pixels[offset+channel] = (pixels[offset+channel]*opacity+127)//255
            return record, bytes(pixels)
    except (OSError, ValueError) as error:
        issues.append(f'{path}: {error}')
        return record, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('positioning', type=Path)
    parser.add_argument('held', type=Path)
    parser.add_argument('--size', type=int, default=64, help='Expected square runtime canvas, default 64')
    parser.add_argument('--hotspot', type=int, nargs=2, metavar=('X', 'Y'),
                        help='Intended common runtime hotspot; never inferred from artwork bounds')
    parser.add_argument('--alpha-threshold', type=int, default=15,
                        help='Visible-bound threshold; matches the current project convention')
    parser.add_argument('--min-padding', type=int, default=1,
                        help='Minimum padding around visible bounds, default 1 pixel')
    args = parser.parse_args()
    if args.size <= 0 or args.min_padding < 0 or not 0 <= args.alpha_threshold < 255:
        parser.error('size must be positive, padding nonnegative, and alpha threshold 0..254')
    try:
        import PIL  # noqa: F401 -- diagnose a missing optional inspection dependency.
    except ImportError:
        print(json.dumps({'ok': False, 'issues': ['Pillow is unavailable; use a workspace Python with Pillow.']}))
        return 2

    issues = []
    if args.hotspot and not all(0 <= value < args.size for value in args.hotspot):
        issues.append('the common hotspot must be inside the runtime canvas')
    idle, idle_pixels = inspect(args.positioning, args, issues)
    held, held_pixels = inspect(args.held, args, issues)
    identical = None
    if idle_pixels is not None and held_pixels is not None:
        identical = idle_pixels == held_pixels
        if identical:
            issues.append('the two state images have identical visible pixels')
    report = {'ok': not issues, 'size': args.size, 'common_hotspot': args.hotspot,
              'alpha_threshold': args.alpha_threshold, 'minimum_padding': args.min_padding,
              'states_identical': identical, 'visual_alignment_checked': False,
              'states': {'positioning': idle, 'held': held}, 'issues': issues}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
