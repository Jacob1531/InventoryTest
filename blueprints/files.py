"""
files.py
=====================================================================
File submissions - upload, list, and delete.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"files.<function_name>" for url_for().
=====================================================================
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from db import SessionLocal
from models import FileSubmission, Inventory, OrderBatch
from services.audit_helpers import format_eastern
from services.file_handler import delete_submission_file, generate_file_url, is_allowed_submission_filename, upload_submission_file
from auth import get_user
from permissions import can_delete_files, is_basic_user
from services.documents import (DOC_TYPES, RELATED_INVENTORY_ITEM, RELATED_ORDER_BATCH,
                                doc_type_label, normalize_doc_type, normalize_related,
                                related_label)

bp = Blueprint("files", __name__)


@bp.route("/files")
def files():
    # Basic-permissions users only see their own uploads. Scoping the QUERY
    # (rather than hiding rows in the template) also means the download URL
    # for someone else's file is never generated or sent to them - the SAS
    # link only exists for files they can see.
    own_files_only = is_basic_user()
    current_user = get_user()

    db = SessionLocal()
    query = db.query(FileSubmission)
    if own_files_only:
        query = query.filter(FileSubmission.uploaded_by == current_user)
    submissions = query.order_by(FileSubmission.uploaded_at.desc()).all()

    # Resolve what each document is attached to, so the list can show
    # "Order PO-14" rather than a bare id the reader can't act on.
    batch_labels = {
        b.id: (b.reference or f"Order #{b.id}")
        for b in db.query(OrderBatch).all()
    }
    item_labels = {i.id: i.name for i in db.query(Inventory).all()}

    for submission in submissions:
        submission.uploaded_at_display = format_eastern(submission.uploaded_at, fmt="%Y-%m-%d %I:%M %p %Z")
        submission.file_url = generate_file_url(submission.blob_path)
        submission.doc_type_display = doc_type_label(submission.doc_type)
        submission.related_kind = related_label(submission.related_type)
        if submission.related_type == RELATED_ORDER_BATCH:
            submission.related_name = batch_labels.get(submission.related_id)
        elif submission.related_type == RELATED_INVENTORY_ITEM:
            submission.related_name = item_labels.get(submission.related_id)
        else:
            submission.related_name = None

    categories = sorted({s.category for s in submissions if s.category})
    doc_types_present = sorted({s.doc_type for s in submissions if s.doc_type})

    db.close()
    return render_template(
        "files.html",
        submissions=submissions,
        categories=categories,
        doc_types=DOC_TYPES,
        doc_types_present=doc_types_present,
        can_delete=can_delete_files(),
        own_files_only=own_files_only,
        title="Files",
    )


@bp.route("/files/upload", methods=["POST"])
def upload_file_submission():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip() or None
    doc_type = normalize_doc_type(request.form.get("doc_type"))
    related_type, related_id = normalize_related(
        request.form.get("related_type"), request.form.get("related_id")
    )
    file = request.files.get("file")

    if not name:
        return "Name is required.", 400
    if not file or not file.filename:
        return "A file is required.", 400
    if not is_allowed_submission_filename(file.filename):
        return "That file type isn't allowed.", 400

    db = SessionLocal()
    try:
        blob_path = upload_submission_file(file)

        submission = FileSubmission(
            name=name,
            original_filename=file.filename,
            blob_path=blob_path,
            category=category,
            doc_type=doc_type,
            related_type=related_type,
            related_id=related_id,
            uploaded_by=get_user(),
        )
        db.add(submission)
        db.commit()

        flash(f'"{name}" was uploaded.', "success")
        return redirect(url_for("files.files"))

    except Exception as e:
        db.rollback()
        return f"Upload failed: {str(e)}", 500
    finally:
        db.close()


@bp.route("/files/<int:submission_id>/delete", methods=["POST"])
def delete_file_submission(submission_id):
    if not can_delete_files():
        return "You don't have permission to delete files.", 403

    db = SessionLocal()
    try:
        submission = db.query(FileSubmission).filter(FileSubmission.id == submission_id).first()
        if not submission:
            return "File not found", 404

        name = submission.name
        delete_submission_file(submission.blob_path)
        db.delete(submission)
        db.commit()

        flash(f'"{name}" was deleted.', "success")
        return redirect(url_for("files.files"))

    except Exception as e:
        db.rollback()
        return f"Failed to delete file: {str(e)}", 500
    finally:
        db.close()
