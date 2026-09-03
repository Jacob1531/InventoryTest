"""
main.py
=====================================================================
Dashboard, favicon, and one-time database migration routes.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"main.<function_name>" for url_for().
=====================================================================
"""
from flask import Blueprint, current_app, render_template
from sqlalchemy import text
from db import SessionLocal, engine
from models import (DashboardPreference, FileSubmission, HardwareDocument, HardwareItem,
                    HardwareNote, Inventory, InventoryAudit, InventoryOrder)
from services.chart_data import build_chart, DEFAULT_LIMIT, DEFAULT_MODE
from permissions import is_basic_user
from services.audit_helpers import (format_eastern, hidden_actions_for, resolve_item_name,
                                    week_ago_cutoff)
from services.order_logic import compute_on_order_totals
from auth import get_user

bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    db = SessionLocal()

    active_items = db.query(Inventory).filter(Inventory.is_active == True).all()

    total_items = len(active_items)
    low_stock_count = sum(
        1 for item in active_items
        if item.low_stock_threshold is not None and item.quantity is not None
        and item.quantity < item.low_stock_threshold
    )

    week_ago = week_ago_cutoff()
    added_this_week = (
        db.query(InventoryAudit)
        .filter(InventoryAudit.action == "ADD", InventoryAudit.changed_at >= week_ago)
        .count()
    )

    item_names = {str(item.id): item.name for item in db.query(Inventory).all()}
    # Same elevated-only filtering as the Reports page, so a basic user's
    # Recent Activity can't surface a PURGE they aren't allowed to see.
    hidden = hidden_actions_for(is_basic_user())
    recent_query = db.query(InventoryAudit)
    if hidden:
        recent_query = recent_query.filter(InventoryAudit.action.notin_(hidden))
    recent_logs = (
        recent_query
        .order_by(InventoryAudit.changed_at.desc())
        .limit(5)
        .all()
    )
    for log in recent_logs:
        log.item_name = resolve_item_name(item_names, log.item_id)
        log.changed_at_display = format_eastern(log.changed_at)

    # Per-user chart preferences; absent row -> defaults, nothing to backfill.
    pref = (
        db.query(DashboardPreference)
        .filter(DashboardPreference.user_key == get_user())
        .first()
    )
    chart_mode = pref.chart_mode if pref else DEFAULT_MODE
    chart_category = pref.chart_category if pref else None
    chart_limit = pref.chart_limit if pref else DEFAULT_LIMIT

    pending_orders = db.query(InventoryOrder).filter(InventoryOrder.status == "PENDING").all()
    on_order_totals = compute_on_order_totals(pending_orders)

    chart = build_chart(
        active_items,
        mode=chart_mode,
        category=chart_category,
        limit=chart_limit,
        on_order_totals=on_order_totals,
    )

    db.close()

    stats = {
        "total_items": total_items,
        "low_stock_count": low_stock_count,
        "added_this_week": added_this_week,
    }

    return render_template(
        "dashboard.html",
        title="Dashboard",
        stats=stats,
        recent_logs=recent_logs,
        chart=chart,
    )


@bp.route('/favicon.ico')
def favicon():
    # current_app rather than a direct `app` reference: blueprints are
    # registered onto the app, not the other way around, so importing the
    # app object here would be a circular import.
    return current_app.send_static_file('favicon.png')


@bp.route("/create-indexes-once")
def create_indexes_once():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_inventory_is_active ON inventory (is_active)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_name_lower ON inventory (lower(name))",
        "CREATE INDEX IF NOT EXISTS ix_inventory_audit_item_id ON inventory_audit (item_id)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_audit_changed_at ON inventory_audit (changed_at)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_audit_changed_by_changed_at ON inventory_audit (changed_by, changed_at)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_audit_action_changed_at ON inventory_audit (action, changed_at)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_order_status ON inventory_order (status)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_order_ordered_at ON inventory_order (ordered_at)",
        "CREATE INDEX IF NOT EXISTS ix_inventory_order_item_status ON inventory_order (item_id, status)",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()
    return f"Created (or confirmed existing) {len(statements)} indexes - remove this route now."


@bp.route("/create-files-table-once")
def create_files_table_once():
    FileSubmission.__table__.create(bind=engine, checkfirst=True)
    return "file_submission table created (or already existed) - remove this route now."


@bp.route("/add-file-category-column-once")
def add_file_category_column_once():
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE file_submission ADD COLUMN IF NOT EXISTS category VARCHAR"))
        conn.commit()
    return "category column added (or already existed) - remove this route now."


# ONE-TIME MIGRATION - visit this URL once to create the three tables
# behind the Hardware & Warranty section, then DELETE THIS ROUTE. Safe to
# run more than once - checkfirst=True skips any table that already
# exists rather than erroring.
@bp.route("/create-hardware-tables-once")
def create_hardware_tables_once():
    for model in (HardwareItem, HardwareDocument, HardwareNote):
        model.__table__.create(bind=engine, checkfirst=True)
    return "hardware tables created (or already existed) - remove this route now."


# ONE-TIME MIGRATION - visit this URL once to create the dashboard_preference
# table (per-user chart settings), then DELETE THIS ROUTE. Safe to run more
# than once - checkfirst=True skips creation if it already exists.
@bp.route("/create-dashboard-pref-table-once")
def create_dashboard_pref_table_once():
    DashboardPreference.__table__.create(bind=engine, checkfirst=True)
    return "dashboard_preference table created (or already existed) - remove this route now."


# ONE-TIME MIGRATION - visit this URL once to add the "site" column to
# hardware_item (the table predates it), then DELETE THIS ROUTE.
@bp.route("/add-hardware-site-column-once")
def add_hardware_site_column_once():
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE hardware_item ADD COLUMN IF NOT EXISTS site VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hardware_item_site ON hardware_item (site)"))
        conn.commit()
    return "site column added (or already existed) - remove this route now."
