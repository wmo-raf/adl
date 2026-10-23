from datetime import timedelta, timezone as py_tz

from django.db import connection


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=py_tz.utc)
    return value.astimezone(py_tz.utc)


def hour_aligned_window(start, end):
    """Widen ``[start, end]`` to whole UTC hours, end exclusive.

    ``refresh_continuous_aggregate`` works on whole buckets. The window starts
    at the hour containing ``start`` and ends one hour after the hour
    containing ``end``. Naive datetimes are taken as UTC.
    """
    start, end = _as_utc(start), _as_utc(end)
    aligned_start = start.replace(minute=0, second=0, microsecond=0)
    aligned_end = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return aligned_start, aligned_end


def refresh_hourly_aggregate(start, end):
    """Refresh ``obs_agg_1h`` for the hours covering ``[start, end]``.

    The aggregate's policy only refreshes the last 90 days, so a save into an
    older window is invisible in ``HourlyObsAgg`` until this runs. TimescaleDB
    refuses to refresh inside a transaction; call this outside one.
    """
    window_start, window_end = hour_aligned_window(start, end)
    with connection.cursor() as cursor:
        cursor.execute(
            "CALL refresh_continuous_aggregate('obs_agg_1h', %s, %s);",
            [window_start, window_end],
        )
