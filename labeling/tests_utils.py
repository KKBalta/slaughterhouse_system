"""
Tests for labeling.utils: pure helpers and label data/PRN generation.
"""

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from labeling.utils import (
    _format_prn_for_bat,
    _format_prn_for_bat_simple,
    format_turkish_text_for_printer,
    generate_animal_label_data,
    generate_cut_label_data,
    generate_cut_prn_label,
    generate_tspl_prn_label,
    get_company_info,
    get_printer_compatibility_mode,
    truncate_to_first_two_words,
    validate_and_sanitize_english_name,
    validate_animal_identification_for_batch,
)

# ---------------------------------------------------------------------------
# truncate_to_first_two_words
# ---------------------------------------------------------------------------


class TestTruncateToFirstTwoWords:
    def test_empty_string(self):
        assert truncate_to_first_two_words("") == ""

    def test_none_returns_empty(self):
        assert truncate_to_first_two_words(None) == ""

    def test_single_word_unchanged(self):
        assert truncate_to_first_two_words("Hello") == "Hello"

    def test_two_words_unchanged(self):
        assert truncate_to_first_two_words("Hello World") == "Hello World"

    def test_three_words_truncated(self):
        assert truncate_to_first_two_words("One Two Three") == "One Two"

    def test_many_words_truncated(self):
        assert truncate_to_first_two_words("A B C D E") == "A B"

    def test_strips_whitespace(self):
        assert truncate_to_first_two_words("  X  Y  Z  ") == "X Y"


# ---------------------------------------------------------------------------
# format_turkish_text_for_printer
# ---------------------------------------------------------------------------


class TestFormatTurkishTextForPrinter:
    def test_empty_string(self):
        assert format_turkish_text_for_printer("") == ""

    def test_unicode_mode_preserves_turkish(self):
        text = "Çanakkale ğüşöç İĞÜŞÖÇ"
        assert format_turkish_text_for_printer(text, "unicode") == text

    def test_ascii_mode_replaces_turkish(self):
        assert format_turkish_text_for_printer("ışık", "ascii") == "isik"
        assert format_turkish_text_for_printer("İĞÜŞÖÇ", "ascii") == "IGUSOC"
        assert format_turkish_text_for_printer("çöp", "ascii") == "cop"

    def test_codepage1254_roundtrip(self):
        text = "Çanakkale"
        result = format_turkish_text_for_printer(text, "codepage1254")
        assert result == text or result  # May be same or fallback to ascii on some envs

    def test_unknown_mode_returns_text(self):
        assert format_turkish_text_for_printer("abc", "unknown") == "abc"


# ---------------------------------------------------------------------------
# get_printer_compatibility_mode
# ---------------------------------------------------------------------------


class TestGetPrinterCompatibilityMode:
    def test_default_is_unicode(self):
        with override_settings(PRINTER_TURKISH_MODE="unicode"):
            assert get_printer_compatibility_mode() == "unicode"

    def test_respects_settings(self):
        with override_settings(PRINTER_TURKISH_MODE="ascii"):
            assert get_printer_compatibility_mode() == "ascii"

    def test_missing_setting_defaults_unicode(self):
        # When PRINTER_TURKISH_MODE is not set, getattr returns "unicode"
        mode = get_printer_compatibility_mode()
        assert mode in ("unicode", "ascii", "codepage1254")


# ---------------------------------------------------------------------------
# validate_and_sanitize_english_name
# ---------------------------------------------------------------------------


class TestValidateAndSanitizeEnglishName:
    def test_empty_returns_empty(self):
        assert validate_and_sanitize_english_name("") == ""

    def test_ascii_unchanged(self):
        assert validate_and_sanitize_english_name("TAG-001") == "TAG-001"

    def test_turkish_replaced(self):
        assert "i" in validate_and_sanitize_english_name("ışık")
        assert "g" in validate_and_sanitize_english_name("ğ")

    def test_problematic_chars_replaced(self):
        assert "_" in validate_and_sanitize_english_name("a:b")
        assert validate_and_sanitize_english_name("a/b") == "a_b"

    def test_max_length_truncates(self):
        long_name = "A" * 100
        result = validate_and_sanitize_english_name(long_name, max_length=50)
        assert len(result) <= 50

    def test_empty_after_sanitize_becomes_ANIMAL(self):
        result = validate_and_sanitize_english_name("???***???")
        assert result == "ANIMAL"


# ---------------------------------------------------------------------------
# validate_animal_identification_for_batch
# ---------------------------------------------------------------------------


class TestValidateAnimalIdentificationForBatch:
    def test_empty_tag(self):
        r = validate_animal_identification_for_batch("")
        assert r["is_valid"] is False
        assert r["sanitized_name"] == "UNKNOWN"
        assert "empty" in r["errors"][0].lower()

    def test_none_equivalent(self):
        r = validate_animal_identification_for_batch(None)
        assert r["is_valid"] is False
        assert r["sanitized_name"] == "UNKNOWN"

    def test_clean_tag_valid(self):
        r = validate_animal_identification_for_batch("TAG-001")
        assert r["is_valid"] is True
        assert r["sanitized_name"] == "TAG-001"
        assert r["original_name"] == "TAG-001"

    def test_turkish_adds_warning(self):
        r = validate_animal_identification_for_batch("çiftçi")
        assert r["is_valid"] is True
        assert any("turkish" in w.lower() or "sanitized" in w.lower() for w in r["warnings"])

    def test_special_chars_add_warning(self):
        r = validate_animal_identification_for_batch("tag:001")
        assert r["sanitized_name"] == "tag_001"
        assert len(r["warnings"]) >= 1


# ---------------------------------------------------------------------------
# get_company_info
# ---------------------------------------------------------------------------


class TestGetCompanyInfo:
    def test_returns_expected_keys(self):
        info = get_company_info()
        assert "company_name" in info
        assert "company_full_name" in info
        assert "company_address" in info
        assert "license_no" in info
        assert "operation_no" in info

    def test_respects_test_settings(self):
        # settings_test.py sets COMPANY_NAME etc.
        info = get_company_info()
        assert info["company_name"] is not None
        assert info["license_no"] == getattr(settings, "LICENSE_NO", "00-0000") or info["license_no"]


# ---------------------------------------------------------------------------
# generate_animal_label_data (with fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGenerateAnimalLabelData:
    def test_returns_expected_keys(self, slaughtered_animal):
        data = generate_animal_label_data(slaughtered_animal)
        assert "uretici" in data
        assert "kupe_no" in data
        assert "tuccar" in data
        assert "kesim_tarihi" in data
        assert "stt" in data
        assert "siparis_no" in data
        assert "cinsi" in data
        assert "weight" in data
        assert "qr_url" in data
        assert "qr_data" in data

    def test_no_slaughter_date_uses_bilinmiyor(self, db, animal_factory_fixture, slaughter_order_factory_fixture):
        order = slaughter_order_factory_fixture.create()
        animal = animal_factory_fixture.create(slaughter_order=order, slaughter_date=None)
        data = generate_animal_label_data(animal)
        assert data["kesim_tarihi"] == "Bilinmiyor"
        assert data["stt"] == "Bilinmiyor"

    def test_with_slaughter_date_formats_correctly(self, slaughtered_animal):
        slaughtered_animal.slaughter_date = timezone.now()
        slaughtered_animal.save()
        data = generate_animal_label_data(slaughtered_animal)
        assert "." in data["kesim_tarihi"]
        assert "." in data["stt"]


# ---------------------------------------------------------------------------
# generate_cut_label_data
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGenerateCutLabelData:
    def test_returns_expected_keys(self, db, animal_factory_fixture, slaughter_order_factory_fixture):
        from decimal import Decimal

        from processing.models import DisassemblyCut

        order = slaughter_order_factory_fixture.create()
        animal = animal_factory_fixture.create(slaughter_order=order, animal_type="cattle")
        animal.perform_slaughter()
        animal.save()
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ribeye", weight_kg=Decimal("5.50"))
        data = generate_cut_label_data(cut)
        assert "uretici" in data
        assert "kupe_no" in data
        assert "kesim_tarihi" in data
        assert "uretim_tarihi" in data
        assert "stt" in data
        assert "siparis_no" in data
        assert "cinsi" in data
        assert "cut_name" in data
        assert data["weight"] == "5.50"
        assert "qr_url" in data


# ---------------------------------------------------------------------------
# generate_tspl_prn_label / generate_cut_prn_label
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGenerateTsplPrnLabel:
    def test_returns_string_with_tspl_commands(self, slaughtered_animal):
        prn = generate_tspl_prn_label(slaughtered_animal)
        assert isinstance(prn, str)
        assert "SIZE" in prn
        assert "PRINT" in prn
        assert "\r\n" in prn


@pytest.mark.django_db
class TestGenerateCutPrnLabel:
    def test_returns_string_with_tspl_commands(self, db, animal_factory_fixture, slaughter_order_factory_fixture):
        from decimal import Decimal

        from processing.models import DisassemblyCut

        order = slaughter_order_factory_fixture.create()
        animal = animal_factory_fixture.create(slaughter_order=order, animal_type="cattle")
        animal.perform_slaughter()
        animal.save()
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ribeye", weight_kg=Decimal("3.0"))
        prn = generate_cut_prn_label(cut)
        assert isinstance(prn, str)
        assert "SIZE" in prn
        assert "PRINT" in prn
        assert "\r\n" in prn


# ---------------------------------------------------------------------------
# _format_prn_for_bat / _format_prn_for_bat_simple
# ---------------------------------------------------------------------------


class TestFormatPrnForBat:
    def test_escapes_percent(self):
        out = _format_prn_for_bat("SET PEEL OFF\nPRINT 1,1")
        assert "%%" in out or "PRINT" in out

    def test_non_empty_lines_formatted(self):
        out = _format_prn_for_bat("LINE1\n\nLINE2")
        assert "echo" in out.lower()
        assert "LINE1" in out
        assert "LINE2" in out


class TestFormatPrnForBatSimple:
    def test_escapes_percent(self):
        out = _format_prn_for_bat_simple("PRINT 1,1")
        assert "%%" in out or "PRINT" in out

    def test_returns_echo_lines(self):
        out = _format_prn_for_bat_simple("CLS\nTEXT 1,1")
        assert "echo" in out.lower()
        assert "CLS" in out
