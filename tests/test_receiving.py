"""
Tests for services/receiving.py - partial deliveries, over-deliveries,
and the batch status derived from line states.

Run with: pytest tests/test_receiving.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.receiving import (
    apply_receipt,
    batch_status_from_lines,
    line_status_after,
    outstanding,
    summarize_batch,
    BATCH_CANCELLED,
    BATCH_OPEN,
    BATCH_RECEIVED,
    STATUS_CANCELLED,
    STATUS_PARTIAL,
    STATUS_PENDING,
    STATUS_RECEIVED,
)


class _Line:
    def __init__(self, quantity, quantity_received=0, status=STATUS_PENDING):
        self.quantity = quantity
        self.quantity_received = quantity_received
        self.status = status


# ---- outstanding --------------------------------------------------------

def test_outstanding_on_untouched_line():
    assert outstanding(_Line(10)) == 10


def test_outstanding_after_partial_delivery():
    assert outstanding(_Line(10, 4, STATUS_PARTIAL)) == 6


def test_outstanding_is_zero_when_complete():
    assert outstanding(_Line(10, 10, STATUS_RECEIVED)) == 0


def test_over_delivery_never_goes_negative():
    """More arrived than ordered. Outstanding must clamp at zero - a
    negative would subtract from other items' on-order totals."""
    assert outstanding(_Line(10, 12, STATUS_RECEIVED)) == 0


def test_cancelled_line_owes_nothing():
    assert outstanding(_Line(10, 0, STATUS_CANCELLED)) == 0


# ---- line status --------------------------------------------------------

def test_status_pending_when_nothing_received():
    assert line_status_after(10, 0) == STATUS_PENDING


def test_status_partial_when_some_received():
    assert line_status_after(10, 4) == STATUS_PARTIAL


def test_status_received_when_complete():
    assert line_status_after(10, 10) == STATUS_RECEIVED


def test_status_received_when_over_delivered():
    assert line_status_after(10, 12) == STATUS_RECEIVED


# ---- apply_receipt ------------------------------------------------------

def test_partial_receipt_leaves_line_open():
    total, status, added = apply_receipt(_Line(10), 4)
    assert (total, status, added) == (4, STATUS_PARTIAL, 4)


def test_second_shipment_completes_the_line():
    total, status, added = apply_receipt(_Line(10, 4, STATUS_PARTIAL), 6)
    assert (total, status, added) == (10, STATUS_RECEIVED, 6)


def test_overage_still_goes_into_stock():
    """The extra units are physically on the shelf, so inventory must
    increase by what arrived, not by what was ordered."""
    total, status, added = apply_receipt(_Line(10), 12)
    assert added == 12
    assert status == STATUS_RECEIVED


def test_receiving_zero_leaves_line_pending():
    total, status, added = apply_receipt(_Line(10), 0)
    assert (total, status, added) == (0, STATUS_PENDING, 0)


def test_negative_receipt_is_rejected():
    with pytest.raises(ValueError):
        apply_receipt(_Line(10), -1)


def test_missing_receipt_quantity_is_rejected():
    with pytest.raises(ValueError):
        apply_receipt(_Line(10), None)


def test_cannot_receive_against_a_cancelled_line():
    with pytest.raises(ValueError):
        apply_receipt(_Line(10, 0, STATUS_CANCELLED), 5)


def test_cannot_receive_against_a_completed_line():
    with pytest.raises(ValueError):
        apply_receipt(_Line(10, 10, STATUS_RECEIVED), 1)


# ---- batch status -------------------------------------------------------

def test_empty_batch_is_open():
    assert batch_status_from_lines([]) == BATCH_OPEN


def test_batch_open_while_any_line_is_pending():
    lines = [_Line(1, 1, STATUS_RECEIVED), _Line(1, 0, STATUS_PENDING)]
    assert batch_status_from_lines(lines) == BATCH_OPEN


def test_batch_open_while_any_line_is_partial():
    assert batch_status_from_lines([_Line(10, 4, STATUS_PARTIAL)]) == BATCH_OPEN


def test_batch_received_when_all_lines_complete():
    lines = [_Line(1, 1, STATUS_RECEIVED), _Line(2, 2, STATUS_RECEIVED)]
    assert batch_status_from_lines(lines) == BATCH_RECEIVED


def test_batch_cancelled_only_when_every_line_is():
    lines = [_Line(1, 0, STATUS_CANCELLED), _Line(1, 0, STATUS_CANCELLED)]
    assert batch_status_from_lines(lines) == BATCH_CANCELLED


def test_cancelled_lines_do_not_hold_a_batch_open():
    """A cancelled line is resolved, not outstanding - it shouldn't stop
    the batch closing once everything else has arrived."""
    lines = [_Line(1, 1, STATUS_RECEIVED), _Line(1, 0, STATUS_CANCELLED)]
    assert batch_status_from_lines(lines) == BATCH_RECEIVED


# ---- batch summary ------------------------------------------------------

def test_summary_excludes_cancelled_from_totals():
    lines = [
        _Line(10, 4, STATUS_PARTIAL),
        _Line(5, 5, STATUS_RECEIVED),
        _Line(3, 0, STATUS_CANCELLED),
    ]
    assert summarize_batch(lines) == {
        "lines": 3,
        "open_lines": 1,
        "ordered": 15,
        "received": 9,
        "outstanding": 6,
    }


def test_summary_of_empty_batch():
    assert summarize_batch([]) == {
        "lines": 0, "open_lines": 0, "ordered": 0, "received": 0, "outstanding": 0,
    }
