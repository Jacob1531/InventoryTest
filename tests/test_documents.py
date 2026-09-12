"""
Tests for services/documents.py - operational document types and the
record a document can be attached to.

Run with: pytest tests/test_documents.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.documents import (
    DEFAULT_DOC_TYPE,
    DOC_TYPE_VALUES,
    RELATED_INVENTORY_ITEM,
    RELATED_ORDER_BATCH,
    doc_type_label,
    normalize_doc_type,
    normalize_related,
    related_label,
)


def test_known_type_passes_through():
    assert normalize_doc_type("INVOICE") == "INVOICE"


def test_unknown_type_falls_back_to_default():
    assert normalize_doc_type("SOMETHING_ELSE") == DEFAULT_DOC_TYPE


def test_missing_type_falls_back_to_default():
    assert normalize_doc_type(None) == DEFAULT_DOC_TYPE
    assert normalize_doc_type("") == DEFAULT_DOC_TYPE


def test_every_declared_type_normalizes_to_itself():
    for value in DOC_TYPE_VALUES:
        assert normalize_doc_type(value) == value


def test_label_for_known_type():
    assert doc_type_label("PACKING_SLIP") == "Packing slip"


def test_label_falls_back_to_raw_value():
    """Documents uploaded before the fixed list existed hold free text.
    They should still display something rather than a blank cell."""
    assert doc_type_label("Old Free Text") == "Old Free Text"


def test_label_of_none_is_none():
    assert doc_type_label(None) is None


# ---- related record linking ---------------------------------------------

def test_valid_order_link():
    assert normalize_related(RELATED_ORDER_BATCH, 5) == (RELATED_ORDER_BATCH, 5)


def test_valid_item_link_with_string_id():
    assert normalize_related(RELATED_INVENTORY_ITEM, "7") == (RELATED_INVENTORY_ITEM, 7)


def test_type_without_id_does_not_link():
    assert normalize_related(RELATED_ORDER_BATCH, None) == (None, None)


def test_id_without_type_does_not_link():
    assert normalize_related(None, 5) == (None, None)


def test_unknown_type_does_not_link():
    assert normalize_related("SOMETHING", 5) == (None, None)


def test_non_numeric_id_does_not_link():
    assert normalize_related(RELATED_ORDER_BATCH, "abc") == (None, None)


def test_zero_and_negative_ids_do_not_link():
    assert normalize_related(RELATED_ORDER_BATCH, 0) == (None, None)
    assert normalize_related(RELATED_ORDER_BATCH, -3) == (None, None)


def test_related_labels_exist_for_both_types():
    assert related_label(RELATED_ORDER_BATCH)
    assert related_label(RELATED_INVENTORY_ITEM)
    assert related_label("UNKNOWN") is None
