from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Date
from sqlalchemy.sql import func
from db import Base

# Hard ceiling on quantity/price magnitude, shared by every entry point
# that writes these fields (single-item add/edit, and bulk Excel import).
MAX_NUMERIC_VALUE = 999999999


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    item_id = Column(String, unique=True, index=True)
    name = Column(String)
    category = Column(String)
    quantity = Column(Integer)
    price = Column(Numeric)
    image_blob_path = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    low_stock_threshold = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class InventoryAudit(Base):
    __tablename__ = "inventory_audit"

    audit_id = Column(Integer, primary_key=True)
    item_id = Column(String)
    action = Column(String)              # ADD, UPDATE, DELETE, BULK_UPLOAD, PURGE, ORDER_RECEIVED
    field_name = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    changed_by = Column(String)
    source = Column(String)              # UI / EXCEL
    changed_at = Column(DateTime, server_default=func.now())


class InventoryOrder(Base):
    __tablename__ = "inventory_order"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer)            # references Inventory.id (no enforced FK,
                                          # consistent with InventoryAudit.item_id)
    quantity = Column(Integer)
    status = Column(String, default="PENDING")  # PENDING, RECEIVED, CANCELLED
    ordered_by = Column(String)
    ordered_at = Column(DateTime, server_default=func.now())
    expected_date = Column(Date, nullable=True)
    notes = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=True)