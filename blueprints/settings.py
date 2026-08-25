"""
settings.py
=====================================================================
Settings hub, database settings (threshold/purge), and account settings.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"settings.<function_name>" for url_for().
=====================================================================
"""
import os
from flask import Blueprint, flash, redirect, render_template, request, send_from_directory, url_for
from db import SessionLocal
from models import DashboardPreference, Inventory, InventoryAudit
from services.audit_helpers import format_audit_value, format_eastern, resolve_item_name
from services.chart_data import (DEFAULT_LIMIT, DEFAULT_MODE, MODE_LABELS, VALID_LIMITS,
                                 normalize_limit, normalize_mode)
from services.group_access import GroupCheckError, is_basic_permissions_user
from auth import get_user, get_user_id
from permissions import require_elevated_access

bp = Blueprint("settings", __name__)


@bp.route("/settings")
def settings():
    try:
        db_settings_restricted = is_basic_permissions_user(get_user_id())
    except GroupCheckError as e:
        print(f"Database Settings access check failed on Settings page, showing as restricted: {e}")
        db_settings_restricted = True

    return render_template(
        "settings.html",
        title="Settings",
        db_settings_restricted=db_settings_restricted,
    )


@bp.route("/settings/database")
@require_elevated_access
def database_settings():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()
    inactive_items = (
        db.query(Inventory)
        .filter(Inventory.is_active == False)
        .order_by(Inventory.name.asc())
        .all()
    )
    db.close()
    return render_template(
        "database_settings.html",
        items=items,
        inactive_items=inactive_items,
        title="Database Settings",
    )


@bp.route("/settings/database/update/<int:item_id>", methods=["POST"])
@require_elevated_access
def update_threshold(item_id):
    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()
        if not item:
            return "Item not found", 404

        threshold = request.form.get("threshold")
        item.low_stock_threshold = int(threshold) if threshold else None

        db.commit()
        flash(f'Low-stock threshold updated for "{item.name}".', "success")
        return redirect(url_for("settings.database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to update threshold: {str(e)}", 500
    finally:
        db.close()


@bp.route("/settings/database/purge/<int:item_id>", methods=["POST"])
@require_elevated_access
def purge_inactive_item(item_id):
    """Permanently deletes a single inactive (already soft-deleted) item.
    Its audit trail is kept, not deleted, and this action itself is logged
    as a PURGE entry so there's a record that it happened. Irreversible -
    unlike the normal delete flow, there is no is_active flag to flip back."""
    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()
        if not item:
            return "Item not found", 404
        if item.is_active:
            return "Only inactive (already deleted) items can be permanently removed.", 400

        name = item.name
        db.add(InventoryAudit(
            item_id=str(item.id),
            action="PURGE",
            field_name=None,
            old_value=None,
            new_value=name,
            changed_by=get_user(),
            source="UI",
        ))
        db.delete(item)
        db.commit()

        flash(f'"{name}" was permanently removed.', "success")
        return redirect(url_for("settings.database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to remove item: {str(e)}", 500
    finally:
        db.close()


@bp.route("/settings/database/purge-all-inactive", methods=["POST"])
@require_elevated_access
def purge_all_inactive_items():
    """Permanently deletes every inactive item in one transaction - all or
    nothing. Audit trails are kept, and each removal is itself logged as a
    PURGE entry."""
    db = SessionLocal()
    try:
        inactive_items = db.query(Inventory).filter(Inventory.is_active == False).all()
        count = len(inactive_items)
        remover = get_user()

        for item in inactive_items:
            db.add(InventoryAudit(
                item_id=str(item.id),
                action="PURGE",
                field_name=None,
                old_value=None,
                new_value=item.name,
                changed_by=remover,
                source="UI",
            ))
            db.delete(item)

        db.commit()
        flash(f"Permanently removed {count} inactive item{'s' if count != 1 else ''}.", "success")
        return redirect(url_for("settings.database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to remove inactive items: {str(e)}", 500
    finally:
        db.close()


@bp.route("/settings/account")
def account_settings():
    current_user = get_user()

    db = SessionLocal()
    item_names = {str(item.id): item.name for item in db.query(Inventory).all()}
    my_logs = (
        db.query(InventoryAudit)
        .filter(InventoryAudit.changed_by == current_user)
        .order_by(InventoryAudit.changed_at.desc())
        .all()
    )
    for log in my_logs:
        log.item_name = resolve_item_name(item_names, log.item_id)
        log.changed_at_display = format_eastern(log.changed_at, fmt="%Y-%m-%d %I:%M %p %Z")
        log.old_value_display = format_audit_value(log.field_name, log.old_value)
        log.new_value_display = format_audit_value(log.field_name, log.new_value)

    pref = (
        db.query(DashboardPreference)
        .filter(DashboardPreference.user_key == current_user)
        .first()
    )
    chart_pref = {
        "mode": pref.chart_mode if pref else DEFAULT_MODE,
        "category": pref.chart_category if pref else None,
        "limit": pref.chart_limit if pref else DEFAULT_LIMIT,
    }

    # Categories that actually exist, so the filter dropdown can't offer
    # something with no data behind it.
    available_categories = sorted({
        (item.category or "").strip() or "Uncategorized"
        for item in db.query(Inventory).filter(Inventory.is_active == True).all()
    })

    db.close()

    return render_template(
        "account_settings.html",
        current_user=current_user,
        my_logs=my_logs,
        chart_pref=chart_pref,
        available_categories=available_categories,
        chart_modes=MODE_LABELS,
        chart_limits=VALID_LIMITS,
        title="Account Settings",
    )


@bp.route("/settings/account/dashboard-chart", methods=["POST"])
def save_dashboard_chart_preference():
    """Saves the signed-in user's dashboard chart settings. Creates their
    preference row on first save - rows are lazy, so users who never touch
    this just keep the defaults."""
    current_user = get_user()

    mode = normalize_mode(request.form.get("chart_mode"))
    limit = normalize_limit(request.form.get("chart_limit"))
    category = (request.form.get("chart_category") or "").strip() or None

    db = SessionLocal()
    try:
        # Only accept a category that currently exists, so a stale or
        # hand-crafted value can't leave the chart permanently empty.
        if category:
            existing = {
                (item.category or "").strip() or "Uncategorized"
                for item in db.query(Inventory).filter(Inventory.is_active == True).all()
            }
            if category not in existing:
                category = None

        pref = (
            db.query(DashboardPreference)
            .filter(DashboardPreference.user_key == current_user)
            .first()
        )
        if pref is None:
            pref = DashboardPreference(user_key=current_user)
            db.add(pref)

        pref.chart_mode = mode
        pref.chart_category = category
        pref.chart_limit = limit
        db.commit()

        flash("Dashboard chart settings saved.", "success")
        return redirect(url_for("settings.account_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to save chart settings: {str(e)}", 500
    finally:
        db.close()
