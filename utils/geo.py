from math import atan2, cos, radians, sin, sqrt

# Telegram reports horizontal_accuracy in [0, 1500] m; a fix with no accuracy at
# all is common on older clients, so treat it as "typical smartphone GPS" rather
# than perfect.
_DEFAULT_ACCURACY_M = 15.0
_MAX_FUSE_AGE_S = 20.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two WGS-84 coordinates."""
    R = 6_371_000
    φ1, φ2 = radians(lat1), radians(lat2)
    dφ = radians(lat2 - lat1)
    dλ = radians(lon2 - lon1)
    a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def fuse_fix(
    prev_lat: float | None,
    prev_lon: float | None,
    prev_accuracy: float | None,
    prev_age_s: float | None,
    new_lat: float,
    new_lon: float,
    new_accuracy: float | None,
) -> tuple[float, float]:
    """
    Cheap inverse-variance fusion of the new GPS fix with the previous one —
    but ONLY when the two fixes plausibly describe the same physical spot.

    A single raw fix from a phone can jump a few metres between updates
    (multipath, momentary loss of a satellite, etc.) while the player is
    standing still, which is what makes a "just reached the point" check
    flicker; blending two such fixes by 1/accuracy² (the same idea used in a
    basic Kalman filter) fixes that.

    But during live-location tracking while walking, consecutive fixes are
    genuinely different positions, not noisy readings of the same one — a
    person walking ~1.4 m/s covers 7-28m between typical 5-20s live-location
    ticks. Averaging those pulls the reported position backwards to "where
    they used to be", which is worse than just trusting the latest fix. So
    fusion only kicks in when the implied movement is within the combined
    GPS noise budget (sum of both accuracies); anything larger is treated as
    real motion and the raw new fix is used as-is.

    Only ever blends with a previous fix that is fresh (< _MAX_FUSE_AGE_S
    old) — an old fix is definitely a different physical position by then.
    """
    if (
        prev_lat is None
        or prev_lon is None
        or prev_age_s is None
        or prev_age_s > _MAX_FUSE_AGE_S
    ):
        return new_lat, new_lon

    a_prev = prev_accuracy if prev_accuracy and prev_accuracy > 0 else _DEFAULT_ACCURACY_M
    a_new = new_accuracy if new_accuracy and new_accuracy > 0 else _DEFAULT_ACCURACY_M

    moved = haversine_m(prev_lat, prev_lon, new_lat, new_lon)
    if moved > a_prev + a_new:
        return new_lat, new_lon

    w_prev = 1 / (a_prev ** 2)
    w_new = 1 / (a_new ** 2)
    total = w_prev + w_new

    lat = (prev_lat * w_prev + new_lat * w_new) / total
    lon = (prev_lon * w_prev + new_lon * w_new) / total
    return lat, lon
