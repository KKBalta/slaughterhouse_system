from __future__ import annotations

from types import SimpleNamespace

from reception.templatetags.file_filters import basename


def test_basename_uses_name_attribute_when_present():
    value = SimpleNamespace(name="/tmp/uploads/report.pdf")

    assert basename(value) == "report.pdf"


def test_basename_uses_string_representation_otherwise():
    assert basename("/tmp/uploads/image.png") == "image.png"
