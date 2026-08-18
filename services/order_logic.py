"""
order_logic.py
=====================================================================
Pure, DB-independent order calculations. Kept separate from the Flask
routes so this logic (a) isn't duplicated across the routes that need
it (inventory() and low_stock_items() both need "how much of each
item is on order"), and (b) can be unit tested directly without a
database.
=====================================================================
"""


def compute_on_order_totals(pending_orders):
    """Given an iterable of pending orders (anything with .item_id and
    .quantity attributes - an InventoryOrder row works directly), returns
    {item_id: total_pending_quantity}. Callers are expected to have
    already filtered to PENDING orders; this function doesn't check
    status itself, so it can work equally well against ORM rows or
    plain test doubles."""
    totals = {}
    for order in pending_orders:
        totals[order.item_id] = totals.get(order.item_id, 0) + order.quantity
    return totals
