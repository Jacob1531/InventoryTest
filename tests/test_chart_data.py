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


# ---- mode selection, normalization, and build_chart ---------------------

from datetime import datetime, timedelta

from services.chart_data import (
    build_chart,
    normalize_mode,
    normalize_limit,
    lowest_stock,
    on_order,
    recently_added,
    MODE_CATEGORY,
    MODE_LOW_STOCK,
    MODE_ON_ORDER,
    MODE_RECENT,
    DEFAULT_MODE,
    DEFAULT_LIMIT,
)


class _FullItem:
    def __init__(self, id, name, category, quantity, created_at=None):
        self.id = id
        self.name = name
        self.category = category
        self.quantity = quantity
        self.created_at = created_at


_NOW = datetime(2026, 1, 10)


def _inventory():
    return [
        _FullItem(1, "Baby Wipes", "Baby", 24, _NOW - timedelta(days=1)),
        _FullItem(2, "Diapers", "Baby", 3, _NOW - timedelta(days=5)),
        _FullItem(3, "Bleach", "Cleaning", 7, _NOW - timedelta(days=2)),
        _FullItem(4, "Mop", "Cleaning", 0, _NOW - timedelta(days=30)),
    ]


def test_unknown_mode_falls_back_to_default():
    assert normalize_mode("NOT_A_MODE") == DEFAULT_MODE
    assert normalize_mode(None) == DEFAULT_MODE


def test_valid_mode_passes_through():
    assert normalize_mode(MODE_LOW_STOCK) == MODE_LOW_STOCK


def test_invalid_limit_falls_back_to_default():
    assert normalize_limit(999) == DEFAULT_LIMIT
    assert normalize_limit("abc") == DEFAULT_LIMIT
    assert normalize_limit(None) == DEFAULT_LIMIT


def test_valid_limit_passes_through():
    assert normalize_limit(20) == 20
    assert normalize_limit("15") == 15


def test_lowest_stock_sorts_ascending():
    rows = lowest_stock(_inventory(), limit=10)
    assert [r["label"] for r in rows] == ["Mop", "Diapers", "Bleach", "Baby Wipes"]


def test_lowest_stock_zero_quantity_renders_empty_bar():
    rows = lowest_stock(_inventory(), limit=10)
    assert rows[0]["count"] == 0
    assert rows[0]["percent"] == 0


def test_lowest_stock_ignores_items_with_no_quantity():
    items = _inventory() + [_FullItem(9, "Unknown", "Misc", None)]
    rows = lowest_stock(items, limit=10)
    assert "Unknown" not in [r["label"] for r in rows]


def test_on_order_only_includes_items_with_pending_orders():
    rows = on_order(_inventory(), {1: 50, 3: 10}, limit=10)
    assert [r["label"] for r in rows] == ["Baby Wipes", "Bleach"]


def test_on_order_is_empty_when_nothing_pending():
    assert on_order(_inventory(), {}, limit=10) == []


def test_recently_added_newest_first():
    rows = recently_added(_inventory(), limit=10)
    assert rows[0]["label"] == "Baby Wipes"
    assert rows[-1]["label"] == "Mop"


def test_recently_added_tolerates_missing_created_at():
    """Rows predating the created_at column shouldn't crash the sort -
    they just sort last."""
    items = _inventory() + [_FullItem(9, "Legacy", "Misc", 5, None)]
    rows = recently_added(items, limit=10)
    assert rows[-1]["label"] == "Legacy"


def test_build_chart_returns_title_and_value_label():
    chart = build_chart(_inventory(), mode=MODE_LOW_STOCK)
    assert chart["title"] == "Lowest Stock"
    assert chart["value_label"] == "Qty"
    assert chart["mode"] == MODE_LOW_STOCK


def test_build_chart_category_filter_scopes_rows_and_title():
    chart = build_chart(_inventory(), mode=MODE_LOW_STOCK, category="Baby")
    assert [r["label"] for r in chart["rows"]] == ["Diapers", "Baby Wipes"]
    assert "Baby" in chart["title"]


def test_build_chart_respects_limit():
    chart = build_chart(_inventory(), mode=MODE_LOW_STOCK, limit=5)
    assert len(chart["rows"]) <= 5


def test_build_chart_with_no_items_returns_empty_rows():
    chart = build_chart([], mode=MODE_CATEGORY)
    assert chart["rows"] == []
    assert chart["title"]


def test_build_chart_sanitizes_bad_mode_and_limit():
    chart = build_chart(_inventory(), mode="GARBAGE", limit=12345)
    assert chart["mode"] == DEFAULT_MODE
    assert len(chart["rows"]) <= DEFAULT_LIMIT


def test_build_chart_category_mode_still_works():
    chart = build_chart(_inventory(), mode=MODE_CATEGORY)
    labels = [r["label"] for r in chart["rows"]]
    assert set(labels) == {"Baby", "Cleaning"}
