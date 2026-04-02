from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from labeling.forms import CustomLabelForm

pytestmark = pytest.mark.django_db


def _valid_custom_label_data():
    today = timezone.now().date()
    return {
        "uretici": "Uretici",
        "kupe_no": "TR-001",
        "tuccar": "Tuccar",
        "kesim_tarihi": today.isoformat(),
        "stt": (today + timedelta(days=10)).isoformat(),
        "siparis_no": "SIP-1",
        "cinsi": "SIGIR",
        "weight": "12.50",
        "sakatat_status": "0.51",
        "qr_data": "QR-001",
    }


def test_custom_label_form_sets_defaults_and_required_flags():
    today = timezone.now().date()
    form = CustomLabelForm()

    assert form.fields["kesim_tarihi"].initial == today
    assert form.fields["stt"].initial == today + timedelta(days=10)
    assert form.fields["sakatat_status"].initial == "0.51"

    assert form.fields["uretici"].required is True
    assert form.fields["kupe_no"].required is True
    assert form.fields["kesim_tarihi"].required is True
    assert form.fields["stt"].required is True
    assert form.fields["cinsi"].required is True
    assert form.fields["weight"].required is True
    assert form.fields["tuccar"].required is False
    assert form.fields["siparis_no"].required is False
    assert form.fields["sakatat_status"].required is False
    assert form.fields["qr_data"].required is False


def test_custom_label_form_rejects_non_positive_weight():
    data = _valid_custom_label_data()
    data["weight"] = "0"

    form = CustomLabelForm(data=data)

    assert not form.is_valid()
    assert form.errors["weight"] == ["Ağırlık 0'dan büyük olmalıdır."]


def test_custom_label_form_rejects_expiration_before_slaughter_date():
    data = _valid_custom_label_data()
    data["stt"] = (timezone.now().date() - timedelta(days=1)).isoformat()

    form = CustomLabelForm(data=data)

    assert not form.is_valid()
    assert form.non_field_errors() == ["Son tüketim tarihi kesim tarihinden önce olamaz."]


def test_custom_label_form_accepts_valid_data():
    data = _valid_custom_label_data()

    form = CustomLabelForm(data=data)

    assert form.is_valid(), form.errors
    instance = form.save(commit=False)
    assert str(instance.weight) == "12.50"
    assert instance.cinsi == "SIGIR"
