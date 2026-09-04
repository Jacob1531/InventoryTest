"""
category_colors.py
=====================================================================
Assigns each category a stable colour drawn from the DCS logo palette
(blue, orange, purple, green, red, pink).

Colours are DERIVED from the category name rather than stored, which
means:
  - a new category picks up a colour with no setup,
  - the same category is always the same colour everywhere it appears
    (inventory pills, chart bars, file categories),
  - nothing needs backfilling or migrating.

The hash is FNV-1a, written out longhand rather than using Python's
built-in hash(), because hash() is randomised per process by default -
colours would change on every app restart. FNV-1a was chosen over a
simpler polynomial hash after comparing how evenly each spread a
realistic set of category names across the six slots (the polynomial
version left one colour unused and doubled up on others).
=====================================================================
"""

PALETTE_SIZE = 6

# Returned when there's no category at all, so "Uncategorized" reads as
# deliberately neutral rather than being assigned an arbitrary colour.
NEUTRAL = "none"


def category_color(name):
    """Returns a stable slot id ("0".."5") for a category name, or
    NEUTRAL when there isn't one. Case- and whitespace-insensitive, so
    "Baby Products" and "baby products " share a colour."""
    if not name:
        return NEUTRAL

    key = str(name).strip().lower()
    if not key or key == "uncategorized":
        return NEUTRAL

    # FNV-1a, 32-bit
    h = 2166136261
    for ch in key:
        h ^= ord(ch)
        h = (h * 16777619) % 4294967296
    return str(h % PALETTE_SIZE)
