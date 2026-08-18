"""
Tests for services/order_logic.py - the pure "how much is on order"
aggregation shared by the Inventory and Low Stock pages.

Run with: pytest tests/test_order_logic.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_logic import compute_on_order_totals


class _FakeOrder:
    """Stand-in for an InventoryOrder row - only needs the two attributes
    compute_on_order_totals actually reads."""
    def __init__(self, item_id, quantity):
        self.item_id = item_id
        self.quantity = quantity


def test_single_order_for_single_item():
    totals = compute_on_order_totals([_FakeOrder(1, 10)])
    assert totals == {1: 10}


def test_multiple_orders_for_same_item_are_summed():
    orders = [_FakeOrder(1, 10), _FakeOrder(1, 5)]
    totals = compute_on_order_totals(orders)
    assert totals == {1: 15}


def test_orders_for_different_items_stay_separate():
    orders = [_FakeOrder(1, 10), _FakeOrder(2, 7)]
    totals = compute_on_order_totals(orders)
    assert totals == {1: 10, 2: 7}


def test_empty_list_returns_empty_dict():
    assert compute_on_order_totals([]) == {}


def test_caller_is_responsible_for_pre_filtering_by_status():
    """This function sums whatever it's given - it doesn't know about
    PENDING/RECEIVED/CANCELLED itself. Passing already-filtered orders
    (as every caller in app.py does) is what makes the result correct;
    this test documents that expectation rather than testing status
    filtering that doesn't live in this function."""
    orders = [_FakeOrder(1, 10), _FakeOrder(1, 999)]
    totals = compute_on_order_totals(orders)
    assert totals[1] == 1009
