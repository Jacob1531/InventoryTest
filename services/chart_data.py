"""
chart_data.py
=====================================================================
Pure, DB-independent helpers that shape data for the dashboard's
inline CSS bar chart. No charting library is used anywhere in this
app - the template renders plain bars sized from the percentages this
module produces.

The chart is per-user configurable (see models.DashboardPreference):
a MODE decides what is measured, an optional category filter narrows
the source items, and a limit caps how many bars are drawn.

Every mode returns the same row shape - {"label", "count", "percent"} -
so the template stays mode-agnostic. `percent` is always relative to
the LARGEST value in the returned set, not to the total, so the top
bar always fills its track and the chart reads well whether the values
span 3 or 3000.

Kept separate from the routes so all of this can be unit tested
without a database.
=====================================================================
"""

MODE_CATEGORY = "CATEGORY"
MODE_LOW_STOCK = "LOW_STOCK"
MODE_ON_ORDER = "ON_ORDER"
MODE_RECENT = "RECENT"

VALID_MODES = (MODE_CATEGORY, MODE_LOW_STOCK, MODE_ON_ORDER, MODE_RECENT)
VALID_LIMITS = (5, 10, 15, 20)

DEFAULT_MODE = MODE_CATEGORY
DEFAULT_LIMIT = 10

# Heading + value-column meaning for each mode. These differ in UNIT -
# "by category" counts items, the others show quantities - so the chart
# labels its value column rather than showing a bare ambiguous number.
MODE_META = {
    MODE_CATEGORY:  {"title": "Inventory by Category", "value_label": "Items"},
    MODE_LOW_STOCK: {"title": "Lowest Stock",          "value_label": "Qty"},
    MODE_ON_ORDER:  {"title": "On Order",              "value_label": "Qty"},
    MODE_RECENT:    {"title": "Recently Added",        "value_label": "Qty"},
}

MODE_LABELS = {
    MODE_CATEGORY: "Inventory by category",
    MODE_LOW_STOCK: "Lowest stock",
    MODE_ON_ORDER: "On order",
    MODE_RECENT: "Recently added",
}


def normalize_mode(mode):
    return mode if mode in VALID_MODES else DEFAULT_MODE


def normalize_limit(limit):
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return limit if limit in VALID_LIMITS else DEFAULT_LIMIT


def _item_category(item):
    return (item.category or "").strip() or "Uncategorized"


def _with_percentages(rows):
    """rows: list of (label, value, color_key). Returns the chart row
    dicts, with percent relative to the largest value present.

    color_key is the CATEGORY a row should be coloured by - which is the
    label itself in category mode, but the item's category in the
    item-level modes, so a bar always matches its category's pill."""
    if not rows:
        return []
    largest = max(value for _, value, _ in rows)
    return [
        {
            "label": label,
            "count": value,
            "color_key": color_key,
            # guard against divide-by-zero when every value is 0
            "percent": round((value / largest) * 100) if largest else 0,
        }
        for label, value, color_key in rows
    ]


def _filter_by_category(items, category):
    if not category:
        return list(items)
    return [i for i in items if _item_category(i) == category]


def category_breakdown(items, limit=DEFAULT_LIMIT):
    """Counts items per category, biggest first. Anything beyond `limit`
    categories folds into a single "Other" bucket, appended last
    regardless of its size since it isn't a real category."""
    counts = {}
    for item in items:
        label = _item_category(item)
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return []

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    top = ordered[:limit]
    remainder = ordered[limit:]
    if remainder:
        top.append(("Other", sum(count for _, count in remainder)))

    return _with_percentages([(label, count, label) for label, count in top])


def lowest_stock(items, limit=DEFAULT_LIMIT):
    """The items with the least stock on hand, lowest first - the most
    actionable view. Bars are proportional to quantity, so a short bar
    genuinely means low stock."""
    ranked = sorted(
        (i for i in items if i.quantity is not None),
        key=lambda i: (i.quantity, (i.name or "").lower()),
    )[:limit]
    return _with_percentages([(i.name, i.quantity, _item_category(i)) for i in ranked])


def on_order(items, on_order_totals, limit=DEFAULT_LIMIT):
    """Items with stock currently on order, largest inbound first.
    `on_order_totals` maps item id -> pending quantity (see
    services.order_logic.compute_on_order_totals)."""
    rows = []
    for item in items:
        pending = on_order_totals.get(item.id, 0)
        if pending > 0:
            rows.append((item.name, pending, _item_category(item)))
    rows.sort(key=lambda r: (-r[1], (r[0] or "").lower()))
    return _with_percentages(rows[:limit])


def recently_added(items, limit=DEFAULT_LIMIT):
    """Newest items first, showing their current quantity. Items with no
    created_at (possible for rows predating that column) sort last rather
    than crashing the comparison."""
    def sort_key(item):
        created = getattr(item, "created_at", None)
        return (created is None, created)

    ranked = sorted(items, key=sort_key, reverse=True)
    # reverse=True puts "created is None" first, so pull those to the end
    ranked = ([i for i in ranked if getattr(i, "created_at", None) is not None]
              + [i for i in ranked if getattr(i, "created_at", None) is None])
    ranked = ranked[:limit]
    return _with_percentages([(i.name, i.quantity or 0, _item_category(i)) for i in ranked])


def build_chart(items, mode=DEFAULT_MODE, category=None, limit=DEFAULT_LIMIT,
                on_order_totals=None):
    """Single entry point the dashboard route uses. Returns
    {"rows", "title", "value_label", "mode"} - everything the template
    needs, so the template never has to know about modes."""
    mode = normalize_mode(mode)
    limit = normalize_limit(limit)
    scoped = _filter_by_category(items, category)

    if mode == MODE_LOW_STOCK:
        rows = lowest_stock(scoped, limit)
    elif mode == MODE_ON_ORDER:
        rows = on_order(scoped, on_order_totals or {}, limit)
    elif mode == MODE_RECENT:
        rows = recently_added(scoped, limit)
    else:
        rows = category_breakdown(scoped, limit)

    meta = MODE_META[mode]
    title = meta["title"]
    if category:
        title = f"{title} — {category}"

    return {
        "rows": rows,
        "title": title,
        "value_label": meta["value_label"],
        "mode": mode,
    }
