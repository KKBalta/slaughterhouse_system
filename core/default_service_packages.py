"""
Default ServicePackage rows seeded per tenant schema (see tenants.signals).
"""

from __future__ import annotations

from typing import TypedDict

from .models import ServicePackage


class DefaultPackageSpec(TypedDict):
    name: str
    description: str
    description_tr: str
    name_tr: str
    includes_disassembly: bool
    includes_delivery: bool


DEFAULT_SERVICE_PACKAGES: tuple[DefaultPackageSpec, ...] = (
    {
        "name": "Slaughter",
        "description": "Slaughter only.",
        "description_tr": "Sadece kesim hizmeti.",
        "name_tr": "Kesim",
        "includes_disassembly": False,
        "includes_delivery": False,
    },
    {
        "name": "Slaughter + Disassembly",
        "description": "Slaughter and disassembly.",
        "description_tr": "Kesim ve parçalama dahildir.",
        "name_tr": "Kesim + Parçalama",
        "includes_disassembly": True,
        "includes_delivery": False,
    },
    {
        "name": "Slaughter + Disassembly + Delivery",
        "description": "Slaughter, disassembly, and delivery.",
        "description_tr": "Kesim, parçalama ve teslimat dahildir.",
        "name_tr": "Kesim + Parçalama + Teslimat",
        "includes_disassembly": True,
        "includes_delivery": True,
    },
)


def ensure_default_service_packages() -> None:
    """Create the three default packages if missing (idempotent per tenant schema)."""
    for spec in DEFAULT_SERVICE_PACKAGES:
        ServicePackage.objects.get_or_create(
            name=spec["name"],
            defaults={
                "description": spec["description"],
                "description_tr": spec["description_tr"],
                "name_tr": spec["name_tr"],
                "includes_disassembly": spec["includes_disassembly"],
                "includes_delivery": spec["includes_delivery"],
            },
        )
