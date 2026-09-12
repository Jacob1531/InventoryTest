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


class OrderBatch(Base):
    """One order form - the paper document, which covers many items at once.

    Added because the real workflow places and receives a whole form of
    items together, while InventoryOrder is one row per item. A batch is
    the header; its InventoryOrder rows are the line items.

    Existing single-item orders predate this and keep batch_id = NULL;
    they continue to work exactly as before, so nothing needed
    backfilling."""
    __tablename__ = "order_batch"

    id = Column(Integer, primary_key=True)
    reference = Column(String, nullable=True, index=True)   # e.g. a PO number
    supplier = Column(String, nullable=True)
    status = Column(String, default="OPEN", index=True)     # OPEN, RECEIVED, CANCELLED
    ordered_by = Column(String)
    ordered_at = Column(DateTime, server_default=func.now(), index=True)
    expected_date = Column(Date, nullable=True)
    notes = Column(String, nullable=True)
    closed_at = Column(DateTime, nullable=True)


class InventoryOrder(Base):
    """A single line on an order - one item and its quantity. Belongs to an
    OrderBatch when placed via an order form; standalone (batch_id NULL)
    when placed one-off from an item card."""
    __tablename__ = "inventory_order"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, nullable=True, index=True)   # references OrderBatch.id
    item_id = Column(Integer)            # references Inventory.id (no enforced FK,
                                          # consistent with InventoryAudit.item_id)
    quantity = Column(Integer)           # quantity ordered
    # Cumulative quantity actually received. Split from `quantity` so a
    # delivery that arrives short is recorded truthfully rather than being
    # forced to either "all arrived" or "none arrived".
    quantity_received = Column(Integer, default=0)
    status = Column(String, default="PENDING", index=True)  # PENDING, PARTIAL, RECEIVED, CANCELLED
    ordered_by = Column(String)
    ordered_at = Column(DateTime, server_default=func.now(), index=True)
    expected_date = Column(Date, nullable=True)
    notes = Column(String, nullable=True)
    condition_note = Column(String, nullable=True)   # damage / discrepancy on arrival
    received_by = Column(String, nullable=True)
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
    # Operational document type, from a fixed list (see services/documents.py)
    # rather than the previous free text, so "Invoice" and "invoice" can't
    # drift into separate categories.
    doc_type = Column(String, nullable=True, index=True)
    # What this document pertains to. Together these link a packing slip to
    # the order batch it arrived against, or a spec sheet to an item, so
    # documents live with the operation instead of in a flat pile.
    related_type = Column(String, nullable=True)   # ORDER_BATCH | INVENTORY_ITEM | None
    related_id = Column(Integer, nullable=True)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_file_submission_related", "related_type", "related_id"),
    )

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
    site = Column(String, nullable=True, index=True)   # which building/site
    location = Column(String, nullable=True)           # room/area within that site
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


class DashboardPreference(Base):
    """Per-user dashboard chart settings. One row per user, keyed by the
    Entra identity that auth.get_user() returns. Deliberately per-user
    rather than global: the warehouse person and the office manager care
    about different things. Rows are created lazily - a user with no row
    simply gets the defaults, so nothing needs backfilling."""
    __tablename__ = "dashboard_preference"

    id = Column(Integer, primary_key=True)
    user_key = Column(String, unique=True, index=True)
    chart_mode = Column(String, default="CATEGORY")     # CATEGORY, LOW_STOCK, ON_ORDER, RECENT
    chart_category = Column(String, nullable=True)      # None = all categories
    chart_limit = Column(Integer, default=10)
    updated_at = Column(DateTime, onupdate=func.now(), server_default=func.now())
