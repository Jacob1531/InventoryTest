"""
Tests for services/chart_data.py - the category breakdown behind the
dashboard's inventory chart.

Run with: pytest tests/test_chart_data.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chart_data import category_breakdown


class _Item:
    def __init__(self, category):
        self.category = category


def _items(**counts):
    out = []
    for label, n in counts.items():
        out.extend(_Item(label) for _ in range(n))
    return out


def test_empty_input_returns_empty_list():
    assert category_breakdown([]) == []


def test_counts_items_per_category():
    result = category_breakdown(_items(Food=5, Cleaning=2))
    counts = {row["label"]: row["count"] for row in result}
    assert counts == {"Food": 5, "Cleaning": 2}


def test_sorted_largest_first():
    result = category_breakdown(_items(Small=1, Large=9, Medium=4))
    assert [row["label"] for row in result] == ["Large", "Medium", "Small"]


def test_largest_category_is_always_full_width():
    result = category_breakdown(_items(Food=7, Other=3))
    assert result[0]["percent"] == 100


def test_percent_is_relative_to_largest_not_total():
    """Two categories of 5 and 1: the smaller should be 20% of the bar
    track (1/5), not 17% (1/6 of the total)."""
    result = category_breakdown(_items(Big=5, Small=1))
    assert result[1]["percent"] == 20


def test_none_category_becomes_uncategorized():
    result = category_breakdown([_Item(None), _Item(None), _Item("Food")])
    counts = {row["label"]: row["count"] for row in result}
    assert counts["Uncategorized"] == 2


def test_blank_and_whitespace_category_becomes_uncategorized():
    result = category_breakdown([_Item(""), _Item("   "), _Item("Food")])
    counts = {row["label"]: row["count"] for row in result}
    assert counts["Uncategorized"] == 2


def test_category_whitespace_is_stripped():
    result = category_breakdown([_Item("  Food  "), _Item("Food")])
    assert len(result) == 1
    assert result[0]["label"] == "Food"
    assert result[0]["count"] == 2


def test_overflow_categories_fold_into_other():
    items = _items(A=10, B=9, C=8, D=7, E=6, F=5, G=4, H=3, I=2)
    result = category_breakdown(items, limit=6)
    labels = [row["label"] for row in result]
    assert len(result) == 7
    assert labels[-1] == "Other"
    assert result[-1]["count"] == 4 + 3 + 2


def test_other_is_appended_last_even_when_large():
    """'Other' isn't a real category, so it shouldn't be sorted in among
    them by size - it belongs at the end regardless."""
    items = _items(A=3, B=3, C=20, D=20, E=20)
    result = category_breakdown(items, limit=2)
    assert result[-1]["label"] == "Other"
    assert result[-1]["count"] > result[0]["count"]


def test_no_other_bucket_when_within_limit():
    result = category_breakdown(_items(A=2, B=1), limit=6)
    assert [row["label"] for row in result] == ["A", "B"]


def test_every_row_has_the_expected_keys():
    for row in category_breakdown(_items(Food=2)):
        assert set(row) == {"label", "count", "percent"}


def test_percent_never_exceeds_one_hundred():
    result = category_breakdown(_items(A=100, B=50, C=1))
    assert all(0 <= row["percent"] <= 100 for row in result)
