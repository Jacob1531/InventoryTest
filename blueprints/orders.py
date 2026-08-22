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
from models import Inventory, InventoryAudit, InventoryOrder, MAX_NUMERIC_VALUE
from services.audit_helpers import format_eastern
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

    item_names = {item.id: item.name for item in db.query(Inventory).all()}
    for order in orders:
        order.item_name = item_names.get(order.item_id, f"Item #{order.item_id} (deleted)")
        order.ordered_at_display = format_eastern(order.ordered_at, fmt="%Y-%m-%d %I:%M %p %Z")
        order.received_at_display = format_eastern(order.received_at, fmt="%Y-%m-%d %I:%M %p %Z") if order.received_at else None
        order.expected_date_display = order.expected_date.strftime("%Y-%m-%d") if order.expected_date else None

    db.close()
    return render_template("orders.html", orders=orders, title="Orders")


@bp.route("/inventory/order/<int:order_id>/receive", methods=["POST"])
def receive_order(order_id):
    db = SessionLocal()
    try:
        order = db.query(InventoryOrder).filter(InventoryOrder.id == order_id).first()
        if not order:
            return "Order not found", 404
        if order.status != "PENDING":
            return "Only pending orders can be marked received.", 400

        item = db.query(Inventory).filter(Inventory.id == order.item_id).first()
        if not item:
            return "The item for this order no longer exists.", 400

        old_quantity = item.quantity
        item.quantity = (item.quantity or 0) + order.quantity

        order.status = "RECEIVED"
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
        flash(f'Received {order.quantity} x "{item.name}". Quantity updated.', "success")
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
        if order.status != "PENDING":
            return "Only pending orders can be cancelled.", 400

        order.status = "CANCELLED"
        db.commit()

        flash("Order cancelled.", "success")
        return redirect(url_for("orders.inventory_orders"))

    except Exception as e:
        db.rollback()
        return f"Failed to cancel order: {str(e)}", 500
    finally:
        db.close()
