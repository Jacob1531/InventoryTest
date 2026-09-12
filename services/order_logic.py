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
from services.receiving import outstanding


def compute_on_order_totals(open_orders):
    """Given an iterable of OPEN order lines (PENDING or PARTIAL), returns
    {item_id: quantity_still_inbound}.

    Sums what's still OUTSTANDING, not what was originally ordered. Those
    used to be the same number, but once a line can be partially received
    they diverge: a line for 10 with 6 already delivered has only 4 still
    on the way, and showing 10 would overstate incoming stock.

    Lines whose outstanding amount is zero are omitted entirely rather
    than recorded as 0, so callers can treat "absent" and "nothing
    inbound" the same way.
    """
    totals = {}
    for order in open_orders:
        remaining = outstanding(order)
        if remaining <= 0:
            continue
        totals[order.item_id] = totals.get(order.item_id, 0) + remaining
    return totals
