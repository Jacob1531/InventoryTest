"""
imports.py
=====================================================================
The three-step Excel import flow (preview -> review -> commit).

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"imports.<function_name>" for url_for().
=====================================================================
"""
from services.notifications import send_low_stock_email
import json
from flask import Blueprint, flash, request
from sqlalchemy import func
from db import SessionLocal
from models import Inventory, InventoryAudit
from services.image_handler import display_filename, is_valid_image_filename, upload_inventory_image
from services.excel_import import ImportFileError, parse_import_file, validate_row
from auth import get_user

bp = Blueprint("imports", __name__)


@bp.route("/inventory/import/preview", methods=["POST"])
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


@bp.route("/inventory/import/lookup-existing", methods=["POST"])
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


@bp.route("/inventory/import/commit", methods=["POST"])
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
