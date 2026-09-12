"""
orders.py
=====================================================================
Placing, viewing, receiving, and cancelling stock orders.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"orders.<function_name>" for url_for().
=====================================================================
"""
from datetime import datetime
from datetime import timezone
from flask import Blueprint, flash, redirect, render_template, request, url_for
from db import SessionLocal
from models import (FileSubmission, Inventory, InventoryAudit, InventoryOrder,
                    MAX_NUMERIC_VALUE, OrderBatch)
from services.audit_helpers import format_eastern
from services.documents import RELATED_ORDER_BATCH, doc_type_label, normalize_doc_type
from services.file_handler import (is_allowed_submission_filename, generate_file_url,
                                   upload_submission_file)
from services.receiving import (OPEN_STATUSES, apply_receipt, batch_status_from_lines,
                                outstanding, summarize_batch)
from auth import get_user
from permissions import can_place_orders

bp = Blueprint("orders", __name__)


@bp.route("/inventory/order/<int:item_id>", methods=["POST"])
def place_order(item_id):
    if not can_place_orders():
        return "You don't have permission to place orders.", 403

    db = SessionLocal()
    try:
        item = db.query(Inventory).filter(Inventory.id == item_id, Inventory.is_active == True).first()
        if not item:
            return "Item not found", 404

        try:
            quantity = int(request.form.get("quantity"))
        except (TypeError, ValueError):
            return "Quantity must be a whole number.", 400

        if quantity <= 0:
            return "Order quantity must be greater than zero.", 400
        if quantity > MAX_NUMERIC_VALUE:
            return f"Order quantity can't exceed {MAX_NUMERIC_VALUE}.", 400

        expected_date_str = request.form.get("expected_date")
        expected_date = None
        if expected_date_str:
            try:
                expected_date = datetime.strptime(expected_date_str, "%Y-%m-%d").date()
            except ValueError:
                return "Expected date must be a valid date.", 400

        notes = request.form.get("notes") or None

        order = InventoryOrder(
            item_id=item.id,
            quantity=quantity,
            status="PENDING",
            ordered_by=get_user(),
            expected_date=expected_date,
            notes=notes,
        )
        db.add(order)
        db.commit()

        flash(f'Order placed: {quantity} x "{item.name}".', "success")
        return redirect(request.referrer or url_for("inventory.inventory"))

    except Exception as e:
        db.rollback()
        return f"Failed to place order: {str(e)}", 500
    finally:
        db.close()


@bp.route("/inventory/orders")
def inventory_orders():
    db = SessionLocal()
    orders = db.query(InventoryOrder).order_by(InventoryOrder.ordered_at.desc()).all()
    batches = db.query(OrderBatch).order_by(OrderBatch.ordered_at.desc()).all()

    item_names = {item.id: item.name for item in db.query(Inventory).all()}
    lines_by_batch = {}
    for order in orders:
        order.item_name = item_names.get(order.item_id, f"Item #{order.item_id} (deleted)")
        order.ordered_at_display = format_eastern(order.ordered_at, fmt="%Y-%m-%d %I:%M %p %Z")
        order.received_at_display = format_eastern(order.received_at, fmt="%Y-%m-%d %I:%M %p %Z") if order.received_at else None
        order.expected_date_display = order.expected_date.strftime("%Y-%m-%d") if order.expected_date else None
        order.outstanding = outstanding(order)
        if order.batch_id:
            lines_by_batch.setdefault(order.batch_id, []).append(order)

    for batch in batches:
        batch_lines = lines_by_batch.get(batch.id, [])
        batch.summary = summarize_batch(batch_lines)
        batch.lines = batch_lines
        batch.ordered_at_display = format_eastern(batch.ordered_at, fmt="%Y-%m-%d %I:%M %p %Z")
        batch.expected_date_display = batch.expected_date.strftime("%Y-%m-%d") if batch.expected_date else None

    # Standalone lines - placed one-off from an item card rather than on a form.
    standalone = [o for o in orders if not o.batch_id]

    db.close()
    return render_template(
        "orders.html",
        batches=batches,
        standalone=standalone,
        can_order=can_place_orders(),
        title="Orders",
    )


@bp.route("/inventory/orders/new")
def new_order_form():
    """The order form - one form covering many items, mirroring the paper
    process rather than forcing an order per item."""
    if not can_place_orders():
        return "You don't have permission to place orders.", 403

    db = SessionLocal()
    items = (
        db.query(Inventory)
        .filter(Inventory.is_active == True)
        .order_by(Inventory.name.asc())
        .all()
    )
    # Suggested quantity: enough to reach the low-stock threshold again.
    for item in items:
        if item.low_stock_threshold and (item.quantity or 0) < item.low_stock_threshold:
            item.suggested = item.low_stock_threshold - (item.quantity or 0)
        else:
            item.suggested = 0
    db.close()
    return render_template("order_form.html", items=items, title="New Order Form")


@bp.route("/inventory/orders/new", methods=["POST"])
def create_order_batch():
    if not can_place_orders():
        return "You don't have permission to place orders.", 403

    reference = (request.form.get("reference") or "").strip() or None
    supplier = (request.form.get("supplier") or "").strip() or None
    notes = (request.form.get("notes") or "").strip() or None

    expected_date = None
    raw_date = (request.form.get("expected_date") or "").strip()
    if raw_date:
        try:
            expected_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError:
            return "Expected date must be a valid date.", 400

    # Collect the lines the person actually filled in. Rows left blank or
    # set to zero are simply not ordered, rather than being an error - the
    # form lists every item, and most will be untouched.
    lines = []
    for key, raw in request.form.items():
        if not key.startswith("qty_"):
            continue
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            qty = int(raw)
        except ValueError:
            return f"Quantity for item {key[4:]} must be a whole number.", 400
        if qty <= 0:
            continue
        if qty > MAX_NUMERIC_VALUE:
            return f"Quantity can't exceed {MAX_NUMERIC_VALUE}.", 400
        try:
            item_id = int(key[4:])
        except ValueError:
            continue
        lines.append((item_id, qty))

    if not lines:
        return "Add a quantity for at least one item.", 400

    db = SessionLocal()
    try:
        valid_ids = {
            i.id for i in db.query(Inventory).filter(
                Inventory.id.in_([i for i, _ in lines]),
                Inventory.is_active == True,
            ).all()
        }
        lines = [(i, q) for i, q in lines if i in valid_ids]
        if not lines:
            return "None of those items are available to order.", 400

        batch = OrderBatch(
            reference=reference,
            supplier=supplier,
            status="OPEN",
            ordered_by=get_user(),
            expected_date=expected_date,
            notes=notes,
        )
        db.add(batch)
        db.flush()  # need batch.id before the lines can reference it

        for item_id, qty in lines:
            db.add(InventoryOrder(
                batch_id=batch.id,
                item_id=item_id,
                quantity=qty,
                quantity_received=0,
                status="PENDING",
                ordered_by=get_user(),
                expected_date=expected_date,
            ))

        db.commit()
        flash(f"Order placed: {len(lines)} item{'s' if len(lines) != 1 else ''}.", "success")
        return redirect(url_for("orders.order_batch_detail", batch_id=batch.id))
    except Exception as e:
        db.rollback()
        return f"Failed to place order: {str(e)}", 500
    finally:
        db.close()


@bp.route("/inventory/orders/batch/<int:batch_id>")
def order_batch_detail(batch_id):
    db = SessionLocal()
    batch = db.query(OrderBatch).filter(OrderBatch.id == batch_id).first()
    if not batch:
        db.close()
        return "Order not found", 404

    lines = (
        db.query(InventoryOrder)
        .filter(InventoryOrder.batch_id == batch_id)
        .order_by(InventoryOrder.id.asc())
        .all()
    )
    item_names = {i.id: i.name for i in db.query(Inventory).all()}
    for line in lines:
        line.item_name = item_names.get(line.item_id, f"Item #{line.item_id} (deleted)")
        line.outstanding = outstanding(line)

    documents = (
        db.query(FileSubmission)
        .filter(
            FileSubmission.related_type == RELATED_ORDER_BATCH,
            FileSubmission.related_id == batch_id,
        )
        .order_by(FileSubmission.uploaded_at.desc())
        .all()
    )
    for doc in documents:
        doc.uploaded_at_display = format_eastern(doc.uploaded_at, fmt="%Y-%m-%d %I:%M %p %Z")
        doc.file_url = generate_file_url(doc.blob_path)
        doc.doc_type_label = doc_type_label(doc.doc_type)

    batch.summary = summarize_batch(lines)
    batch.ordered_at_display = format_eastern(batch.ordered_at, fmt="%Y-%m-%d %I:%M %p %Z")
    batch.expected_date_display = batch.expected_date.strftime("%Y-%m-%d") if batch.expected_date else None
    has_open_lines = any(l.status in OPEN_STATUSES for l in lines)

    db.close()
    return render_template(
        "order_batch.html",
        batch=batch,
        lines=lines,
        documents=documents,
        has_open_lines=has_open_lines,
        can_order=can_place_orders(),
        title=batch.reference or f"Order #{batch.id}",
    )


@bp.route("/inventory/orders/batch/<int:batch_id>/receive", methods=["POST"])
def receive_batch(batch_id):
    """The delivery arrival form: records what actually turned up, line by
    line, with an optional packing slip attached. Quantities may be short,
    over, or zero - inventory moves by what physically arrived."""
    if not can_place_orders():
        return "You don't have permission to receive orders.", 403

    received_by = (request.form.get("received_by") or "").strip() or get_user()

    doc_file = request.files.get("document")
    has_doc = bool(doc_file and doc_file.filename)
    if has_doc and not is_allowed_submission_filename(doc_file.filename):
        return "That file type isn't allowed.", 400

    db = SessionLocal()
    try:
        batch = db.query(OrderBatch).filter(OrderBatch.id == batch_id).first()
        if not batch:
            return "Order not found", 404

        lines = db.query(InventoryOrder).filter(InventoryOrder.batch_id == batch_id).all()
        lines_by_id = {l.id: l for l in lines}

        # Parse and validate EVERY line before writing anything, so a bad
        # value on line 9 can't leave lines 1-8 already applied.
        planned = []
        for line in lines:
            raw = (request.form.get(f"recv_{line.id}") or "").strip()
            if not raw:
                continue
            try:
                qty = int(raw)
            except ValueError:
                return f"Received quantity for {line.id} must be a whole number.", 400
            if qty == 0:
                continue
            if qty > MAX_NUMERIC_VALUE:
                return f"Received quantity can't exceed {MAX_NUMERIC_VALUE}.", 400
            try:
                new_total, new_status, added = apply_receipt(line, qty)
            except ValueError as e:
                return str(e), 400
            planned.append((line, new_total, new_status, added))

        if not planned:
            return "Enter a received quantity for at least one line.", 400

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for line, new_total, new_status, added in planned:
            item = db.query(Inventory).filter(Inventory.id == line.item_id).first()
            if not item:
                return f"The item for line {line.id} no longer exists.", 400

            old_quantity = item.quantity
            item.quantity = (item.quantity or 0) + added

            line.quantity_received = new_total
            line.status = new_status
            line.received_by = received_by
            line.received_at = now
            condition = (request.form.get(f"cond_{line.id}") or "").strip()
            if condition:
                line.condition_note = condition

            db.add(InventoryAudit(
                item_id=str(item.id),
                action="ORDER_RECEIVED",
                field_name="quantity",
                old_value=str(old_quantity),
                new_value=str(item.quantity),
                changed_by=received_by,
                source="UI",
            ))

        # Refresh the batch header from its lines' new states.
        batch.status = batch_status_from_lines(lines)
        batch.closed_at = now if batch.status != "OPEN" else None

        if has_doc:
            blob_path = upload_submission_file(doc_file, prefix="files")
            db.add(FileSubmission(
                name=(request.form.get("document_name") or "").strip()
                     or f"Delivery {batch.reference or batch.id}",
                original_filename=doc_file.filename,
                blob_path=blob_path,
                doc_type=normalize_doc_type(request.form.get("document_type")),
                related_type=RELATED_ORDER_BATCH,
                related_id=batch.id,
                uploaded_by=get_user(),
            ))

        db.commit()
        flash(f"Delivery recorded for {len(planned)} line{'s' if len(planned) != 1 else ''}.", "success")
        return redirect(url_for("orders.order_batch_detail", batch_id=batch_id))
    except Exception as e:
        db.rollback()
        return f"Failed to record delivery: {str(e)}", 500
    finally:
        db.close()


@bp.route("/inventory/order/<int:order_id>/receive", methods=["POST"])
def receive_order(order_id):
    db = SessionLocal()
    try:
        order = db.query(InventoryOrder).filter(InventoryOrder.id == order_id).first()
        if not order:
            return "Order not found", 404
        if order.status not in OPEN_STATUSES:
            return "Only open orders can be received.", 400

        item = db.query(Inventory).filter(Inventory.id == order.item_id).first()
        if not item:
            return "The item for this order no longer exists.", 400

        # "Receive all" on a single-item order means whatever is still
        # outstanding - which is the full quantity for an untouched line,
        # but only the remainder if part of it already arrived.
        remaining = outstanding(order)
        try:
            new_total, new_status, added = apply_receipt(order, remaining)
        except ValueError as e:
            return str(e), 400

        old_quantity = item.quantity
        item.quantity = (item.quantity or 0) + added

        order.quantity_received = new_total
        order.status = new_status
        order.received_by = get_user()
        order.received_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(InventoryAudit(
            item_id=str(item.id),
            action="ORDER_RECEIVED",
            field_name="quantity",
            old_value=str(old_quantity),
            new_value=str(item.quantity),
            changed_by=get_user(),
            source="UI",
        ))

        db.commit()
        flash(f'Received {added} x "{item.name}". Quantity updated.', "success")
        return redirect(url_for("orders.inventory_orders"))

    except Exception as e:
        db.rollback()
        return f"Failed to mark order received: {str(e)}", 500
    finally:
        db.close()


@bp.route("/inventory/order/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    db = SessionLocal()
    try:
        order = db.query(InventoryOrder).filter(InventoryOrder.id == order_id).first()
        if not order:
            return "Order not found", 404
        if order.status not in OPEN_STATUSES:
            return "Only open orders can be cancelled.", 400

        order.status = "CANCELLED"
        db.commit()

        flash("Order cancelled.", "success")
        return redirect(url_for("orders.inventory_orders"))

    except Exception as e:
        db.rollback()
        return f"Failed to cancel order: {str(e)}", 500
    finally:
        db.close()
