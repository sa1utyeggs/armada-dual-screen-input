"""Bounded passive-ring IPC payloads; no GTK, screen or input access."""
import math

MAX_RINGS = 10


def validate_rings(rings):
    if not isinstance(rings, (tuple, list)) or len(rings) > MAX_RINGS:
        raise ValueError('invalid marker count')
    result = []
    for ring in rings:
        if not isinstance(ring, (tuple, list)) or len(ring) != 3:
            raise ValueError('invalid marker state')
        x, y, pressed = ring
        if (not all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in (x, y))
                or type(pressed) is not bool):
            raise ValueError('invalid marker state')
        result.append((x, y, pressed))
    return tuple(result)


def decode_rings(message):
    if isinstance(message, dict):
        if set(message) != {'contacts'}:
            raise ValueError('unknown marker payload')
        return validate_rings(message['contacts'])
    return validate_rings([message])  # Existing single-ring protocol.
