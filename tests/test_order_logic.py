"""
Tests for services/order_logic.py - the "how much of each item is
still inbound" aggregation shared by the Inventory, Low Stock, and
Dashboard pages.

Note the contract changed when partial receiving was added: this sums
what's still OUTSTANDING on each line, not what was originally
ordered. Those used to be the same number.

Run with: pytest tests/test_order_logic.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_logic import compute_on_order_totals


class _FakeOrder:
    """Stand-in for an InventoryOrder line. Needs status and
    quantity_received as well as quantity, since outstanding amounts
    depend on all three."""
    def __init__(self, item_id, quantity, quantity_received=0, status="PENDING"):
        self.item_id = item_id
        self.quantity = quantity
        self.quantity_received = quantity_received
        self.status = status


def test_single_untouched_line():
    assert compute_on_order_totals([_FakeOrder(1, 10)]) == {1: 10}


def test_multiple_lines_for_same_item_are_summed():
    orders = [_FakeOrder(1, 10), _FakeOrder(1, 5)]
    assert compute_on_order_totals(orders) == {1: 15}


def test_lines_for_different_items_stay_separate():
    orders = [_FakeOrder(1, 10), _FakeOrder(2, 7)]
    assert compute_on_order_totals(orders) == {1: 10, 2: 7}


def test_empty_list_returns_empty_dict():
    assert compute_on_order_totals([]) == {}


def test_partially_received_line_counts_only_the_remainder():
    """10 ordered with 6 already delivered means 4 still inbound -
    reporting 10 would overstate incoming stock."""
    orders = [_FakeOrder(1, 10, 6, "PARTIAL")]
    assert compute_on_order_totals(orders) == {1: 4}


def test_mix_of_partial_and_untouched_lines():
    orders = [_FakeOrder(1, 10, 6, "PARTIAL"), _FakeOrder(1, 5)]
    assert compute_on_order_totals(orders) == {1: 9}


def test_fully_received_line_is_omitted_entirely():
    """Not recorded as 0 - absent, so callers can treat "no key" and
    "nothing inbound" identically."""
    assert compute_on_order_totals([_FakeOrder(1, 10, 10, "RECEIVED")]) == {}


def test_cancelled_line_contributes_nothing():
    assert compute_on_order_totals([_FakeOrder(1, 10, 0, "CANCELLED")]) == {}


def test_over_delivered_line_does_not_go_negative():
    """12 arrived against 10 ordered. A negative remainder would subtract
    from other lines for the same item."""
    assert compute_on_order_totals([_FakeOrder(1, 10, 12, "RECEIVED")]) == {}


def test_over_delivery_does_not_cancel_out_another_open_line():
    orders = [_FakeOrder(1, 10, 12, "RECEIVED"), _FakeOrder(1, 5)]
    assert compute_on_order_totals(orders) == {1: 5}


def test_caller_is_responsible_for_pre_filtering_to_open_lines():
    """The function trusts the query to have filtered to open statuses;
    it only skips lines whose outstanding amount is zero. This documents
    that expectation rather than testing filtering that lives in the
    route."""
    orders = [_FakeOrder(1, 10), _FakeOrder(1, 999)]
    assert compute_on_order_totals(orders)[1] == 1009
