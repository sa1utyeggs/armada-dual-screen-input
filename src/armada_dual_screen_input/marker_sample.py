"""Visual-only samples. Stable identities never become native input events."""
from dataclasses import dataclass
import math

from .marker_state import decode_rings, validate_rings


@dataclass(frozen=True)
class MarkerSample:
    rings: tuple
    ids: tuple = ()
    mode: str = 'legacy'
    active: bool = False
    sampled_at: float = 0.
    snap: bool = True


def decode_sample(message):
    if not isinstance(message, dict) or 'motion' not in message:
        rings = decode_rings(message)
        return MarkerSample(rings, tuple(range(len(rings))))
    if set(message) != {'contacts', 'motion'}:
        raise ValueError('unknown marker sample fields')
    rings = validate_rings(message['contacts'])
    motion = message['motion']
    if not isinstance(motion, dict) or set(motion) != {'ids', 'mode', 'active', 'sampled_at', 'snap'}:
        raise ValueError('invalid marker motion metadata')
    ids = motion['ids']
    if (not isinstance(ids, (list, tuple)) or len(ids) != len(rings)
            or any(type(tid) is not int or not 0 <= tid < 2**63 for tid in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError('invalid marker contact identities')
    mode, active, sampled_at, snap = (motion[k] for k in ('mode', 'active', 'sampled_at', 'snap'))
    if (mode not in ('position', 'direct') or type(active) is not bool or type(snap) is not bool
            or type(sampled_at) not in (int, float) or not math.isfinite(sampled_at) or sampled_at < 0
            or (mode == 'position' and len(rings) != 1)
            or (mode == 'direct' and active != bool(rings))):
        raise ValueError('invalid marker motion state')
    return MarkerSample(rings, tuple(ids), mode, active, sampled_at, snap)


def sample_payload(rings, motion):
    payload = {'contacts': validate_rings(rings), 'motion': dict(motion)}
    sample = decode_sample(payload)
    payload['motion']['ids'] = sample.ids
    return payload
