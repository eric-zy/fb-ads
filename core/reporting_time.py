"""Insights dates follow the ad account timezone; unknown timezones use UTC."""
from datetime import datetime, timezone
import pytz


def account_today(account, now=None):
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    try:
        zone = pytz.timezone(getattr(account, "timezone", None) or "UTC")
    except (pytz.UnknownTimeZoneError, ValueError):
        zone = timezone.utc
    return instant.astimezone(zone).date()
