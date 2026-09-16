"""
Tests for services/warranty_alerts.py - which hardware warranties need
an alert email, at 60 days, 30 days, and on expiry.

Run with: pytest tests/test_warranty_alerts.py
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.warranty_alerts import (
    alerts_due,
    current_milestone,
    days_until,
    MILESTONE_30,
    MILESTONE_60,
    MILESTONE_EXPIRED,
    MILESTONE_LABELS,
    MILESTONE_SUBJECTS,
)

TODAY = date(2026, 6, 15)


class _Item:
    def __init__(self, id, name, days_out):
        self.id = id
        self.name = name
        self.warranty_expires = (
            TODAY + timedelta(days=days_out) if days_out is not None else None
        )


# ---- milestone boundaries -----------------------------------------------

def test_no_expiry_has_no_milestone():
    assert current_milestone(None, TODAY) is None


def test_more_than_sixty_days_out_has_no_milestone():
    assert current_milestone(TODAY + timedelta(days=61), TODAY) is None


def test_exactly_sixty_days_triggers_the_sixty_day_milestone():
    assert current_milestone(TODAY + timedelta(days=60), TODAY) == MILESTONE_60


def test_thirty_one_days_is_still_the_sixty_day_milestone():
    assert current_milestone(TODAY + timedelta(days=31), TODAY) == MILESTONE_60


def test_exactly_thirty_days_triggers_the_thirty_day_milestone():
    assert current_milestone(TODAY + timedelta(days=30), TODAY) == MILESTONE_30


def test_one_day_out_is_the_thirty_day_milestone():
    assert current_milestone(TODAY + timedelta(days=1), TODAY) == MILESTONE_30


def test_expiring_today_counts_as_expired():
    assert current_milestone(TODAY, TODAY) == MILESTONE_EXPIRED


def test_already_past_counts_as_expired():
    assert current_milestone(TODAY - timedelta(days=90), TODAY) == MILESTONE_EXPIRED


def test_days_until_is_negative_once_past():
    assert days_until(TODAY - timedelta(days=5), TODAY) == -5


# ---- only the most urgent milestone -------------------------------------

def test_item_gets_only_its_most_urgent_milestone():
    """Something 20 days out has passed both the 60- and 30-day marks, but
    should produce one alert, not two."""
    due = alerts_due([_Item(1, "A", 20)], set(), TODAY)
    assert list(due) == [MILESTONE_30]


# ---- robustness to missed runs ------------------------------------------

def test_a_missed_run_still_catches_the_milestone():
    """If the scheduled job doesn't run for a few days, an item that
    slipped from 61 to 58 days must still get its 60-day alert. Exact-day
    matching would have skipped it permanently."""
    due = alerts_due([_Item(1, "A", 58)], set(), TODAY)
    assert list(due) == [MILESTONE_60]


# ---- no duplicates ------------------------------------------------------

def test_already_sent_milestone_is_not_repeated():
    item = _Item(1, "A", 30)
    sent = {(1, MILESTONE_30, item.warranty_expires)}
    assert alerts_due([item], sent, TODAY) == {}


def test_a_different_items_record_does_not_suppress_this_one():
    item = _Item(1, "A", 30)
    sent = {(2, MILESTONE_30, item.warranty_expires)}
    assert list(alerts_due([item], sent, TODAY)) == [MILESTONE_30]


def test_changing_the_expiry_date_rearms_the_alert():
    """Records are keyed by the expiry they were sent for, so extending a
    warranty naturally re-arms its milestones with no explicit reset."""
    item = _Item(1, "A", 30)
    sent_for_old_date = {(1, MILESTONE_30, TODAY + timedelta(days=10))}
    assert list(alerts_due([item], sent_for_old_date, TODAY)) == [MILESTONE_30]


# ---- grouping and ordering ----------------------------------------------

def test_groups_items_by_milestone():
    items = [_Item(1, "Soon", 20), _Item(2, "Later", 45), _Item(3, "Gone", -1)]
    due = alerts_due(items, set(), TODAY)
    assert set(due) == {MILESTONE_30, MILESTONE_60, MILESTONE_EXPIRED}


def test_items_within_a_milestone_are_sorted_soonest_first():
    items = [_Item(1, "Later", 29), _Item(2, "Sooner", 5)]
    due = alerts_due(items, set(), TODAY)
    assert [i.name for i in due[MILESTONE_30]] == ["Sooner", "Later"]


def test_milestones_with_nothing_due_are_omitted():
    """So the caller never sends an empty email."""
    due = alerts_due([_Item(1, "A", 20)], set(), TODAY)
    assert MILESTONE_60 not in due
    assert MILESTONE_EXPIRED not in due


def test_items_without_an_expiry_are_ignored():
    assert alerts_due([_Item(1, "A", None)], set(), TODAY) == {}


def test_empty_input_produces_nothing():
    assert alerts_due([], set(), TODAY) == {}


def test_every_milestone_has_a_label_and_subject():
    for milestone in (MILESTONE_60, MILESTONE_30, MILESTONE_EXPIRED):
        assert MILESTONE_LABELS.get(milestone)
        assert MILESTONE_SUBJECTS.get(milestone)
