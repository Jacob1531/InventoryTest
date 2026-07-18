from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime
from sqlalchemy.sql import func
from db import Base


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
    action = Column(String)              # ADD, UPDATE, DELETE, BULK_UPLOAD
    field_name = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    changed_by = Column(String)
    source = Column(String)              # UI / EXCEL
    changed_at = Column(DateTime, server_default=func.now())