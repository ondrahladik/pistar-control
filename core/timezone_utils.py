from __future__ import annotations

from datetime import datetime, time as datetime_time, timezone
from typing import TYPE_CHECKING, Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None
    available_timezones = None

    class ZoneInfoNotFoundError(Exception):
        pass
else:
    from zoneinfo import available_timezones

try:
    import pytz
except ImportError:  # pragma: no cover - optional runtime fallback
    pytz = None

if TYPE_CHECKING:
    from core.config import ConfigStore


_SYSTEM_TIMEZONE = datetime.now().astimezone().tzinfo or timezone.utc
_SYSTEM_TIMEZONE_NAME = (
    getattr(_SYSTEM_TIMEZONE, "key", None)
    or datetime.now(_SYSTEM_TIMEZONE).tzname()
    or "UTC"
)


def get_configured_timezone_name(config_store: "ConfigStore") -> str:
    return config_store.get_timezone_name()


def get_effective_timezone_name(timezone_name: Optional[str]) -> str:
    tzinfo = resolve_timezone(timezone_name)
    return getattr(tzinfo, "key", None) or datetime.now(tzinfo).tzname() or "UTC"


def resolve_timezone(timezone_name: Optional[str]):
    normalized_name = (timezone_name or "").strip()
    if normalized_name.lower() in {"", "system", "local", "default"}:
        return _SYSTEM_TIMEZONE

    try:
        if ZoneInfo is not None:
            return ZoneInfo(normalized_name)
        if pytz is not None:
            return pytz.timezone(normalized_name)
        raise ZoneInfoNotFoundError(normalized_name)
    except ZoneInfoNotFoundError:
        return _SYSTEM_TIMEZONE


def format_current_time(timezone_name: Optional[str], pattern: str = "%H:%M:%S") -> str:
    return datetime.now(resolve_timezone(timezone_name)).strftime(pattern)


def convert_local_time(
    value: Optional[str],
    target_timezone_name: Optional[str],
    source_timezone_name: Optional[str] = None,
) -> Optional[str]:
    if not value:
        return value

    try:
        parsed_time = datetime.strptime(value, "%H:%M:%S").time()
    except ValueError:
        return value

    source_timezone = resolve_timezone(source_timezone_name)
    target_timezone = resolve_timezone(target_timezone_name)
    source_now = datetime.now(source_timezone)
    source_datetime = _build_timezone_aware_datetime(source_now.date(), parsed_time, source_timezone)
    return source_datetime.astimezone(target_timezone).strftime("%H:%M:%S")


def get_system_timezone_name() -> str:
    return _SYSTEM_TIMEZONE_NAME


def get_available_timezone_names() -> list[str]:
    timezone_names = set()

    if available_timezones is not None:
        try:
            timezone_names.update(available_timezones())
        except Exception:
            pass

    if pytz is not None:
        timezone_names.update(getattr(pytz, "common_timezones", []))

    if not timezone_names:
        timezone_names.update({
            "UTC",
            "Europe/Prague",
            "Europe/London",
            "Europe/Berlin",
            "America/New_York",
            "America/Los_Angeles",
            "Asia/Tokyo",
        })

    timezone_names.discard("localtime")
    return ["system"] + sorted(timezone_names)


def _normalize_time(value: datetime_time) -> datetime_time:
    return value.replace(microsecond=0)


def _build_timezone_aware_datetime(date_value, time_value: datetime_time, tzinfo):
    normalized_time = _normalize_time(time_value)
    naive_datetime = datetime.combine(date_value, normalized_time)
    if hasattr(tzinfo, "localize"):
        return tzinfo.localize(naive_datetime)
    return naive_datetime.replace(tzinfo=tzinfo)
