from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import ByProduct, Carcass, MeatCut, Offal, StorageLocation
from inventory.services import (
    assign_label_to_inventory_item,
    get_inventory_by_location,
    get_inventory_for_animal,
    move_inventory_item,
    update_inventory_disposition,
)
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_service_data():
    user = User.objects.create_user(username="testuser", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user, account_type="INDIVIDUAL", phone_number="1234567890", address="123 Test St"
    )
    order = SlaughterOrder.objects.create(client=client_profile, order_datetime=timezone.now())
    animal = Animal.objects.create(slaughter_order=order, animal_type="cattle")
    storage_location_1 = StorageLocation.objects.create(name="Freezer A", location_type="freezer")
    storage_location_2 = StorageLocation.objects.create(name="Cooler B", location_type="cooler")

    carcass = Carcass.objects.create(
        animal=animal,
        hot_carcass_weight=250.0,
        disposition="for_sale",
        storage_location=storage_location_1,
    )
    meat_cut = MeatCut.objects.create(
        carcass=carcass,
        cut_type=MeatCut.BeefCuts.RIBEYE,
        weight=10.0,
        disposition="for_sale",
        storage_location=storage_location_1,
    )
    offal = Offal.objects.create(
        animal=animal,
        offal_type=Offal.BeefOffalTypes.LIVER,
        weight=2.0,
        disposition="for_sale",
        storage_location=storage_location_1,
    )
    by_product = ByProduct.objects.create(
        animal=animal,
        byproduct_type=ByProduct.ByProductTypes.SKIN,
        disposition="for_sale",
        storage_location=storage_location_1,
    )

    return SimpleNamespace(
        user=user,
        client_profile=client_profile,
        order=order,
        animal=animal,
        storage_location_1=storage_location_1,
        storage_location_2=storage_location_2,
        carcass=carcass,
        meat_cut=meat_cut,
        offal=offal,
        by_product=by_product,
    )


class TestInventoryService:
    def test_move_inventory_item(self, inventory_service_data):
        moved_carcass = move_inventory_item(inventory_service_data.carcass, inventory_service_data.storage_location_2)
        assert moved_carcass.storage_location == inventory_service_data.storage_location_2

        moved_meat_cut = move_inventory_item(inventory_service_data.meat_cut, inventory_service_data.storage_location_2)
        assert moved_meat_cut.storage_location == inventory_service_data.storage_location_2
        inventory_service_data.meat_cut.refresh_from_db()
        assert inventory_service_data.meat_cut.storage_location == inventory_service_data.storage_location_2

        moved_offal = move_inventory_item(inventory_service_data.offal, inventory_service_data.storage_location_2)
        assert moved_offal.storage_location == inventory_service_data.storage_location_2
        inventory_service_data.offal.refresh_from_db()
        assert inventory_service_data.offal.storage_location == inventory_service_data.storage_location_2

        moved_by_product = move_inventory_item(
            inventory_service_data.by_product, inventory_service_data.storage_location_2
        )
        assert moved_by_product.storage_location == inventory_service_data.storage_location_2
        inventory_service_data.by_product.refresh_from_db()
        assert inventory_service_data.by_product.storage_location == inventory_service_data.storage_location_2

        with pytest.raises(TypeError):
            move_inventory_item(inventory_service_data.user, inventory_service_data.storage_location_2)

    def test_update_inventory_disposition(self, inventory_service_data):
        updated_carcass = update_inventory_disposition(inventory_service_data.carcass, "disposed")
        assert updated_carcass.disposition == "disposed"

        updated_meat_cut = update_inventory_disposition(inventory_service_data.meat_cut, "returned_to_owner")
        assert updated_meat_cut.disposition == "returned_to_owner"
        inventory_service_data.meat_cut.refresh_from_db()
        assert inventory_service_data.meat_cut.disposition == "returned_to_owner"

        with pytest.raises(TypeError):
            update_inventory_disposition(inventory_service_data.user, "some_disposition")

    def test_assign_label_to_inventory_item(self, inventory_service_data):
        assigned_meat_cut = assign_label_to_inventory_item(inventory_service_data.meat_cut, "LABEL-MC-001")
        assert assigned_meat_cut.label_id == "LABEL-MC-001"
        inventory_service_data.meat_cut.refresh_from_db()
        assert inventory_service_data.meat_cut.label_id == "LABEL-MC-001"

        with pytest.raises(TypeError):
            assign_label_to_inventory_item(inventory_service_data.user, "LABEL-USER-001")

    def test_get_inventory_by_location(self, inventory_service_data):
        inventory = get_inventory_by_location(inventory_service_data.storage_location_1)

        assert inventory_service_data.carcass in inventory["carcasses"]
        assert inventory_service_data.meat_cut in inventory["meat_cuts"]
        assert inventory_service_data.offal in inventory["offal"]
        assert inventory_service_data.by_product in inventory["byproducts"]

        empty_location = StorageLocation.objects.create(name="Empty Room", location_type="dry_storage")
        empty_inventory = get_inventory_by_location(empty_location)
        assert empty_inventory["carcasses"].count() == 0
        assert empty_inventory["meat_cuts"].count() == 0
        assert empty_inventory["offal"].count() == 0
        assert empty_inventory["byproducts"].count() == 0

    def test_get_inventory_for_animal(self, inventory_service_data):
        inventory = get_inventory_for_animal(inventory_service_data.animal)

        assert inventory["carcass"] == inventory_service_data.carcass
        assert inventory_service_data.meat_cut in inventory["meat_cuts"]
        assert inventory_service_data.offal in inventory["offal"]
        assert inventory_service_data.by_product in inventory["byproducts"]

        animal_no_inventory = Animal.objects.create(
            slaughter_order=inventory_service_data.order,
            animal_type="sheep",
        )
        inventory_no_items = get_inventory_for_animal(animal_no_inventory)
        assert inventory_no_items["carcass"] is None
        assert inventory_no_items["meat_cuts"].count() == 0
        assert inventory_no_items["offal"].count() == 0
        assert inventory_no_items["byproducts"].count() == 0
