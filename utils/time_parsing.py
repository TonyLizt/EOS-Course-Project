"""Deterministic UTC parsing for the legacy orbit epoch contract (no JVM)."""

from datetime import datetime, timezone
import math
import re

EPOCH_PARSER_VERSION = "epoch_parser_v1"
_MONTHS = {name: index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
_ENGLISH = re.compile(
    r"(\d{1,2}) ([A-Za-z]{3}) (\d{4}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?"
)


def parse_orbit_epoch(value, *, satellite_id=None, field_name="epoch"):
    """Return an aware UTC datetime; naive legacy values mean UTC.

    Numeric inputs are finite Unix seconds (booleans are not timestamps).
    English month names use a fixed mapping, never the process locale.
    Invalid physical inputs always raise ValueError with their source context.
    """
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, bool):
            raise ValueError("boolean is not a Unix timestamp")
        elif isinstance(value, (int, float)):
            if not math.isfinite(value):
                raise ValueError("Unix timestamp must be finite")
            result = datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("empty date")
            match = _ENGLISH.fullmatch(text)
            if match:
                day, month, year, hour, minute, second, fraction = match.groups()
                if month not in _MONTHS:
                    raise ValueError(f"unsupported English month {month!r}")
                result = datetime(int(year), _MONTHS[month], int(day), int(hour),
                                  int(minute), int(second), int((fraction or "0").ljust(6, "0")))
            else:
                # Preserve the two legacy slash formats, with no locale lookup.
                if re.fullmatch(r"\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2}", text):
                    text = text.replace("/", "-")
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                result = datetime.fromisoformat(text)
        else:
            raise ValueError(f"unsupported type {type(value).__name__}")
        if result.tzinfo is None:
            return result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise ValueError(
            f"satellite_id={satellite_id!r} field={field_name!r} value={value!r}: {exc}"
        ) from exc
