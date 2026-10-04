"""
order_lifecycle.py
=====================================================================
The four milestones from the paper order form's "Section For Office
Use Only":

    Received order form -> Order placed -> Order received -> Order
    distributed

Each is a date on the form, so each is a date here too. The current
STAGE is derived from which of them are filled in rather than being
stored separately - one source of truth, and it can't drift out of
sync with the dates the way a duplicate status column would.

"Order received" is special: it isn't marked by hand, it's set
automatically once every line of the order has actually been
received, so it can never claim goods arrived that the line items say
didn't.

Pure and DB-independent so the ordering rules are unit testable.
=====================================================================
"""

STAGE_SUBMITTED = "SUBMITTED"
STAGE_FORM_RECEIVED = "FORM_RECEIVED"
STAGE_PLACED = "PLACED"
STAGE_RECEIVED = "RECEIVED"
STAGE_DISTRIBUTED = "DISTRIBUTED"
STAGE_CANCELLED = "CANCELLED"

# In order. Each entry is (stage, the field that marks it).
# SUBMITTED has no field - it's simply the state before anything is marked.
STAGE_SEQUENCE = [
    (STAGE_SUBMITTED, None),
    (STAGE_FORM_RECEIVED, "form_received_at"),
    (STAGE_PLACED, "order_placed_at"),
    (STAGE_RECEIVED, "order_received_at"),
    (STAGE_DISTRIBUTED, "order_distributed_at"),
]

STAGE_LABELS = {
    STAGE_SUBMITTED: "Submitted",
    STAGE_FORM_RECEIVED: "Order form received",
    STAGE_PLACED: "Order placed",
    STAGE_RECEIVED: "Order received",
    STAGE_DISTRIBUTED: "Order distributed",
    STAGE_CANCELLED: "Cancelled",
}

# Stages a person advances by hand. "Order received" is excluded
# deliberately - it follows from the line items, not from a button.
MANUAL_STAGES = [STAGE_FORM_RECEIVED, STAGE_PLACED, STAGE_DISTRIBUTED]

STAGE_FIELDS = {stage: field for stage, field in STAGE_SEQUENCE if field}


def current_stage(batch):
    """The furthest milestone reached. Works backwards through the
    sequence so that an out-of-order set of dates (someone marks
    distributed without having marked placed) still reports the most
    advanced truthful stage rather than stalling at the gap."""
    if getattr(batch, "status", None) == "CANCELLED":
        return STAGE_CANCELLED

    for stage, field in reversed(STAGE_SEQUENCE):
        if field and getattr(batch, field, None):
            return stage
    return STAGE_SUBMITTED


def stage_index(stage):
    for i, (name, _) in enumerate(STAGE_SEQUENCE):
        if name == stage:
            return i
    return -1


def can_advance_to(batch, stage, all_lines_received=False):
    """Whether a given milestone may be marked right now.

    Rules:
      - a cancelled order advances nowhere;
      - a milestone already marked can't be marked twice;
      - "order received" is never marked by hand;
      - "order distributed" requires the goods to have actually
        arrived, since you can't hand out what you haven't got.
    Earlier milestones are deliberately NOT enforced as prerequisites -
    paperwork often catches up out of order, and blocking that would
    just make people record nothing at all.
    """
    if getattr(batch, "status", None) == "CANCELLED":
        return False
    if stage not in MANUAL_STAGES:
        return False
    if getattr(batch, STAGE_FIELDS[stage], None):
        return False
    if stage == STAGE_DISTRIBUTED and not all_lines_received:
        return False
    return True


def timeline(batch):
    """The four milestones with their dates, for display. Always returns
    all four so the UI can show what's still outstanding, not just what's
    done."""
    return [
        {
            "stage": stage,
            "label": STAGE_LABELS[stage],
            "field": field,
            "at": getattr(batch, field, None),
            "done": bool(getattr(batch, field, None)),
        }
        for stage, field in STAGE_SEQUENCE
        if field
    ]


def line_total(line):
    """Quantity x unit price for one line, or None when no price is
    recorded - None rather than 0 so an unpriced line reads as "unknown"
    instead of "free"."""
    if line.unit_price is None or line.quantity is None:
        return None
    return float(line.unit_price) * line.quantity


def order_total(lines):
    """Sum of the priced lines. Returns (total, all_priced) so the caller
    can show the figure as provisional when some lines have no price."""
    totals = [line_total(l) for l in lines if getattr(l, "status", None) != "CANCELLED"]
    priced = [t for t in totals if t is not None]
    return sum(priced), len(priced) == len(totals)
