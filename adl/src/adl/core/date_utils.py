from django.utils import timezone as dj_timezone


def make_record_timezone_aware(value, timezone):
    if dj_timezone.is_aware(value):
        aware_value = value.astimezone(timezone)
    else:
        # naive
        aware_value = dj_timezone.make_aware(value, timezone=timezone)
    return aware_value
