"""
inventory.py
=====================================================================
Inventory list, add/edit/delete, quantity updates, and low-stock view.

Routes and URLs are unchanged from the pre-blueprint version; only
their location moved. Endpoint names are now namespaced as
"inventory.<function_name>" for url_for().
=====================================================================
"""
from services.inventory_update import update_inventory_quantity
from services.notifications import send_low_stock_email
from services.order_logic import compute_on_order_totals
from flask import Blueprint, flash, redirect, render_template, request, url_for
from db import SessionLocal
from models import Inventory, InventoryAudit, InventoryOrder, MAX_NUMERIC_VALUE
from services.image_handler import generate_image_url, is_valid_image_filename, upload_inventory_image
from auth import get_user
from permissions import can_place_orders

bp = Blueprint("inventory", __name__)


@bp.route("/inventory/low-stock")
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

    pending_orders = db.query(InventoryOrder).filter(InventoryOrder.status == "PENDING").all()
    on_order_totals = compute_on_order_totals(pending_orders)

    for item in items:
        item.is_out = item.quantity is not None and item.quantity <= 0
        item.on_order = on_order_totals.get(item.id, 0)

    db.close()
    return render_template(
        "low_stock.html",
        items=items,
        title="Low Stock Items",
        can_order=can_place_orders(),
    )


@bp.route("/inventory")
def inventory():
    db = SessionLocal()
    items = db.query(Inventory).filter(Inventory.is_active == True).all()

    # Sum pending order quantity per item, so cards can show "X on order".
    pending_orders = db.query(InventoryOrder).filter(InventoryOrder.status == "PENDING").all()
    on_order_totals = compute_on_order_totals(pending_orders)

    for item in items:
        if item.image_blob_path:
            item.image_url = generate_image_url(item.image_blob_path)
        else:
            item.image_url = None
        item.on_order = on_order_totals.get(item.id, 0)

    db.close()
    return render_template(
        "inventory.html",
        items=items,
        title="Inventory",
        can_order=can_place_orders(),
    )


@bp.route("/inventory/update", methods=["POST"])
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

    return redirect(url_for("inventory.inventory"))


@bp.route("/inventory/edit/<int:item_id>", methods=["POST"])
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
        return redirect(url_for("inventory.inventory"))

    except Exception as e:
        db.rollback()
        return f"Update failed: {str(e)}", 500

    finally:
        db.close()


@bp.route("/inventory/add", methods=["POST"])
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
        return redirect(url_for("inventory.inventory"))

    except Exception as e:
        db.rollback()
        return f"Server error: {str(e)}", 500

    finally:
        db.close()


@bp.route("/inventory/delete/<int:item_id>", methods=["POST"])
def delete_inventory(item_id):
    db = SessionLocal()

    try:
        item = db.query(Inventory).filter(Inventory.id == item_id).first()

        if not item:
            return "Item not found", 404

        # Soft delete
        item.is_active = False

        # A pending order for this item no longer makes sense once it's
        # deleted - without this, "receive" would still find the item row
        # (it's soft-deleted, not gone) and silently add stock to an item
        # nobody can see or use anymore.
        db.query(InventoryOrder).filter(
            InventoryOrder.item_id == item.id,
            InventoryOrder.status == "PENDING",
        ).update({"status": "CANCELLED"}, synchronize_session=False)

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
        return redirect(url_for("inventory.inventory"))

    except Exception as e:
        db.rollback()
        return f"Delete failed: {str(e)}", 500

    finally:
        db.close()
