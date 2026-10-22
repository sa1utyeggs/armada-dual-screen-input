"""Format cached battery telemetry; never read sensors while painting."""
import math
from numbers import Real

from .i18n import msg


def battery_label(stats):
    watts = stats.get('bat_watts')
    if isinstance(watts, Real) and not isinstance(watts, bool) and math.isfinite(watts):
        # Round first so a near-zero discharge does not show a misleading -0.0.
        rounded = round(watts, 1)
        text = '0.0' if rounded == 0 else f'{rounded:+.1f}'.replace('-', '−')
    else:
        text = '—'
    return msg('status.battery_power', value=stats.get('bat_cap', 0), watts=text)
