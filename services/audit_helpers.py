"""
audit_helpers.py
=====================================================================
Pure, DB-independent formatting/lookup helpers used when displaying
audit log entries (Reports, Recent Activity, My Activity, Added This
Week). Kept separate from app.py so they can be unit tested directly
without needing Flask, SQLAlchemy, or a live database - none of these
functions touch either.
=====================================================================
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# All timestamps are stored naive/UTC (Postgres server default). This
# converts them to US Eastern (auto-adjusts for EST/EDT) for display only.
_UTC = ZoneInfo("UTC")
_EASTERN = ZoneInfo("America/New_York")

# Only these audit fields are ever truly numeric - scoping the scientific
# notation formatting to just these avoids misformatting something like an
# item name or category that happens to be a numeric-looking string.
_NUMERIC_AUDIT_FIELDS = {"quantity", "price"}


def format_eastern(dt, fmt="%b %d, %I:%M %p %Z"):
    if dt is None:
        return ""
    return dt.replace(tzinfo=_UTC).astimezone(_EASTERN).strftime(fmt)


def format_audit_value(field_name, value):
    """Display-only formatting: values stored in the DB are never touched.
    Any quantity/price value beyond +/-999999 is shown in scientific
    notation so a bad input (accidental or otherwise) can't blow out the
    Reports table's layout."""
    if value is None or field_name not in _NUMERIC_AUDIT_FIELDS:
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if abs(num) > 999999:
        return f"{num:.2e}"
    return value


def week_ago_cutoff():
    """Shared 7-day cutoff so the dashboard's 'Added This Week' count and
    the drill-down page behind it always use the exact same boundary.
    Returns a naive datetime (matching how every timestamp in this app is
    stored) - datetime.now(timezone.utc).replace(tzinfo=None) is the
    non-deprecated equivalent of datetime.utcnow(), stripped back to
    naive so it compares cleanly against naive DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)


def resolve_item_name(item_names, item_id):
    """Looks up an audit row's item name from the current Inventory table.
    Falls back to a readable placeholder (rather than a bare numeric ID)
    for items that have since been permanently purged - their audit
    history is kept, but there's no live row left to resolve the name
    from, so this keeps that history legible instead of showing "47"."""
    name = item_names.get(item_id)
    return name if name is not None else f"Item #{item_id} (deleted)"
