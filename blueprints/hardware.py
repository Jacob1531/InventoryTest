"""
hardware.py
=====================================================================
Hardware assets and their warranty information.

Each row is one individually-identified device (a specific printer,
not "3 printers"), with attached documents (receipts, manuals,
warranty paperwork) and a running history of timestamped notes.

The whole section is gated by @require_elevated_access - members of
the basic-permissions group can neither see the dashboard card nor
reach these URLs directly.
=====================================================================
"""
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import SessionLocal
from models import HardwareItem, HardwareDocument, HardwareNote, MAX_NUMERIC_VALUE
from services.audit_helpers import format_eastern
from services.file_handler import (upload_submission_file, generate_file_url,
                                   delete_submission_file, is_allowed_submission_filename)
from services.hardware_logic import (warranty_status, days_until_expiry,
                                     summarize_warranties, STATUS_LABELS)
from auth import get_user
from permissions import require_elevated_access

bp = Blueprint("hardware", __name__)

HARDWARE_TYPES = ["Computer", "Laptop", "Monitor", "Printer", "Networking", "Phone", "Other"]
HARDWARE_STATUSES = ["ACTIVE", "IN_REPAIR", "RETIRED"]
DOC_TYPES = ["Receipt", "Manual", "Warranty", "Other"]

# Blob path prefix - keeps hardware documents namespaced separately from
# general Files submissions within the same storage container.
BLOB_PREFIX = "hardware"


def _parse_date(value):
    """Returns (date_or_None, error_message_or_None) for an optional date field."""
    if not value:
        return None, None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date(), None
    except ValueError:
        return None, "Dates must be valid (YYYY-MM-DD)."


def _parse_price(value):
    """Returns (float_or_None, error_message_or_None) for the optional price field."""
    if not value:
        return None, None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None, "Purchase price must be a number."
    if price < 0:
        return None, "Purchase price can't be negative."
    if price > MAX_NUMERIC_VALUE:
        return None, f"Purchase price can't exceed {MAX_NUMERIC_VALUE}."
    return price, None


def _read_item_form(form):
    """Pulls and validates the shared add/edit field set.
    Returns (values_dict, error_message_or_None)."""
    name = form.get("name", "").strip()
    if not name:
        return None, "Name is required."

    hardware_type = form.get("hardware_type", "").strip()
    if not hardware_type:
        return None, "Type is required."

    status = form.get("status", "ACTIVE").strip()
    if status not in HARDWARE_STATUSES:
        return None, "Invalid status."

    purchase_date, err = _parse_date(form.get("purchase_date", "").strip())
    if err:
        return None, err

    warranty_expires, err = _parse_date(form.get("warranty_expires", "").strip())
    if err:
        return None, err

    purchase_price, err = _parse_price(form.get("purchase_price", "").strip())
    if err:
        return None, err

    return {
        "name": name,
        "hardware_type": hardware_type,
        "manufacturer": form.get("manufacturer", "").strip() or None,
        "model": form.get("model", "").strip() or None,
        "serial_number": form.get("serial_number", "").strip() or None,
        "site": form.get("site", "").strip() or None,
        "location": form.get("location", "").strip() or None,
        "assigned_to": form.get("assigned_to", "").strip() or None,
        "purchase_date": purchase_date,
        "purchase_price": purchase_price,
        "warranty_provider": form.get("warranty_provider", "").strip() or None,
        "warranty_expires": warranty_expires,
        "status": status,
    }, None


@bp.route("/hardware-warranty")
@require_elevated_access
def hardware_warranty():
    db = SessionLocal()
    items = (
        db.query(HardwareItem)
        .filter(HardwareItem.is_active == True)
        .order_by(HardwareItem.name.asc())
        .all()
    )

    for item in items:
        item.warranty_state = warranty_status(item.warranty_expires)
        item.warranty_label = STATUS_LABELS[item.warranty_state]
        item.days_left = days_until_expiry(item.warranty_expires)

    summary = summarize_warranties(items)
    types_in_use = sorted({i.hardware_type for i in items if i.hardware_type})
    sites_in_use = sorted({i.site for i in items if i.site})

    db.close()
    return render_template(
        "hardware_warranty.html",
        items=items,
        summary=summary,
        types_in_use=types_in_use,
        sites_in_use=sites_in_use,
        hardware_types=HARDWARE_TYPES,
        hardware_statuses=HARDWARE_STATUSES,
        title="Hardware & Warranty",
    )


@bp.route("/hardware-warranty/add", methods=["POST"])
@require_elevated_access
def add_hardware():
    values, error = _read_item_form(request.form)
    if error:
        return error, 400

    # An optional document can be attached at creation time. Validate it
    # BEFORE writing anything, so a bad file doesn't leave a half-created
    # item behind - more can always be added from the detail page later.
    doc_file = request.files.get("document")
    has_doc = bool(doc_file and doc_file.filename)
    if has_doc and not is_allowed_submission_filename(doc_file.filename):
        return "That file type isn't allowed.", 400

    doc_name = request.form.get("document_name", "").strip()
    doc_type = request.form.get("document_type", "").strip() or None

    db = SessionLocal()
    try:
        item = HardwareItem(is_active=True, **values)
        db.add(item)
        db.flush()  # populates item.id before the document row references it

        if has_doc:
            blob_path = upload_submission_file(doc_file, prefix=BLOB_PREFIX)
            db.add(HardwareDocument(
                hardware_id=item.id,
                # Fall back to the filename if no name was typed, so the
                # document is never listed with a blank label.
                name=doc_name or doc_file.filename,
                doc_type=doc_type,
                original_filename=doc_file.filename,
                blob_path=blob_path,
                uploaded_by=get_user(),
            ))

        db.commit()
        msg = f'"{values["name"]}" was added.'
        if has_doc:
            msg += " Document attached."
        flash(msg, "success")
        return redirect(url_for("hardware.hardware_warranty"))
    except Exception as e:
        db.rollback()
        return f"Failed to add hardware: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/<int:item_id>")
@require_elevated_access
def hardware_detail(item_id):
    db = SessionLocal()
    item = (
        db.query(HardwareItem)
        .filter(HardwareItem.id == item_id, HardwareItem.is_active == True)
        .first()
    )
    if not item:
        db.close()
        return "Hardware item not found", 404

    item.warranty_state = warranty_status(item.warranty_expires)
    item.warranty_label = STATUS_LABELS[item.warranty_state]
    item.days_left = days_until_expiry(item.warranty_expires)

    documents = (
        db.query(HardwareDocument)
        .filter(HardwareDocument.hardware_id == item_id)
        .order_by(HardwareDocument.uploaded_at.desc())
        .all()
    )
    for doc in documents:
        doc.uploaded_at_display = format_eastern(doc.uploaded_at, fmt="%Y-%m-%d %I:%M %p %Z")
        doc.file_url = generate_file_url(doc.blob_path)

    notes = (
        db.query(HardwareNote)
        .filter(HardwareNote.hardware_id == item_id)
        .order_by(HardwareNote.created_at.desc())
        .all()
    )
    for note in notes:
        note.created_at_display = format_eastern(note.created_at, fmt="%Y-%m-%d %I:%M %p %Z")

    db.close()
    return render_template(
        "hardware_detail.html",
        item=item,
        documents=documents,
        notes=notes,
        hardware_types=HARDWARE_TYPES,
        hardware_statuses=HARDWARE_STATUSES,
        doc_types=DOC_TYPES,
        title=item.name,
    )


@bp.route("/hardware-warranty/<int:item_id>/edit", methods=["POST"])
@require_elevated_access
def edit_hardware(item_id):
    values, error = _read_item_form(request.form)
    if error:
        return error, 400

    db = SessionLocal()
    try:
        item = db.query(HardwareItem).filter(HardwareItem.id == item_id).first()
        if not item:
            return "Hardware item not found", 404

        for field, value in values.items():
            setattr(item, field, value)

        db.commit()
        flash(f'"{values["name"]}" was updated.', "success")
        return redirect(url_for("hardware.hardware_detail", item_id=item_id))
    except Exception as e:
        db.rollback()
        return f"Failed to update hardware: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/<int:item_id>/delete", methods=["POST"])
@require_elevated_access
def delete_hardware(item_id):
    """Soft delete, matching Inventory's pattern - the row and its
    documents/notes are kept, just hidden from the list."""
    db = SessionLocal()
    try:
        item = db.query(HardwareItem).filter(HardwareItem.id == item_id).first()
        if not item:
            return "Hardware item not found", 404

        name = item.name
        item.is_active = False
        db.commit()

        flash(f'"{name}" was deleted.', "success")
        return redirect(url_for("hardware.hardware_warranty"))
    except Exception as e:
        db.rollback()
        return f"Failed to delete hardware: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/<int:item_id>/documents", methods=["POST"])
@require_elevated_access
def add_hardware_document(item_id):
    name = request.form.get("name", "").strip()
    doc_type = request.form.get("doc_type", "").strip() or None
    file = request.files.get("file")

    if not name:
        return "Document name is required.", 400
    if not file or not file.filename:
        return "A file is required.", 400
    if not is_allowed_submission_filename(file.filename):
        return "That file type isn't allowed.", 400

    db = SessionLocal()
    try:
        item = db.query(HardwareItem).filter(HardwareItem.id == item_id).first()
        if not item:
            return "Hardware item not found", 404

        blob_path = upload_submission_file(file, prefix=BLOB_PREFIX)

        db.add(HardwareDocument(
            hardware_id=item_id,
            name=name,
            doc_type=doc_type,
            original_filename=file.filename,
            blob_path=blob_path,
            uploaded_by=get_user(),
        ))
        db.commit()

        flash(f'"{name}" was attached.', "success")
        return redirect(url_for("hardware.hardware_detail", item_id=item_id))
    except Exception as e:
        db.rollback()
        return f"Failed to attach document: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/documents/<int:doc_id>/delete", methods=["POST"])
@require_elevated_access
def delete_hardware_document(doc_id):
    db = SessionLocal()
    try:
        doc = db.query(HardwareDocument).filter(HardwareDocument.id == doc_id).first()
        if not doc:
            return "Document not found", 404

        item_id = doc.hardware_id
        name = doc.name
        # Delete the blob first - if that genuinely fails, the DB row is
        # left alone rather than orphaning a file with no record of it.
        delete_submission_file(doc.blob_path)
        db.delete(doc)
        db.commit()

        flash(f'"{name}" was removed.', "success")
        return redirect(url_for("hardware.hardware_detail", item_id=item_id))
    except Exception as e:
        db.rollback()
        return f"Failed to remove document: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/<int:item_id>/notes", methods=["POST"])
@require_elevated_access
def add_hardware_note(item_id):
    note_text = request.form.get("note", "").strip()
    if not note_text:
        return "Note can't be empty.", 400

    db = SessionLocal()
    try:
        item = db.query(HardwareItem).filter(HardwareItem.id == item_id).first()
        if not item:
            return "Hardware item not found", 404

        db.add(HardwareNote(
            hardware_id=item_id,
            note=note_text,
            created_by=get_user(),
        ))
        db.commit()

        flash("Note added.", "success")
        return redirect(url_for("hardware.hardware_detail", item_id=item_id))
    except Exception as e:
        db.rollback()
        return f"Failed to add note: {str(e)}", 500
    finally:
        db.close()


@bp.route("/hardware-warranty/notes/<int:note_id>/delete", methods=["POST"])
@require_elevated_access
def delete_hardware_note(note_id):
    db = SessionLocal()
    try:
        note = db.query(HardwareNote).filter(HardwareNote.id == note_id).first()
        if not note:
            return "Note not found", 404

        item_id = note.hardware_id
        db.delete(note)
        db.commit()

        flash("Note deleted.", "success")
        return redirect(url_for("hardware.hardware_detail", item_id=item_id))
    except Exception as e:
        db.rollback()
        return f"Failed to delete note: {str(e)}", 500
    finally:
        db.close()
