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
from models import FileSubmission
from services.audit_helpers import format_eastern
from services.file_handler import delete_submission_file, generate_file_url, is_allowed_submission_filename, upload_submission_file
from auth import get_user
from permissions import can_delete_files

bp = Blueprint("files", __name__)


@bp.route("/files")
def files():
    db = SessionLocal()
    submissions = db.query(FileSubmission).order_by(FileSubmission.uploaded_at.desc()).all()

    for submission in submissions:
        submission.uploaded_at_display = format_eastern(submission.uploaded_at, fmt="%Y-%m-%d %I:%M %p %Z")
        submission.file_url = generate_file_url(submission.blob_path)

    categories = sorted({s.category for s in submissions if s.category})

    db.close()
    return render_template(
        "files.html",
        submissions=submissions,
        categories=categories,
        can_delete=can_delete_files(),
        title="Files",
    )


@bp.route("/files/upload", methods=["POST"])
def upload_file_submission():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip() or None
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
