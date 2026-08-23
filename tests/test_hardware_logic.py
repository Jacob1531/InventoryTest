"""
Tests for services/hardware_logic.py - warranty status classification
used by the Hardware & Warranty section.

All tests inject a fixed `today` so they never depend on the real
clock and can't start failing on a particular date.

Run with: pytest tests/test_hardware_logic.py
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.hardware_logic import (
    warranty_status,
    days_until_expiry,
    summarize_warranties,
    EXPIRING_SOON_DAYS,
    STATUS_ACTIVE,
    STATUS_EXPIRING,
    STATUS_EXPIRED,
    STATUS_NONE,
)

TODAY = date(2026, 6, 15)


# ---- warranty_status --------------------------------------------------

def test_no_expiry_date_is_status_none():
    assert warranty_status(None, TODAY) == STATUS_NONE


def test_past_date_is_expired():
    assert warranty_status(TODAY - timedelta(days=1), TODAY) == STATUS_EXPIRED


def test_long_past_date_is_expired():
    assert warranty_status(TODAY - timedelta(days=900), TODAY) == STATUS_EXPIRED


def test_expiring_today_is_not_yet_expired():
    """A warranty lapses only once the day has passed - today still counts
    as in-warranty, though it falls inside the 'expiring soon' window."""
    assert warranty_status(TODAY, TODAY) == STATUS_EXPIRING


def test_just_inside_expiring_window():
    assert warranty_status(TODAY + timedelta(days=1), TODAY) == STATUS_EXPIRING


def test_expiring_window_boundary_is_inclusive():
    """Exactly EXPIRING_SOON_DAYS out still counts as expiring soon."""
    assert warranty_status(TODAY + timedelta(days=EXPIRING_SOON_DAYS), TODAY) == STATUS_EXPIRING


def test_one_day_past_expiring_window_is_active():
    assert warranty_status(TODAY + timedelta(days=EXPIRING_SOON_DAYS + 1), TODAY) == STATUS_ACTIVE


def test_far_future_date_is_active():
    assert warranty_status(TODAY + timedelta(days=730), TODAY) == STATUS_ACTIVE


# ---- days_until_expiry -------------------------------------------------

def test_days_until_expiry_none_when_no_date():
    assert days_until_expiry(None, TODAY) is None


def test_days_until_expiry_future():
    assert days_until_expiry(TODAY + timedelta(days=45), TODAY) == 45


def test_days_until_expiry_today_is_zero():
    assert days_until_expiry(TODAY, TODAY) == 0


def test_days_until_expiry_negative_when_already_expired():
    assert days_until_expiry(TODAY - timedelta(days=12), TODAY) == -12


# ---- summarize_warranties ----------------------------------------------

class _Item:
    def __init__(self, warranty_expires):
        self.warranty_expires = warranty_expires


def test_summary_counts_each_status():
    items = [
        _Item(None),
        _Item(TODAY - timedelta(days=1)),
        _Item(TODAY + timedelta(days=10)),
        _Item(TODAY + timedelta(days=365)),
    ]
    counts = summarize_warranties(items, TODAY)
    assert counts == {
        STATUS_ACTIVE: 1,
        STATUS_EXPIRING: 1,
        STATUS_EXPIRED: 1,
        STATUS_NONE: 1,
    }


def test_summary_of_empty_list_is_all_zero():
    counts = summarize_warranties([], TODAY)
    assert counts == {
        STATUS_ACTIVE: 0,
        STATUS_EXPIRING: 0,
        STATUS_EXPIRED: 0,
        STATUS_NONE: 0,
    }


def test_summary_totals_match_input_length():
    items = [_Item(TODAY + timedelta(days=n)) for n in (-5, 0, 30, 200, 400)]
    counts = summarize_warranties(items, TODAY)
    assert sum(counts.values()) == len(items)
