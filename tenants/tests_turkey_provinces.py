"""Tests for Turkish province list and VD label abbreviation map (printer-sensitive)."""

import string

import pytest

from tenants.turkey_provinces import (
    PROVINCE_CHOICES,
    VD_LABEL_ABBREV_BY_PLAKA,
    get_vd_label_prefix_for_plaka,
)


def test_province_choices_count_and_plaka_sequence():
    assert len(PROVINCE_CHOICES) == 81
    plakas = [c[0] for c in PROVINCE_CHOICES]
    assert plakas == [f"{i:02d}" for i in range(1, 82)]
    assert len(set(plakas)) == 81


def test_abbrev_map_has_81_keys_matching_choices():
    plakas = {c[0] for c in PROVINCE_CHOICES}
    assert set(VD_LABEL_ABBREV_BY_PLAKA.keys()) == plakas


def test_abbrev_values_are_non_empty_ascii():
    for abbrev in VD_LABEL_ABBREV_BY_PLAKA.values():
        assert abbrev
        assert abbrev == abbrev.encode("ascii", errors="strict").decode("ascii")
        assert all(c in (string.ascii_letters + string.digits) for c in abbrev)


def test_golden_abbrev_pairs():
    assert VD_LABEL_ABBREV_BY_PLAKA["17"] == "CKALE"
    assert VD_LABEL_ABBREV_BY_PLAKA["06"] == "ANKARA"
    assert VD_LABEL_ABBREV_BY_PLAKA["34"] == "ISTANBUL"


@pytest.mark.parametrize(
    "plaka,expected",
    [
        ("06", "ANKARA"),
        ("17", "CKALE"),
        ("", "CKALE"),
    ],
)
def test_get_vd_label_prefix_for_plaka(plaka, expected):
    assert get_vd_label_prefix_for_plaka(plaka) == expected
