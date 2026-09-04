"""
Tests for services/category_colors.py - the stable per-category colour
assignment used by inventory pills, chart bars, and file categories.

Run with: pytest tests/test_category_colors.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.category_colors import category_color, PALETTE_SIZE, NEUTRAL


VALID_SLOTS = {str(i) for i in range(PALETTE_SIZE)}


# ---- neutral cases ------------------------------------------------------

def test_none_is_neutral():
    assert category_color(None) == NEUTRAL


def test_empty_string_is_neutral():
    assert category_color("") == NEUTRAL


def test_whitespace_only_is_neutral():
    assert category_color("   ") == NEUTRAL


def test_uncategorized_label_is_neutral():
    """'Uncategorized' is the app's own placeholder label, so it should
    read as absence-of-category, not as a category with a colour."""
    assert category_color("Uncategorized") == NEUTRAL
    assert category_color("uncategorized") == NEUTRAL


# ---- stability ----------------------------------------------------------

def test_same_name_always_same_slot():
    assert category_color("Baby Products") == category_color("Baby Products")


def test_case_insensitive():
    assert category_color("Baby Products") == category_color("baby products")


def test_whitespace_insensitive():
    assert category_color("Baby Products") == category_color("  Baby Products  ")


def test_not_affected_by_hash_randomisation():
    """Python's built-in hash() is randomised per process, which would make
    colours change on every restart. This must not be."""
    import subprocess

    code = (
        "import sys; sys.path.insert(0, %r); "
        "from services.category_colors import category_color; "
        "print(category_color('Baby Products'))"
        % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    ).stdout.strip()
    assert out == category_color("Baby Products")


# ---- range and distribution ---------------------------------------------

def test_result_always_within_palette():
    names = ["Food", "Cleaning", "Baby", "Office", "Medical", "Toys",
             "Furniture", "Electronics", "Bedding", "Paper Goods", "x", "123"]
    for name in names:
        assert category_color(name) in VALID_SLOTS


def test_handles_unusual_names_without_error():
    for name in ["123", "!!!", "ünïcödé", "a" * 500, "  mixed CASE  "]:
        assert category_color(name) in VALID_SLOTS | {NEUTRAL}


def test_spreads_realistic_categories_across_multiple_slots():
    """A hash that clumped everything into one or two slots would defeat
    the purpose - categories would be visually indistinguishable."""
    names = ["Baby Products", "School Supplies", "Office Supplies",
             "Hygiene", "Cleaning Products", "Kitchen Products"]
    slots = {category_color(n) for n in names}
    assert len(slots) >= 4, f"too much collision: {slots}"


def test_numeric_and_string_input_agree():
    """Categories arrive as strings, but the function shouldn't blow up if
    handed something else."""
    assert category_color(123) in VALID_SLOTS
