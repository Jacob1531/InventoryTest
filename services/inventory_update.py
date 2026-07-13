from models import Inventory, InventoryAudit
from auth import get_user
from db import SessionLocal

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
    db.commit()
    db.close()