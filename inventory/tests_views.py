"""
Model and service tests for the inventory app.

Note: The inventory app doesn't have URL routes configured yet.
These tests focus on model and service functionality.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ServicePackage
from inventory.models import Carcass, MeatCut, Offal, StorageLocation
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_view_data():
    user = User.objects.create_user(username="inv_move_user", password="testpass123", role=User.Role.CLIENT)
    profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1234567890",
        address="Test Address",
    )
    service = ServicePackage.objects.create(name="Move Test Package", includes_disassembly=True)
    order = SlaughterOrder.objects.create(client=profile, order_datetime=timezone.now(), service_package=service)
    animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="MOVE-TEST-001")
    animal.perform_slaughter()
    animal.save()
    freezer = StorageLocation.objects.create(name="Test Freezer", location_type="freezer")
    cooler = StorageLocation.objects.create(name="Test Cooler", location_type="cooler")

    return SimpleNamespace(
        user=user,
        profile=profile,
        service=service,
        order=order,
        animal=animal,
        freezer=freezer,
        cooler=cooler,
    )


class TestStorageLocationModel:
    def test_create_storage_location(self):
        location = StorageLocation.objects.create(name="Test Freezer", location_type="freezer")

        assert location.name == "Test Freezer"
        assert location.location_type == "freezer"

    def test_all_location_types(self):
        location_types = ["freezer", "cooler", "dry_storage", "processing"]

        for loc_type in location_types:
            location = StorageLocation.objects.create(name=f"{loc_type.title()} Location", location_type=loc_type)
            assert location.location_type == loc_type

    def test_location_str_representation(self):
        location = StorageLocation.objects.create(name="Main Freezer", location_type="freezer")

        assert "Main Freezer" in str(location)


class TestInventoryMovement:
    def test_move_carcass_between_locations(self, inventory_view_data):
        carcass = Carcass.objects.create(
            animal=inventory_view_data.animal,
            hot_carcass_weight=Decimal("250.00"),
            disposition="for_sale",
            storage_location=inventory_view_data.freezer,
        )

        assert carcass.storage_location == inventory_view_data.freezer

        from inventory.services import move_inventory_item

        moved = move_inventory_item(carcass, inventory_view_data.cooler)

        assert moved.storage_location == inventory_view_data.cooler

    def test_move_meat_cut(self, inventory_view_data):
        carcass = Carcass.objects.create(
            animal=inventory_view_data.animal,
            hot_carcass_weight=Decimal("250.00"),
            disposition="for_sale",
            storage_location=inventory_view_data.freezer,
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass,
            cut_type=MeatCut.BeefCuts.RIBEYE,
            weight=Decimal("10.0"),
            disposition="for_sale",
            storage_location=inventory_view_data.freezer,
        )

        from inventory.services import move_inventory_item

        moved = move_inventory_item(meat_cut, inventory_view_data.cooler)

        assert moved.storage_location == inventory_view_data.cooler


class TestDispositionUpdate:
    def test_update_carcass_disposition(self, inventory_view_data):
        carcass = Carcass.objects.create(
            animal=inventory_view_data.animal, hot_carcass_weight=Decimal("250.00"), disposition="for_sale"
        )

        from inventory.services import update_inventory_disposition

        updated = update_inventory_disposition(carcass, "returned_to_owner")

        assert updated.disposition == "returned_to_owner"

    def test_all_disposition_types(self, inventory_view_data):
        carcass = Carcass.objects.create(
            animal=inventory_view_data.animal, hot_carcass_weight=Decimal("250.00"), disposition="for_sale"
        )

        from inventory.services import update_inventory_disposition

        for disposition in ["for_sale", "returned_to_owner", "disposed"]:
            updated = update_inventory_disposition(carcass, disposition)
            assert updated.disposition == disposition


@pytest.mark.django_db
class TestInventoryQueries:
    """Pytest-style tests for inventory queries."""

    def test_get_inventory_by_location(self, animal_factory, service_package_factory):
        from inventory.services import get_inventory_by_location

        location = StorageLocation.objects.create(name="Query Test Location", location_type="freezer")

        service = service_package_factory()
        order = SlaughterOrder.objects.create(
            client_name="Test", service_package=service, order_datetime=timezone.now()
        )
        animal = animal_factory(slaughter_order=order)
        animal.perform_slaughter()
        animal.save()

        Carcass.objects.create(
            animal=animal, hot_carcass_weight=Decimal("200"), disposition="for_sale", storage_location=location
        )

        inventory = get_inventory_by_location(location)

        assert "carcasses" in inventory
        assert inventory["carcasses"].count() == 1

    def test_get_inventory_for_animal(self, animal_factory, service_package_factory):
        from inventory.services import get_inventory_for_animal

        service = service_package_factory()
        order = SlaughterOrder.objects.create(
            client_name="Test", service_package=service, order_datetime=timezone.now()
        )
        animal = animal_factory(slaughter_order=order)
        animal.perform_slaughter()
        animal.save()

        carcass = Carcass.objects.create(animal=animal, hot_carcass_weight=Decimal("200"), disposition="for_sale")

        Offal.objects.create(
            animal=animal, offal_type=Offal.BeefOffalTypes.LIVER, weight=Decimal("5"), disposition="for_sale"
        )

        inventory = get_inventory_for_animal(animal)

        assert inventory["carcass"] == carcass
        assert inventory["offal"].count() == 1


@pytest.mark.django_db
class TestStorageLocationTypes:
    def test_location_types(self):
        location_types = ["freezer", "cooler", "dry_storage", "processing"]

        for loc_type in location_types:
            location = StorageLocation.objects.create(name=f"{loc_type.title()} Location", location_type=loc_type)
            assert location.location_type == loc_type
