"""
chart_data.py
=====================================================================
Pure, DB-independent helpers that shape data for the dashboard's
inline SVG/CSS charts. No charting library is used anywhere in this
app - the templates render plain bars sized from these percentages -
so this module's job is simply to turn rows into (label, count,
percent) tuples.

Kept separate from the routes so the bucketing and percentage maths
can be unit tested directly.
=====================================================================
"""


def category_breakdown(items, limit=6):
    """Counts active inventory items per category, biggest first.

    Returns a list of dicts: {"label", "count", "percent"} where
    percent is relative to the LARGEST category (not to the total), so
    the biggest bar always fills the track and the chart stays readable
    whether there are 3 categories or 30.

    Anything beyond `limit` categories is folded into a single "Other"
    bucket so the chart can't grow unbounded. "Other" is appended last
    regardless of its size, since it isn't a real category.
    """
    counts = {}
    for item in items:
        label = (item.category or "").strip() or "Uncategorized"
        counts[label] = counts.get(label, 0) + 1

    if not counts:
        return []

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    top = ordered[:limit]
    remainder = ordered[limit:]
    if remainder:
        top.append(("Other", sum(count for _, count in remainder)))

    largest = max(count for _, count in top)

    return [
        {
            "label": label,
            "count": count,
            # guard against divide-by-zero if every count were somehow 0
            "percent": round((count / largest) * 100) if largest else 0,
        }
        for label, count in top
    ]
