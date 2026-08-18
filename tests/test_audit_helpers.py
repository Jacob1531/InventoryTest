"""
Tests for services/audit_helpers.py - the display formatting used
across Reports, Recent Activity, My Activity, and Added This Week.

Run with: pytest tests/test_audit_helpers.py
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.audit_helpers import (
    format_eastern,
    format_audit_value,
    week_ago_cutoff,
    resolve_item_name,
)


# ---- format_eastern ---------------------------------------------------

def test_summer_datetime_shows_edt():
    # Aug 10 2026, 14:30 UTC -> 10:30 AM EDT (UTC-4 in summer)
    result = format_eastern(datetime(2026, 8, 10, 14, 30))
    assert result == "Aug 10, 10:30 AM EDT"


def test_winter_datetime_shows_est():
    # Jan 10 2026, 14:30 UTC -> 09:30 AM EST (UTC-5 in winter)
    result = format_eastern(datetime(2026, 1, 10, 14, 30))
    assert result == "Jan 10, 09:30 AM EST"


def test_none_datetime_returns_empty_string():
    assert format_eastern(None) == ""


def test_custom_format_string_is_respected():
    result = format_eastern(datetime(2026, 8, 10, 14, 30), fmt="%Y-%m-%d %I:%M %p %Z")
    assert result == "2026-08-10 10:30 AM EDT"


# ---- format_audit_value ------------------------------------------------

def test_small_price_value_is_unchanged():
    assert format_audit_value("price", "3.0") == "3.0"


def test_huge_price_value_uses_scientific_notation():
    huge = "1" + "0" * 59
    assert format_audit_value("price", huge) == "1.00e+59"


def test_value_at_threshold_boundary_is_unchanged():
    assert format_audit_value("price", "999999") == "999999"


def test_value_just_over_threshold_is_converted():
    assert format_audit_value("price", "1000000") == "1.00e+06"


def test_non_numeric_field_is_never_touched_even_if_it_looks_numeric():
    """A person's name or category shouldn't get mangled into scientific
    notation just because it happens to be a numeric-looking string."""
    assert format_audit_value("name", "123456789012") == "123456789012"
    assert format_audit_value("category", "1000000") == "1000000"


def test_none_value_passes_through():
    assert format_audit_value("price", None) is None


def test_field_name_none_passes_through_unchanged():
    """ADD/BULK_UPLOAD/PURGE entries have field_name=None."""
    assert format_audit_value(None, "5") == "5"


def test_non_numeric_garbage_in_numeric_field_does_not_crash():
    assert format_audit_value("price", "not-a-number") == "not-a-number"


def test_negative_large_number_is_converted_too():
    assert format_audit_value("price", "-5000000") == "-5.00e+06"


# ---- week_ago_cutoff -----------------------------------------------------

def test_week_ago_cutoff_is_seven_days_before_now():
    cutoff = week_ago_cutoff()
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - cutoff
    # Allow a little slack for test execution time itself
    assert 6.99 <= delta.total_seconds() / 86400 <= 7.01


# ---- resolve_item_name -------------------------------------------------

def test_resolves_name_for_existing_item():
    assert resolve_item_name({"1": "Canned Beans"}, "1") == "Canned Beans"


def test_falls_back_to_readable_placeholder_for_purged_item():
    assert resolve_item_name({}, "47") == "Item #47 (deleted)"


def test_does_not_confuse_a_falsy_but_present_name():
    """An item legitimately named '' shouldn't be treated the same as a
    missing item - though empty names shouldn't occur in practice, the
    lookup itself should distinguish 'key present' from 'key absent'."""
    assert resolve_item_name({"1": ""}, "1") == ""
