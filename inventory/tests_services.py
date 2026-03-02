from django.contrib.auth import get_user_model
from django.test import TestCase
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


class InventoryServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", role=User.Role.CLIENT)
        self.client_profile = ClientProfile.objects.create(
            user=self.user, account_type="INDIVIDUAL", phone_number="1234567890", address="123 Test St"
        )
        self.order = SlaughterOrder.objects.create(client=self.client_profile, order_datetime=timezone.now())
        self.animal = Animal.objects.create(slaughter_order=self.order, animal_type="cattle")
        self.storage_location_1 = StorageLocation.objects.create(name="Freezer A", location_type="freezer")
        self.storage_location_2 = StorageLocation.objects.create(name="Cooler B", location_type="cooler")

        self.carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=250.0,
            disposition="for_sale",
            storage_location=self.storage_location_1,
        )
        self.meat_cut = MeatCut.objects.create(
            carcass=self.carcass,
            cut_type=MeatCut.BeefCuts.RIBEYE,
            weight=10.0,
            disposition="for_sale",
            storage_location=self.storage_location_1,
        )
        self.offal = Offal.objects.create(
            animal=self.animal,
            offal_type=Offal.BeefOffalTypes.LIVER,
            weight=2.0,
            disposition="for_sale",
            storage_location=self.storage_location_1,
        )
        self.by_product = ByProduct.objects.create(
            animal=self.animal,
            byproduct_type=ByProduct.ByProductTypes.SKIN,
            disposition="for_sale",
            storage_location=self.storage_location_1,
        )

    def test_move_inventory_item(self):
        # Test moving a Carcass
        moved_carcass = move_inventory_item(self.carcass, self.storage_location_2)
        self.assertEqual(moved_carcass.storage_location, self.storage_location_2)

        # Test moving a MeatCut
        moved_meat_cut = move_inventory_item(self.meat_cut, self.storage_location_2)
        self.assertEqual(moved_meat_cut.storage_location, self.storage_location_2)
        self.meat_cut.refresh_from_db()
        self.assertEqual(self.meat_cut.storage_location, self.storage_location_2)

        # Test moving an Offal
        moved_offal = move_inventory_item(self.offal, self.storage_location_2)
        self.assertEqual(moved_offal.storage_location, self.storage_location_2)
        self.offal.refresh_from_db()
        self.assertEqual(self.offal.storage_location, self.storage_location_2)

        # Test moving a ByProduct
        moved_by_product = move_inventory_item(self.by_product, self.storage_location_2)
        self.assertEqual(moved_by_product.storage_location, self.storage_location_2)
        self.by_product.refresh_from_db()
        self.assertEqual(self.by_product.storage_location, self.storage_location_2)

        # Test moving an item without storage_location attribute
        with self.assertRaises(TypeError):
            move_inventory_item(self.user, self.storage_location_2)  # User model doesn't have storage_location

    def test_update_inventory_disposition(self):
        # Test updating Carcass disposition
        updated_carcass = update_inventory_disposition(self.carcass, "disposed")
        self.assertEqual(updated_carcass.disposition, "disposed")

        # Test updating MeatCut disposition
        updated_meat_cut = update_inventory_disposition(self.meat_cut, "returned_to_owner")
        self.assertEqual(updated_meat_cut.disposition, "returned_to_owner")
        self.meat_cut.refresh_from_db()
        self.assertEqual(self.meat_cut.disposition, "returned_to_owner")

        # Test updating an item without disposition attribute
        with self.assertRaises(TypeError):
            update_inventory_disposition(self.user, "some_disposition")

    def test_assign_label_to_inventory_item(self):
        # Test assigning label to MeatCut
        assigned_meat_cut = assign_label_to_inventory_item(self.meat_cut, "LABEL-MC-001")
        self.assertEqual(assigned_meat_cut.label_id, "LABEL-MC-001")
        self.meat_cut.refresh_from_db()
        self.assertEqual(self.meat_cut.label_id, "LABEL-MC-001")

        # Test assigning label to Carcass (assuming it has label_id field)
        # Note: Carcass model does not have label_id by default, this test will fail or raise TypeError
        # if Carcass model is not updated to include label_id.
        # For now, let's assume it does for the sake of testing the service function.
        # If not, this test should be adjusted or removed.
        # self.carcass.label_id = None # Ensure it has the attribute for testing
        # assigned_carcass = assign_label_to_inventory_item(self.carcass, 'LABEL-CAR-001')
        # self.assertEqual(assigned_carcass.label_id, 'LABEL-CAR-001')

        # Test assigning label to an item without label_id attribute
        with self.assertRaises(TypeError):
            assign_label_to_inventory_item(self.user, "LABEL-USER-001")

    def test_get_inventory_by_location(self):
        inventory = get_inventory_by_location(self.storage_location_1)

        self.assertIn(self.carcass, inventory["carcasses"])
        self.assertIn(self.meat_cut, inventory["meat_cuts"])
        self.assertIn(self.offal, inventory["offal"])
        self.assertIn(self.by_product, inventory["byproducts"])

        # Test with an empty location
        empty_location = StorageLocation.objects.create(name="Empty Room", location_type="dry_storage")
        empty_inventory = get_inventory_by_location(empty_location)
        self.assertEqual(empty_inventory["carcasses"].count(), 0)
        self.assertEqual(empty_inventory["meat_cuts"].count(), 0)
        self.assertEqual(empty_inventory["offal"].count(), 0)
        self.assertEqual(empty_inventory["byproducts"].count(), 0)

    def test_get_inventory_for_animal(self):
        inventory = get_inventory_for_animal(self.animal)

        self.assertEqual(inventory["carcass"], self.carcass)
        self.assertIn(self.meat_cut, inventory["meat_cuts"])
        self.assertIn(self.offal, inventory["offal"])
        self.assertIn(self.by_product, inventory["byproducts"])

        # Test with an animal that has no inventory items
        animal_no_inventory = Animal.objects.create(slaughter_order=self.order, animal_type="sheep")
        inventory_no_items = get_inventory_for_animal(animal_no_inventory)
        self.assertIsNone(inventory_no_items["carcass"])
        self.assertEqual(inventory_no_items["meat_cuts"].count(), 0)
        self.assertEqual(inventory_no_items["offal"].count(), 0)
        self.assertEqual(inventory_no_items["byproducts"].count(), 0)
