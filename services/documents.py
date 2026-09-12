"""
documents.py
=====================================================================
Operational document types and the records a document can be attached
to.

Files started as generic storage with a free-text category, which
meant "Invoice", "invoice" and "Invoices" drifted into three separate
groupings. These are a fixed list instead, chosen around what the
operation actually produces and receives rather than around file
formats.

A document can also point at the record it documents, so a packing
slip lives with the order batch it arrived against instead of in a
flat pile.
=====================================================================
"""

# Ordered roughly by how often they come up day to day.
DOC_TYPES = [
    ("ORDER_FORM", "Order form"),
    ("PACKING_SLIP", "Packing slip"),
    ("DELIVERY_NOTE", "Delivery note"),
    ("INVOICE", "Invoice"),
    ("RECEIPT", "Receipt"),
    ("DAMAGE_REPORT", "Damage report"),
    ("OTHER", "Other"),
]

DOC_TYPE_VALUES = {value for value, _ in DOC_TYPES}
DOC_TYPE_LABELS = dict(DOC_TYPES)

DEFAULT_DOC_TYPE = "OTHER"

# What a document can be attached to.
RELATED_ORDER_BATCH = "ORDER_BATCH"
RELATED_INVENTORY_ITEM = "INVENTORY_ITEM"
RELATED_TYPES = {RELATED_ORDER_BATCH, RELATED_INVENTORY_ITEM}

RELATED_LABELS = {
    RELATED_ORDER_BATCH: "Order",
    RELATED_INVENTORY_ITEM: "Item",
}


def normalize_doc_type(value):
    """Unknown or missing types fall back to OTHER rather than being
    stored as-is, so the filter list can never grow stray values."""
    return value if value in DOC_TYPE_VALUES else DEFAULT_DOC_TYPE


def doc_type_label(value):
    """Human label for a stored type. Falls back to the raw value so
    documents uploaded before this list existed still display something
    meaningful rather than a blank cell."""
    if not value:
        return None
    return DOC_TYPE_LABELS.get(value, value)


def normalize_related(related_type, related_id):
    """Validates a (type, id) pair. Returns (None, None) unless BOTH are
    present and valid - a dangling type with no id, or an id with no
    type, would produce a link that points nowhere."""
    if related_type not in RELATED_TYPES:
        return None, None
    try:
        related_id = int(related_id)
    except (TypeError, ValueError):
        return None, None
    if related_id <= 0:
        return None, None
    return related_type, related_id


def related_label(related_type):
    return RELATED_LABELS.get(related_type)
