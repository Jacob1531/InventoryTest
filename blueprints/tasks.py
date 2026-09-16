"""
tasks.py
=====================================================================
Endpoints meant to be called by a SCHEDULER, not by a person.

The app has no built-in scheduler, so warranty alerts are driven by an
external daily trigger (Azure Logic App, Automation runbook, Function
timer, or any cron that can make an HTTPS request) hitting the route
below once a day.

SECURITY
--------
This route is guarded by a shared secret in the X-Task-Token header,
compared in constant time. That guard is independent of Easy Auth -
which normally sits in front of everything - because a scheduler can't
complete an interactive sign-in. See the deployment notes in the route
docstring for how to let the scheduler through Easy Auth.

The endpoint is idempotent: running it twice in a day sends nothing the
second time, because every alert is recorded and checked before
sending. That makes it safe to retry after a failure.
=====================================================================
"""
import hmac
import os
from datetime import date

from flask import Blueprint, jsonify, request

from db import SessionLocal
from models import HardwareItem, WarrantyNotification
from services.notifications import send_warranty_alert_email
from services.warranty_alerts import (MILESTONE_LABELS, MILESTONE_SUBJECTS,
                                      alerts_due)

bp = Blueprint("tasks", __name__)

TASK_TOKEN = os.getenv("TASK_TOKEN")


def _token_ok(supplied):
    """Constant-time comparison - a plain == would leak the token one
    character at a time to anyone able to measure response timing."""
    if not TASK_TOKEN or not supplied:
        return False
    return hmac.compare_digest(supplied, TASK_TOKEN)


@bp.route("/tasks/warranty-alerts", methods=["POST"])
def warranty_alerts_task():
    """Sends warranty expiry alerts to the admin group.

    Call this ONCE A DAY. It emails one message per milestone reached
    (60 days out, 30 days out, expired), each listing every item that hit
    that milestone, so ten expiring laptops produce one email rather than
    ten.

    Requires the X-Task-Token header to match the TASK_TOKEN app setting.

    DEPLOYMENT: Easy Auth sits in front of the whole app, so a scheduler
    is blocked before reaching this code. Either add /tasks/* to the Easy
    Auth excludedPaths, or give the caller an identity Easy Auth accepts.
    The token check here is what protects the route in either case.
    """
    if not _token_ok(request.headers.get("X-Task-Token")):
        # Deliberately vague: confirming whether the token was missing vs
        # wrong tells an unauthenticated caller more than it needs to.
        return jsonify({"error": "Unauthorized"}), 401

    today = date.today()
    db = SessionLocal()
    try:
        items = (
            db.query(HardwareItem)
            .filter(
                HardwareItem.is_active == True,
                HardwareItem.warranty_expires.isnot(None),
            )
            .all()
        )

        # Everything already sent, keyed by the expiry it was sent for -
        # so an edited warranty date re-arms its milestones automatically.
        already_sent = {
            (n.hardware_id, n.milestone, n.warranty_expires)
            for n in db.query(WarrantyNotification).all()
        }

        due = alerts_due(items, already_sent, today)

        results = {}
        for milestone, milestone_items in due.items():
            # Send FIRST, record second. If the send fails we raise before
            # writing anything, so the next run retries rather than
            # recording an email that never arrived.
            sent_count = send_warranty_alert_email(
                milestone,
                milestone_items,
                subject=MILESTONE_SUBJECTS[milestone],
                heading=MILESTONE_LABELS[milestone],
            )
            if not sent_count:
                # No recipients configured - don't record it as sent, so it
                # goes out once the group is populated.
                results[milestone] = 0
                continue

            for item in milestone_items:
                db.add(WarrantyNotification(
                    hardware_id=item.id,
                    milestone=milestone,
                    warranty_expires=item.warranty_expires,
                ))
            results[milestone] = len(milestone_items)

        db.commit()
        return jsonify({
            "ok": True,
            "date": today.isoformat(),
            "checked": len(items),
            "sent": results,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()
