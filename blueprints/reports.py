"""
reports.py
=====================================================================
Inventory change history and the 'added this week' drill-down.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"reports.<function_name>" for url_for().
=====================================================================
"""
from flask import Blueprint, render_template
from db import SessionLocal
from models import Inventory, InventoryAudit
from permissions import is_basic_user
from services.audit_helpers import (format_audit_value, format_eastern, hidden_actions_for,
                                    resolve_item_name, week_ago_cutoff)

bp = Blueprint("reports", __name__)


@bp.route("/reports/added-this-week")
def added_this_week_items():
    db = SessionLocal()

    # Same cutoff as the dashboard's "Added This Week" count, so the
    # number on the card always matches what shows up here.
    logs = (
        db.query(InventoryAudit)
        .filter(InventoryAudit.action == "ADD", InventoryAudit.changed_at >= week_ago_cutoff())
        .order_by(InventoryAudit.changed_at.desc())
        .all()
    )

    item_names = {str(item.id): item.name for item in db.query(Inventory).all()}
    for log in logs:
        log.item_name = resolve_item_name(item_names, log.item_id)
        log.changed_at_display = format_eastern(log.changed_at, fmt="%Y-%m-%d %I:%M %p %Z")

    db.close()
    return render_template("added_this_week.html", logs=logs, title="Added This Week")


@bp.route("/reports")
def reports():
    db = SessionLocal()
    # Hide elevated-only actions (PURGE) from basic-permissions users.
    # Filtered in the query, so those rows never reach the page at all.
    hidden = hidden_actions_for(is_basic_user())
    log_query = db.query(InventoryAudit)
    if hidden:
        log_query = log_query.filter(InventoryAudit.action.notin_(hidden))
    logs = log_query.order_by(InventoryAudit.changed_at.desc()).all()

    # Map item_id -> item name for display
    item_names = {
        str(item.id): item.name
        for item in db.query(Inventory).all()
    }

    for log in logs:
        log.item_name = resolve_item_name(item_names, log.item_id)
        log.changed_at_display = format_eastern(log.changed_at, fmt="%Y-%m-%d %I:%M %p %Z")
        log.old_value_display = format_audit_value(log.field_name, log.old_value)
        log.new_value_display = format_audit_value(log.field_name, log.new_value)

    db.close()
    return render_template("reports.html", logs=logs, show_purge_filter=not hidden, title="Reports")
