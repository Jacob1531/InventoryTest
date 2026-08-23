"""
hardware_logic.py
=====================================================================
Pure, DB-independent logic for hardware warranty status. Kept separate
from the routes so it can be unit tested directly without a database
or a Flask request context.
=====================================================================
"""
from datetime import date, timedelta

# How far ahead counts as "expiring soon" rather than simply "active".
EXPIRING_SOON_DAYS = 60

STATUS_NONE = "NONE"          # no warranty expiry recorded
STATUS_EXPIRED = "EXPIRED"
STATUS_EXPIRING = "EXPIRING"
STATUS_ACTIVE = "ACTIVE"

STATUS_LABELS = {
    STATUS_NONE: "No warranty",
    STATUS_EXPIRED: "Expired",
    STATUS_EXPIRING: "Expiring soon",
    STATUS_ACTIVE: "Under warranty",
}


def warranty_status(warranty_expires, today=None):
    """Returns one of the STATUS_* constants for a given expiry date.

    `today` is injectable so tests don't depend on the real clock.
    Boundaries: a warranty expiring exactly today is NOT yet EXPIRED
    (it lapses only once the day has passed), but it does fall inside
    the EXPIRING window. The EXPIRING_SOON_DAYS boundary is inclusive,
    so exactly 60 days out is EXPIRING and 61 days out is ACTIVE.
    """
    if warranty_expires is None:
        return STATUS_NONE

    today = today or date.today()

    if warranty_expires < today:
        return STATUS_EXPIRED
    if warranty_expires <= today + timedelta(days=EXPIRING_SOON_DAYS):
        return STATUS_EXPIRING
    return STATUS_ACTIVE


def days_until_expiry(warranty_expires, today=None):
    """Whole days until the warranty lapses. Negative once it already
    has; None when no expiry is recorded."""
    if warranty_expires is None:
        return None
    today = today or date.today()
    return (warranty_expires - today).days


def summarize_warranties(items, today=None):
    """Counts items by warranty status, for the page's summary cards.
    Accepts anything with a .warranty_expires attribute."""
    today = today or date.today()
    counts = {STATUS_ACTIVE: 0, STATUS_EXPIRING: 0, STATUS_EXPIRED: 0, STATUS_NONE: 0}
    for item in items:
        counts[warranty_status(item.warranty_expires, today)] += 1
    return counts
