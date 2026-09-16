"""
warranty_alerts.py
=====================================================================
Decides which hardware warranties need an alert email today.

Three milestones: 60 days out, 30 days out, and expired.

Two design points worth knowing:

1. Milestones are "at or past", not "exactly on". If the scheduled job
   fails to run for a few days, an item that slipped from 61 to 58 days
   still gets its 60-day alert on the next successful run. Exact-day
   matching would have silently skipped it forever.

2. Whether an alert was already sent is recorded against the expiry
   date it was sent FOR. So if someone extends a warranty, the old
   records no longer match the new date and the milestones naturally
   re-arm - without needing any explicit "reset" step.

Pure and DB-independent so all of this is unit testable.
=====================================================================
"""
from datetime import date

MILESTONE_60 = "DAY_60"
MILESTONE_30 = "DAY_30"
MILESTONE_EXPIRED = "EXPIRED"

# Checked in order, most urgent first - an item only ever gets its single
# most urgent outstanding milestone, so something 20 days out doesn't
# generate both a 30-day and a 60-day notice in the same run.
MILESTONES = [
    (MILESTONE_EXPIRED, 0),
    (MILESTONE_30, 30),
    (MILESTONE_60, 60),
]

MILESTONE_LABELS = {
    MILESTONE_60: "Expiring in 60 days",
    MILESTONE_30: "Expiring in 30 days",
    MILESTONE_EXPIRED: "Warranty expired",
}

# Subject lines, kept here so the wording lives with the logic that
# chooses it rather than being buried in the sending code.
MILESTONE_SUBJECTS = {
    MILESTONE_60: "Hardware warranties expiring in 60 days",
    MILESTONE_30: "Hardware warranties expiring in 30 days",
    MILESTONE_EXPIRED: "Hardware warranties have expired",
}


def days_until(expiry, today=None):
    today = today or date.today()
    return (expiry - today).days


def current_milestone(expiry, today=None):
    """The most urgent milestone an item has reached, or None if its
    warranty is still further out than 60 days (or absent)."""
    if expiry is None:
        return None
    remaining = days_until(expiry, today)
    for name, threshold in MILESTONES:
        if remaining <= threshold:
            return name
    return None


def alerts_due(items, already_sent, today=None):
    """Works out which items need an alert now.

    `items` need .id and .warranty_expires.
    `already_sent` is a set of (hardware_id, milestone, expiry_date)
    tuples - note the expiry date is part of the key, which is what makes
    an edited warranty re-arm.

    Returns {milestone: [items]}, containing only milestones that have
    something to report, so the caller sends no empty emails.
    """
    today = today or date.today()
    due = {}

    for item in items:
        milestone = current_milestone(item.warranty_expires, today)
        if milestone is None:
            continue
        if (item.id, milestone, item.warranty_expires) in already_sent:
            continue
        due.setdefault(milestone, []).append(item)

    # Stable ordering: soonest expiry first within each milestone, so the
    # email reads in priority order.
    for milestone in due:
        due[milestone].sort(key=lambda i: (i.warranty_expires, (i.name or "").lower()))

    return due
