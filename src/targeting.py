import json
import math

MIN_CONFIDENCE = 0.85


def parse_target(text):
    """Fail closed: one unambiguous, normalized target only."""
    value = json.loads(text)
    if not isinstance(value, dict) or value.get('status') != 'ok':
        raise ValueError('No unambiguous answer')
    for key in ('x', 'y', 'confidence'):
        n = value.get(key)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
            raise ValueError('Invalid numeric target')
        if not 0 <= n <= 1:
            raise ValueError('Target outside image')
    if value['confidence'] < MIN_CONFIDENCE:
        raise ValueError('Low confidence')
    return value


def screen_point(target, bounds):
    left, top, width, height = bounds
    return (left + round(target['x'] * (width - 1)),
            top + round(target['y'] * (height - 1)))


def eased_point(start, end, fraction):
    t = max(0, min(1, fraction))
    t = t * t * (3 - 2 * t)
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))
