from models import Inventory, InventoryAudit
from auth import get_user
from db import SessionLocal
from services.notifications import send_low_stock_email

def update_inventory_quantity(item_id, new_qty, source="UI"):
    db = SessionLocal()

    item = db.query(Inventory).filter(
        Inventory.id == item_id,
        Inventory.is_active == True
    ).first()

    if not item:
        db.close()
        raise ValueError("Item not found")

    old_qty = item.quantity
    item.quantity = new_qty

    audit = InventoryAudit(
        item_id=str(item.id),
        action="UPDATE",
        field_name="quantity",
        old_value=str(old_qty),
        new_value=str(new_qty),
        changed_by=get_user(),
        source=source
    )

    db.add(audit)

    crossed_threshold = (
        item.low_stock_threshold is not None
        and old_qty >= item.low_stock_threshold
        and new_qty < item.low_stock_threshold
    )

    db.commit()
    db.close()

    if crossed_threshold:
        try:
            send_low_stock_email(item)
        except Exception as e:
            print(f"Low stock email failed: {e}")