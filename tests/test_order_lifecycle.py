"""
Tests for services/order_lifecycle.py - the four "Office Use Only"
milestones from the paper order form, and line/order totals.

Run with: pytest tests/test_order_lifecycle.py
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.order_lifecycle import (
    MANUAL_STAGES,
    STAGE_CANCELLED,
    STAGE_DISTRIBUTED,
    STAGE_FORM_RECEIVED,
    STAGE_PLACED,
    STAGE_RECEIVED,
    STAGE_SUBMITTED,
    can_advance_to,
    current_stage,
    line_total,
    order_total,
    timeline,
)

NOW = datetime(2026, 5, 1, 10, 0)


class _Batch:
    def __init__(self, **kwargs):
        self.status = "OPEN"
        self.form_received_at = None
        self.order_placed_at = None
        self.order_received_at = None
        self.order_distributed_at = None
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Line:
    def __init__(self, quantity=3, unit_price=10.0, status="PENDING"):
        self.quantity = quantity
        self.unit_price = unit_price
        self.status = status


# ---- stage derivation ---------------------------------------------------

def test_new_order_is_submitted():
    assert current_stage(_Batch()) == STAGE_SUBMITTED


def test_stage_follows_the_dates():
    assert current_stage(_Batch(form_received_at=NOW)) == STAGE_FORM_RECEIVED
    assert current_stage(_Batch(form_received_at=NOW, order_placed_at=NOW)) == STAGE_PLACED
    assert current_stage(
        _Batch(form_received_at=NOW, order_placed_at=NOW, order_received_at=NOW)
    ) == STAGE_RECEIVED
    assert current_stage(
        _Batch(form_received_at=NOW, order_placed_at=NOW,
               order_received_at=NOW, order_distributed_at=NOW)
    ) == STAGE_DISTRIBUTED


def test_cancelled_overrides_every_other_stage():
    batch = _Batch(status="CANCELLED", form_received_at=NOW, order_placed_at=NOW)
    assert current_stage(batch) == STAGE_CANCELLED


def test_out_of_order_dates_report_the_furthest_stage():
    """Paperwork catches up out of order in real life. A batch marked
    distributed without an earlier mark should report DISTRIBUTED, not
    stall at the gap."""
    assert current_stage(_Batch(order_distributed_at=NOW)) == STAGE_DISTRIBUTED


# ---- advancement rules --------------------------------------------------

def test_can_mark_the_first_milestone_on_a_new_order():
    assert can_advance_to(_Batch(), STAGE_FORM_RECEIVED) is True


def test_cannot_mark_a_milestone_twice():
    assert can_advance_to(_Batch(form_received_at=NOW), STAGE_FORM_RECEIVED) is False


def test_received_is_never_marked_by_hand():
    """It's derived from the line items actually arriving, so it must not
    be settable from a button."""
    assert STAGE_RECEIVED not in MANUAL_STAGES
    assert can_advance_to(_Batch(), STAGE_RECEIVED, all_lines_received=True) is False


def test_cannot_distribute_before_the_goods_arrive():
    assert can_advance_to(_Batch(), STAGE_DISTRIBUTED, all_lines_received=False) is False


def test_can_distribute_once_everything_has_arrived():
    assert can_advance_to(_Batch(), STAGE_DISTRIBUTED, all_lines_received=True) is True


def test_a_cancelled_order_advances_nowhere():
    batch = _Batch(status="CANCELLED")
    for stage in MANUAL_STAGES:
        assert can_advance_to(batch, stage, all_lines_received=True) is False


def test_earlier_milestones_are_not_prerequisites():
    """Deliberate: blocking out-of-order marking would just lead to
    nothing being recorded at all."""
    assert can_advance_to(_Batch(), STAGE_PLACED) is True


# ---- timeline -----------------------------------------------------------

def test_timeline_always_lists_all_four_milestones():
    assert len(timeline(_Batch())) == 4


def test_timeline_marks_which_are_done():
    steps = timeline(_Batch(form_received_at=NOW))
    assert steps[0]["done"] is True
    assert steps[1]["done"] is False


# ---- totals -------------------------------------------------------------

def test_line_total_multiplies_quantity_by_price():
    assert line_total(_Line(quantity=3, unit_price=12.5)) == 37.5


def test_line_total_is_none_without_a_price():
    """None, not zero - an unpriced line is unknown, not free."""
    assert line_total(_Line(unit_price=None)) is None


def test_line_total_is_none_without_a_quantity():
    assert line_total(_Line(quantity=None)) is None


def test_order_total_sums_priced_lines():
    total, all_priced = order_total([_Line(3, 10.0), _Line(2, 5.0)])
    assert total == 40.0
    assert all_priced is True


def test_order_total_flags_when_some_lines_are_unpriced():
    total, all_priced = order_total([_Line(3, 10.0), _Line(2, None)])
    assert total == 30.0
    assert all_priced is False


def test_order_total_excludes_cancelled_lines():
    total, _ = order_total([_Line(3, 10.0), _Line(99, 1.0, status="CANCELLED")])
    assert total == 30.0


def test_order_total_of_no_lines_is_zero_and_fully_priced():
    total, all_priced = order_total([])
    assert total == 0
    assert all_priced is True
