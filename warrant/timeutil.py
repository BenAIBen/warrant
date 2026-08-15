"""Time helpers shared by the seeder, the scorer and the renderer.

Not in the DESIGN_SPEC.md §9.1 file list — added because seed_db.py, scoring.py,
reasons.py and render.py all need the same ISO-8601 handling and duplicating it
would be the fastest way to make the arithmetic and the rendered dates disagree.
Recorded in README.md under "Deviations from the spec".

All timestamps in this system are ISO-8601 UTC TEXT, 'YYYY-MM-DDTHH:MM:SSZ'
(DESIGN_SPEC.md §3 conventions). String comparison on that format is
chronologically correct, which is why the format is mandatory.
"""

from datetime import datetime, timedelta, timezone

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def parse_ts(text):
    """'2026-08-11T09:00:00Z' -> aware datetime in UTC."""
    return datetime.strptime(text, TS_FORMAT).replace(tzinfo=timezone.utc)


def fmt_ts(dt):
    """aware/naive datetime -> '2026-08-11T09:00:00Z'."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(TS_FORMAT)


def shift(text, **kwargs):
    """Shift an ISO timestamp string by a timedelta and return a string."""
    return fmt_ts(parse_ts(text) + timedelta(**kwargs))


def age_days(as_of_text, ts_text):
    """Float age in days. Float, not int — DESIGN_SPEC.md §4.2 is explicit."""
    delta = parse_ts(as_of_text) - parse_ts(ts_text)
    return delta.total_seconds() / 86400.0


def human_date(ts_text):
    """'2026-08-09T14:22:00Z' -> '9 Aug 2026' (DESIGN_SPEC.md §4.3 {newest_date})."""
    dt = parse_ts(ts_text)
    return "%d %s %d" % (dt.day, MONTHS[dt.month - 1], dt.year)


def human_datetime(ts_text):
    """'2026-08-09T14:22:00Z' -> '9 Aug 2026 14:22 UTC' (evidence drawer, §6.3)."""
    dt = parse_ts(ts_text)
    return "%s %02d:%02d UTC" % (human_date(ts_text), dt.hour, dt.minute)


def relative_phrase(as_of_text, ts_text):
    """{newest_relative} — DESIGN_SPEC.md §4.3, constrained by §8.2.

    §8.2 "must not": never a relative phrase that hides age; never "recently"
    for anything over 14 days. So this escalates days -> weeks -> months and
    always carries a number.
    """
    days = age_days(as_of_text, ts_text)
    if days < 0:
        return "today"
    whole = int(days)
    if whole == 0:
        return "today"
    if whole == 1:
        return "yesterday"
    if whole < 14:
        return "%d days ago" % whole
    if whole < 91:
        weeks = int(round(whole / 7.0))
        return "%d week%s ago" % (weeks, "" if weeks == 1 else "s")
    months = int(round(whole / 30.44))
    return "%d month%s ago" % (months, "" if months == 1 else "s")


def lag_phrase(occurred_at, observed_at):
    """'41 min later' — ingestion lag, DESIGN_SPEC.md §6.3."""
    minutes = int(round((parse_ts(observed_at) - parse_ts(occurred_at)).total_seconds() / 60.0))
    if minutes < 1:
        return "same minute"
    if minutes < 90:
        return "%d min later" % minutes
    hours = minutes / 60.0
    if hours < 48:
        return "%.1f h later" % hours
    return "%.1f days later" % (hours / 24.0)
