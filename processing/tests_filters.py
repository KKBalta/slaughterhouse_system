from __future__ import annotations

from decimal import Decimal

from processing.templatetags.processing_filters import grams_to_kg, sum_weights


class _FakeQuerySet:
    def __init__(self, total):
        self.total = total

    def __bool__(self):
        return True

    def aggregate(self, **kwargs):
        assert "total" in kwargs
        return {"total": self.total}


def test_grams_to_kg_handles_none():
    assert grams_to_kg(None) == "0 kg"


def test_grams_to_kg_formats_valid_values():
    assert grams_to_kg("2700") == "2.70 kg"


def test_grams_to_kg_handles_invalid_values():
    assert grams_to_kg("abc") == "0 kg"


def test_sum_weights_handles_empty_queryset():
    assert sum_weights(None) == 0


def test_sum_weights_returns_aggregate_total():
    assert sum_weights(_FakeQuerySet(Decimal("5.25"))) == Decimal("5.25")


def test_sum_weights_returns_zero_for_empty_aggregate():
    assert sum_weights(_FakeQuerySet(None)) == 0
