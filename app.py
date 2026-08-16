import os
import json
from functools import wraps
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import (Flask, flash, redirect, render_template, request, send_from_directory, url_for)
from flask_wtf.csrf import CSRFProtect
from azure.storage.blob import BlobServiceClient
from sqlalchemy import text, func

from db import SessionLocal, engine
from models import Inventory, InventoryAudit, MAX_NUMERIC_VALUE
from services.inventory_update import update_inventory_quantity
from services.image_handler import generate_image_url, upload_inventory_image, display_filename, is_valid_image_filename
from services.notifications import send_low_stock_email
from services.excel_import import parse_import_file, validate_row, ImportFileError
from services.group_access import is_basic_permissions_user, GroupCheckError

from auth import get_user, get_user_id

app = Flask(__name__)

# Required for CSRF token signing. Set FLASK_SECRET_KEY in the Azure App
# Service configuration (same place as PGUSER/PGPASSWORD/etc).
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY")
csrf = CSRFProtect(app)


@app.context_processor
def inject_current_user():
    """Makes the signed-in user's identity available in every template
    (used by the header's account chip) without passing it through every
    single render_template call."""
    return {"header_user": get_user()}


def require_database_settings_access(view_func):
    """Blocks members of the "basic permissions" Entra ID group from
    Database Settings and its sub-routes (threshold updates, purging
    inactive items). Fails CLOSED: if membership can't be reliably
    determined - missing config, Graph error, no user ID - access is
    denied rather than silently allowed. That's a deliberate choice: the
    failure mode of "the restricted group gets in anyway" is worse than
    "everyone is temporarily blocked until the check works again"."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        try:
            is_basic_permissions = is_basic_permissions_user(get_user_id())
        except GroupCheckError as e:
            print(f"Database Settings access check failed, denying access: {e}")
            return render_template("access_denied.html", reason="check_failed", title="Access Denied"), 403

        if is_basic_permissions:
            return render_template("access_denied.html", reason="restricted_group", title="Access Denied"), 403

        return view_func(*args, **kwargs)
    return wrapped

# All timestamps are stored naive/UTC (Postgres server default). This
# converts them to US Eastern (auto-adjusts for EST/EDT) for display only.
_UTC = ZoneInfo("UTC")
_EASTERN = ZoneInfo("America/New_York")


def format_eastern(dt, fmt="%b %d, %I:%M %p %Z"):
    if dt is None:
        return ""
    return dt.replace(tzinfo=_UTC).astimezone(_EASTERN).strftime(fmt)


# Only these audit fields are ever truly numeric - scoping the scientific
# notation formatting to just these avoids misformatting something like an
# item name or category that happens to be a numeric-looking string.
_NUMERIC_AUDIT_FIELDS = {"quantity", "price"}


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
    the drill-down page behind it always use the exact same boundary."""
    return datetime.utcnow() - timedelta(days=7)


def resolve_item_name(item_names, item_id):
    """Looks up an audit row's item name from the current Inventory table.
    Falls back to a readable placeholder (rather than a bare numeric ID)
    for items that have since been permanently purged - their audit
    history is kept, but there's no live row left to resolve the name
    from, so this keeps that history legible instead of showing "47"."""
    name = item_names.get(item_id)
    return name if name is not None else f"Item #{item_id} (deleted)"


@app.route("/")
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
    recent_logs = (
        db.query(InventoryAudit)
        .order_by(InventoryAudit.changed_at.desc())
        .limit(5)
        .all()
    )
    for log in recent_logs:
        log.item_name = resolve_item_name(item_names, log.item_id)
        log.changed_at_display = format_eastern(log.changed_at)

    db.close()

    stats = {
        "total_items": total_items,
        "low_stock_count": low_stock_count,
        "added_this_week": added_this_week,
    }

    return render_template("dashboard.html", title="Dashboard", stats=stats, recent_logs=recent_logs)


@app.route("/inventory/low-stock")
def low_stock_items():
    db = SessionLocal()

    # Same criteria as the dashboard's "Low Stock Items" count, so the
    # number on the card always matches what shows up here.
    items = (
        db.query(Inventory)
        .filter(
            Inventory.is_active == True,
            Inventory.low_stock_threshold.isnot(None),
            Inventory.quantity < Inventory.low_stock_threshold,
        )
        .order_by(Inventory.quantity.asc())
        .all()
    )

    for item in items:
        item.is_out = item.quantity is not None and item.quantity <= 0

    db.close()
    return render_template("low_stock.html", items=items, title="Low Stock Items")


@app.route("/reports/added-this-week")
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

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.png')


#from db import engine
#from models import Base

#@app.route("/init-db")
#def init_db():
    #Base.metadata.create_all(engine)
    #return "Tables created!"

#can be used as a one time db migration when needed as a workaround
#@app.route("/run-migration-once")
#def run_migration_once():
#    with engine.connect() as conn:
#        #runs the postgresql script to modify the db
#        conn.execute(text("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS low_stock_threshold INTEGER"))
#        conn.commit()
#    return "Migration applied"

# ONE-TIME CLEANUP - visit this URL once to remove the "Meme" test item and
# its audit history, then DELETE THIS ROUTE. It is not gated behind a
# confirmation step and will silently do nothing if the item is already gone,
# so there's no harm in it lingering briefly, but it shouldn't ship in the
# app long-term - it's a maintenance action, not a feature.
@app.route("/cleanup-meme-item")
def cleanup_meme_item():
    with engine.connect() as conn:
        conn.execute(text(
            "DELETE FROM inventory_audit WHERE item_id IN "
            "(SELECT id::text FROM inventory WHERE name = :name)"
        ), {"name": "Meme"})
        conn.execute(text(
            "DELETE FROM inventory WHERE name = :name AND is_active = false"
        ), {"name": "Meme"})
        conn.commit()
    return "Cleanup applied - remove this route now."

@app.route("/check-schema")
def check_schema():
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'inventory'"
        ))
        columns = [row[0] for row in result]
    return {"columns": columns}


@app.route("/inventory")
def inventory():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()

    
    for item in items:
        if item.image_blob_path:
            item.image_url = generate_image_url(item.image_blob_path)
        else:
            item.image_url = None


    db.close()
    return render_template("inventory.html", items=items, title="Inventory")


@app.route("/inventory/update", methods=["POST"])
def update_inventory():
    id = request.form["id"]

    try:
        new_qty = int(request.form["quantity"])
    except (KeyError, ValueError, TypeError):
        return "Invalid numeric input", 400

    if new_qty < 0:
        return "Quantity can't be negative", 400
    if abs(new_qty) > MAX_NUMERIC_VALUE:
        return f"Quantity can't exceed {MAX_NUMERIC_VALUE}", 400

    try:
        update_inventory_quantity(id, new_qty)
    except ValueError as e:
        return str(e), 404

    return redirect(url_for("inventory"))

@app.route("/inventory/edit/<int:item_id>", methods=["POST"])
def edit_inventory_item(item_id):
    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()
        if not item:
            return "Item not found", 404
        
        new_name = request.form.get("name")
        new_category = request.form.get("category")
        new_quantity = int(request.form.get("quantity"))
        new_price = float(request.form.get("price"))

        if not new_name:
            return "Name is required", 400
        if not new_category:
            return "Category is required", 400
        
        try:
            new_quantity = int(new_quantity)
            new_price = float(new_price)
        except:
            return "Invalid numeric input", 400

        if new_quantity < 0:
            return "Quantity can't be negative", 400
        if new_price < 0:
            return "Price can't be negative", 400
        if abs(new_quantity) > MAX_NUMERIC_VALUE or abs(new_price) > MAX_NUMERIC_VALUE:
            return f"Quantity and price can't exceed {MAX_NUMERIC_VALUE}", 400
        
        old_quantity = item.quantity

        changes = []
        if item.name != new_name:
            changes.append(("name", item.name, new_name))
        if item.category != new_category:
            changes.append(("category", item.category, new_category))
        if item.quantity != new_quantity:
            changes.append(("quantity", str(item.quantity), str(new_quantity)))
        if float(item.price) != new_price:
            changes.append(("price", str(item.price), str(new_price)))

        item.name = new_name
        item.category = new_category
        item.quantity = new_quantity
        item.price = new_price

        image_file = request.files.get("image")

        if image_file and image_file.filename:
            if not is_valid_image_filename(image_file.filename):
                return "Error: Only PNG/JPG images allowed.", 400
            image_path = upload_inventory_image(image_file)
            item.image_blob_path = image_path
            changes.append(("image", "previous image", "new image"))

        for field_name, old_value, new_value in changes:
            audit = InventoryAudit(
                item_id=str(item.id),
                action="UPDATE",
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                changed_by=get_user(),
                source="UI"
            )
            db.add(audit)
        
        crossed_threshold = (
            item.low_stock_threshold is not None
            and old_quantity >= item.low_stock_threshold
            and new_quantity < item.low_stock_threshold
        )

        if crossed_threshold:
            try:
                send_low_stock_email(item)
            except Exception as e:
                print(f"Low stock email failed: {e}")

        db.commit()
        flash(f'"{item.name}" was updated.', "success")
        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Update failed: {str(e)}", 500

    finally:
        db.close()


@app.route("/inventory/add", methods=["POST"])
def add_inventory():
    db = SessionLocal()
    #Will likely makle price optional. Also need to eventually do checks against the db
    #to ensure unique entries and no duplicates
    try:
        #Obtains values first
        name = request.form.get("name")
        category = request.form.get("category")
        quantity = request.form.get("quantity")
        price = request.form.get("price")
        image_file = request.files.get("image")

        #Checks validity of fields
        if not all([name, category, quantity, price, image_file]):
            return "Error: All fields including image are required.", 400

        #Checks numbers being valid
        try:
            quantity = int(quantity)
            price = float(price)

            if quantity < 0 or price < 0:
                return "Error: Quantity and price must be positive.", 400
            if abs(quantity) > MAX_NUMERIC_VALUE or abs(price) > MAX_NUMERIC_VALUE:
                return f"Error: Quantity and price can't exceed {MAX_NUMERIC_VALUE}.", 400

        except:
            return "Error: Invalid numeric input.", 400

        #Validates image type
        if not is_valid_image_filename(image_file.filename):
            return "Error: Only PNG/JPG images allowed.", 400

        #uploads only after image passes check
        image_path = upload_inventory_image(image_file)

        item = Inventory(
            name=name,
            category=category,
            quantity=quantity,
            price=price,
            image_blob_path=image_path,
            is_active=True
        )

        db.add(item)
        db.flush()  # populates item.id before commit, needed for the audit entry below

        audit = InventoryAudit(
            item_id=str(item.id),
            action="ADD",
            field_name=None,
            old_value=None,
            new_value=name,
            changed_by=get_user(),
            source="UI"
        )

        db.add(audit)
        db.commit()

        flash(f'"{name}" was added to inventory.', "success")
        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Server error: {str(e)}", 500

    finally:
        db.close()


@app.route("/inventory/import/preview", methods=["POST"])
def import_preview():
    file = request.files.get("file")
    if not file or not file.filename:
        return {"error": "No file was uploaded."}, 400
    if not file.filename.lower().endswith(".xlsx"):
        return {"error": "Please upload a .xlsx file."}, 400

    try:
        raw_rows = parse_import_file(file)
    except ImportFileError as e:
        return {"error": str(e)}, 400

    if not raw_rows:
        return {"error": "That file doesn't have any data rows to import."}, 400

    rows = [validate_row(r) for r in raw_rows]
    return {"rows": rows}


@app.route("/inventory/import/lookup-existing", methods=["POST"])
def import_lookup_existing():
    """Given the finalized (corrected) rows from the review step, reports
    which ones match an existing active item by name, and that item's
    current image filename if it has one. Looked up fresh here (rather
    than at preview time) since names can be edited during review."""
    payload = request.get_json(silent=True)
    if not payload or "rows" not in payload:
        return {"error": "Malformed request."}, 400

    db = SessionLocal()
    results = []
    try:
        for row in payload["rows"]:
            name = str(row.get("name", "")).strip()
            existing = (
                db.query(Inventory)
                .filter(Inventory.is_active == True, func.lower(Inventory.name) == name.lower())
                .first()
                if name else None
            )
            results.append({
                "existing_item_id": existing.id if existing else None,
                "existing_image_filename": display_filename(existing.image_blob_path) if existing else None,
            })
    finally:
        db.close()

    return {"rows": results}


@app.route("/inventory/import/commit", methods=["POST"])
def import_commit():
    raw_rows_json = request.form.get("rows_json")
    if not raw_rows_json:
        return {"error": "Malformed import request."}, 400

    try:
        submitted_rows = json.loads(raw_rows_json)
    except (TypeError, ValueError):
        return {"error": "Malformed import request."}, 400

    # Never trust client-side validation for a write path - re-validate
    # every row from scratch server-side before touching the database.
    rows = [validate_row(r) for r in submitted_rows]
    bad_rows = [r for r in rows if r["errors"]]
    if bad_rows:
        return {"error": "Some rows still have invalid values.", "rows": rows}, 400

    # Validate every attached image's extension upfront, before touching
    # the database at all - same "validate everything, then commit" shape
    # as the row validation above, rather than failing partway through.
    image_files = {}
    for idx in range(len(rows)):
        f = request.files.get(f"image_{idx}")
        if f and f.filename:
            if not is_valid_image_filename(f.filename):
                return {"error": f"Row {idx + 1}: only PNG/JPG images are allowed."}, 400
            image_files[idx] = f

    db = SessionLocal()
    added = 0
    updated = 0
    unchanged = 0

    try:
        for idx, row in enumerate(rows):
            image_file = image_files.get(idx)
            has_new_image = image_file is not None

            existing = (
                db.query(Inventory)
                .filter(
                    Inventory.is_active == True,
                    func.lower(Inventory.name) == row["name"].lower(),
                )
                .first()
            )

            if existing is None:
                image_path = upload_inventory_image(image_file) if has_new_image else None

                item = Inventory(
                    name=row["name"],
                    category=row["category"],
                    quantity=row["quantity"],
                    price=row["price"],
                    image_blob_path=image_path,
                    is_active=True,
                )
                db.add(item)
                db.flush()  # populates item.id before commit, needed for the audit entry below

                db.add(InventoryAudit(
                    item_id=str(item.id),
                    action="BULK_UPLOAD",
                    field_name=None,
                    old_value=None,
                    new_value=item.name,
                    changed_by=get_user(),
                    source="EXCEL",
                ))
                added += 1
                continue

            changes = []
            if existing.category != row["category"]:
                changes.append(("category", existing.category, row["category"]))
            if existing.quantity != row["quantity"]:
                changes.append(("quantity", existing.quantity, row["quantity"]))
            if float(existing.price) != float(row["price"]):
                changes.append(("price", existing.price, row["price"]))
            if has_new_image:
                changes.append(("image", "previous image", "new image"))

            if not changes:
                unchanged += 1
                continue

            # Only touch the row's attributes once we know something is
            # actually changing - reassigning identical values would still
            # mark the row dirty and bump updated_at for a no-op row.
            old_quantity = existing.quantity
            existing.category = row["category"]
            existing.quantity = row["quantity"]
            existing.price = row["price"]

            if has_new_image:
                image_path = upload_inventory_image(image_file)
                existing.image_blob_path = image_path

            for field_name, old_value, new_value in changes:
                db.add(InventoryAudit(
                    item_id=str(existing.id),
                    action="UPDATE",
                    field_name=field_name,
                    old_value=str(old_value),
                    new_value=str(new_value),
                    changed_by=get_user(),
                    source="EXCEL",
                ))
            updated += 1

            # Same low-stock check as the single-item edit path
            crossed_threshold = (
                existing.low_stock_threshold is not None
                and old_quantity is not None
                and old_quantity >= existing.low_stock_threshold
                and existing.quantity < existing.low_stock_threshold
            )
            if crossed_threshold:
                try:
                    send_low_stock_email(existing)
                except Exception as e:
                    print(f"Low stock email failed: {e}")

        db.commit()

    except Exception as e:
        db.rollback()
        return {"error": f"Import failed: {str(e)}"}, 500

    finally:
        db.close()

    flash(f"Import complete: {added} added, {updated} updated, {unchanged} unchanged.", "success")
    return {"added": added, "updated": updated, "unchanged": unchanged}



@app.route("/inventory/delete/<int:item_id>", methods=["POST"])
def delete_inventory(item_id):
    db = SessionLocal()

    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()

        if not item:
            return "Item not found", 404

        # Soft delete
        item.is_active = False

        audit = InventoryAudit(
            item_id=str(item.id),
            action="DELETE",
            field_name="is_active",
            old_value="True",
            new_value="False",
            changed_by=get_user(),
            source="UI"
        )
        db.add(audit)
        
        db.commit()

        flash(f'"{item.name}" was deleted.', "success")
        return redirect(url_for("inventory"))

    except Exception as e:
        db.rollback()
        return f"Delete failed: {str(e)}", 500

    finally:
        db.close()

@app.route("/reports")
def reports():
    db = SessionLocal()
    logs = db.query(InventoryAudit).order_by(InventoryAudit.changed_at.desc()).all()

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
    return render_template("reports.html", logs=logs, title="Reports")

#for debug purposes. Wont exist for deployment
@app.route("/debug-db")
def debug_db():
    db = SessionLocal()
    items = db.query(Inventory).all()

    output = []
    for item in items:
        output.append({
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "quantity": item.quantity,
            "low_stock_threshold": item.low_stock_threshold,
            "price": item.price,
            "image": item.image_blob_path,
            "is_active": item.is_active
        })

    db.close()
    return {"items": output}

@app.route("/settings")
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


@app.route("/settings/database")
@require_database_settings_access
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


@app.route("/settings/database/update/<int:item_id>", methods=["POST"])
@require_database_settings_access
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
        return redirect(url_for("database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to update threshold: {str(e)}", 500
    finally:
        db.close()


@app.route("/settings/database/purge/<int:item_id>", methods=["POST"])
@require_database_settings_access
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
        return redirect(url_for("database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to remove item: {str(e)}", 500
    finally:
        db.close()


@app.route("/settings/database/purge-all-inactive", methods=["POST"])
@require_database_settings_access
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
        return redirect(url_for("database_settings"))
    except Exception as e:
        db.rollback()
        return f"Failed to remove inactive items: {str(e)}", 500
    finally:
        db.close()


@app.route("/settings/account")
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
    db.close()

    return render_template("account_settings.html", current_user=current_user, my_logs=my_logs, title="Account Settings")



#@app.route('/')
#def index():
#   print('Request for index page received')
#   return render_template('index.html')
#
#
#@app.route('/diaspora_logo.png')
#def favicon():
#    return send_from_directory(
#        os.path.join(app.root_path, 'static'),
#        'diaspora_logo.png',
#        mimetype='image/png'
#    )

#@app.route('/hello', methods=['POST'])
#def hello():
#   name = request.form.get('name')
#
#   if name:
#       print('Request for hello page received with name=%s' % name)
#       return render_template('hello.html', name = name)
#   else:
#       print('Request for hello page received with no name or blank name -- redirecting')
#       return redirect(url_for('index'))


#if __name__ == '__main__':
#   app.run()


if __name__ == "__main__":
    # Only turns on the interactive debugger if FLASK_DEBUG=true is set
    # locally. gunicorn (the real entry point in Azure) never hits this
    # block at all, but this keeps the file itself safe if it's ever run
    # directly (e.g. `python app.py` on a dev machine or test VM).
    #
    # This MUST stay at the true bottom of the file, after every route
    # definition. app.run() blocks until the server stops, so any route
    # defined after this point would never get registered when the file
    # is run directly with `python app.py` (though gunicorn - the real
    # production entry point - imports the module without ever reaching
    # this block, so that path is unaffected either way).
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)