"""
receiving.py
=====================================================================
Pure, DB-independent logic for receiving deliveries against order
lines.

Previously "receive" was all-or-nothing: one click added the full
ordered quantity. Real deliveries arrive short, arrive damaged, or
arrive in two shipments, so a line now tracks how much has ACTUALLY
been received and stays open until it's complete.

Kept separate from the routes so the arithmetic and the state
transitions can be unit tested without a database.
=====================================================================
"""

STATUS_PENDING = "PENDING"
STATUS_PARTIAL = "PARTIAL"
STATUS_RECEIVED = "RECEIVED"
STATUS_CANCELLED = "CANCELLED"

# Lines still expecting stock. Used both for "what's on order" and for
# deciding which lines a receiving form should show.
OPEN_STATUSES = (STATUS_PENDING, STATUS_PARTIAL)

BATCH_OPEN = "OPEN"
BATCH_RECEIVED = "RECEIVED"
BATCH_CANCELLED = "CANCELLED"


def outstanding(line):
    """How much of a line is still owed. Never negative - an over-delivery
    (more arrived than was ordered) counts as fully satisfied rather than
    producing a negative amount that would corrupt on-order totals."""
    if line.status == STATUS_CANCELLED:
        return 0
    ordered = line.quantity or 0
    received = line.quantity_received or 0
    return max(0, ordered - received)


def line_status_after(ordered, received):
    """The status a line should hold given its ordered/received amounts."""
    ordered = ordered or 0
    received = received or 0
    if received <= 0:
        return STATUS_PENDING
    if received >= ordered:
        return STATUS_RECEIVED
    return STATUS_PARTIAL


def apply_receipt(line, receiving_now):
    """Works out the result of receiving `receiving_now` more units against
    a line. Returns (new_total_received, new_status, added_to_stock).

    `added_to_stock` is what inventory should increase by - which is
    exactly what arrived, including any overage, since the physical goods
    are on the shelf regardless of what was ordered.

    Raises ValueError for a negative amount or a line that can't receive.
    """
    if receiving_now is None:
        raise ValueError("Received quantity is required.")
    if receiving_now < 0:
        raise ValueError("Received quantity can't be negative.")
    if line.status == STATUS_CANCELLED:
        raise ValueError("This line was cancelled and can't receive stock.")
    if line.status == STATUS_RECEIVED:
        raise ValueError("This line has already been fully received.")

    new_total = (line.quantity_received or 0) + receiving_now
    return new_total, line_status_after(line.quantity, new_total), receiving_now


def batch_status_from_lines(lines):
    """A batch's status derived from its lines: cancelled only if every
    line is, received once no line is still open, otherwise open. An empty
    batch counts as open - it has nothing to have completed."""
    statuses = [line.status for line in lines]
    if not statuses:
        return BATCH_OPEN
    if all(s == STATUS_CANCELLED for s in statuses):
        return BATCH_CANCELLED
    if any(s in OPEN_STATUSES for s in statuses):
        return BATCH_OPEN
    return BATCH_RECEIVED


def summarize_batch(lines):
    """Totals for a batch header: line count, units ordered, units received
    and units still outstanding."""
    active = [l for l in lines if l.status != STATUS_CANCELLED]
    return {
        "lines": len(lines),
        "open_lines": sum(1 for l in lines if l.status in OPEN_STATUSES),
        "ordered": sum(l.quantity or 0 for l in active),
        "received": sum(l.quantity_received or 0 for l in active),
        "outstanding": sum(outstanding(l) for l in active),
    }
