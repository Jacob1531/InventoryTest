from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, Date, Index
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
    is_active = Column(Boolean, default=True, index=True)
    low_stock_threshold = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        # Every Excel-import row match and the "already exists?" check use
        # a case-insensitive name lookup (func.lower(Inventory.name) == ...);
        # a plain index on name can't serve that, so this indexes the
        # lowercased expression directly.
        Index("ix_inventory_name_lower", func.lower(name)),
    )


class InventoryAudit(Base):
    __tablename__ = "inventory_audit"

    audit_id = Column(Integer, primary_key=True)
    item_id = Column(String, index=True)
    action = Column(String)              # ADD, UPDATE, DELETE, BULK_UPLOAD, PURGE, ORDER_RECEIVED
    field_name = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    changed_by = Column(String)
    source = Column(String)              # UI / EXCEL
    changed_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        # Serves "My Activity" (filter by user, sorted by time) and
        # "Added This Week" (filter by action, sorted by time) together,
        # rather than filtering first and sorting the result separately.
        Index("ix_inventory_audit_changed_by_changed_at", "changed_by", "changed_at"),
        Index("ix_inventory_audit_action_changed_at", "action", "changed_at"),
    )


class InventoryOrder(Base):
    __tablename__ = "inventory_order"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer)            # references Inventory.id (no enforced FK,
                                          # consistent with InventoryAudit.item_id)
    quantity = Column(Integer)
    status = Column(String, default="PENDING", index=True)  # PENDING, RECEIVED, CANCELLED
    ordered_by = Column(String)
    ordered_at = Column(DateTime, server_default=func.now(), index=True)
    expected_date = Column(Date, nullable=True)
    notes = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Serves both "sum pending orders per item" (inventory/low-stock
        # pages) and "cancel this item's pending orders" (on delete).
        Index("ix_inventory_order_item_status", "item_id", "status"),
    )


class FileSubmission(Base):
    __tablename__ = "file_submission"

    id = Column(Integer, primary_key=True)
    name = Column(String)                  # descriptive name the uploader typed
    original_filename = Column(String)     # the actual filename that was uploaded
    blob_path = Column(String)             # where it lives in Azure Blob Storage
    category = Column(String, nullable=True)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime, server_default=func.now(), index=True)

class HardwareItem(Base):
    """A single, individually-identified piece of equipment - one row per
    physical device. Deliberately separate from Inventory: Inventory
    tracks fungible quantities (42 interchangeable cans), whereas each
    hardware item is a distinct unit with its own serial number and
    warranty."""
    __tablename__ = "hardware_item"

    id = Column(Integer, primary_key=True)
    name = Column(String)                        # e.g. "Front desk workstation"
    hardware_type = Column(String, index=True)   # Computer, Printer, Monitor, Other
    manufacturer = Column(String, nullable=True)
    model = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)
    location = Column(String, nullable=True)
    assigned_to = Column(String, nullable=True)
    purchase_date = Column(Date, nullable=True)
    purchase_price = Column(Numeric, nullable=True)
    warranty_provider = Column(String, nullable=True)
    warranty_expires = Column(Date, nullable=True, index=True)
    status = Column(String, default="ACTIVE", index=True)  # ACTIVE, IN_REPAIR, RETIRED
    is_active = Column(Boolean, default=True, index=True)   # soft delete
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())


class HardwareDocument(Base):
    """Receipts, manuals, and warranty paperwork attached to a hardware
    item. Many per item."""
    __tablename__ = "hardware_document"

    id = Column(Integer, primary_key=True)
    hardware_id = Column(Integer, index=True)   # references HardwareItem.id
    name = Column(String)                       # descriptive name the uploader typed
    doc_type = Column(String, nullable=True)    # Receipt, Manual, Warranty, Other
    original_filename = Column(String)
    blob_path = Column(String)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime, server_default=func.now())


class HardwareNote(Base):
    """Timestamped notes appended to a hardware item over time - a running
    history ("replaced power supply 3/2026") rather than one overwritable
    free-text field."""
    __tablename__ = "hardware_note"

    id = Column(Integer, primary_key=True)
    hardware_id = Column(Integer, index=True)   # references HardwareItem.id
    note = Column(String)
    created_by = Column(String)
    created_at = Column(DateTime, server_default=func.now())
