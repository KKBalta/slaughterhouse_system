from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.utils import timezone

from processing.models import Animal
from reception.models import ServicePackage, SlaughterOrder
from users.models import ClientProfile

from .models import ByProduct, Carcass, MeatCut, Offal

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_test_data():
    user = User.objects.create_user(username="testuser", password="password123", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1234567890",
        address="123 Test St",
    )
    service_package = ServicePackage.objects.create(
        name="Full Processing", includes_disassembly=True, includes_delivery=True
    )
    order = SlaughterOrder.objects.create(
        client=client_profile,
        order_datetime=timezone.now(),
        service_package=service_package,
    )
    animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="CATTLE-001")

    return SimpleNamespace(
        user=user,
        client_profile=client_profile,
        service_package=service_package,
        order=order,
        animal=animal,
    )


class TestInventoryModel:
    def test_create_carcass(self, inventory_test_data):
        carcass = Carcass.objects.create(
            animal=inventory_test_data.animal, hot_carcass_weight=250.75, disposition="for_sale"
        )
        assert carcass.animal == inventory_test_data.animal
        assert carcass.hot_carcass_weight == 250.75
        assert carcass.status == "chilling"
        assert str(carcass) == f"Carcass of {inventory_test_data.animal.identification_tag} - 250.75 kg (Hot)"

    def test_create_meat_cut(self, inventory_test_data):
        carcass = Carcass.objects.create(
            animal=inventory_test_data.animal, hot_carcass_weight=250.75, disposition="returned_to_owner"
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass, cut_type=MeatCut.BeefCuts.RIBEYE, weight=10.5, disposition="returned_to_owner"
        )
        assert meat_cut.carcass == carcass
        assert meat_cut.cut_type == "RIBEYE"
        assert str(meat_cut) == f"{meat_cut.cut_type} from {carcass.animal.identification_tag} - {meat_cut.weight} kg"

    def test_create_offal(self, inventory_test_data):
        offal = Offal.objects.create(
            animal=inventory_test_data.animal, offal_type=Offal.BeefOffalTypes.LIVER, weight=5.2, disposition="for_sale"
        )
        assert offal.animal == inventory_test_data.animal
        assert offal.offal_type == "LIVER"
        assert (
            str(offal) == f"{offal.offal_type} from {inventory_test_data.animal.identification_tag} - {offal.weight} kg"
        )

    def test_create_by_product(self, inventory_test_data):
        by_product = ByProduct.objects.create(
            animal=inventory_test_data.animal, byproduct_type=ByProduct.ByProductTypes.SKIN, disposition="disposed"
        )
        assert by_product.animal == inventory_test_data.animal
        assert by_product.byproduct_type == "SKIN"
        assert str(by_product) == f"{by_product.byproduct_type} from {inventory_test_data.animal.identification_tag}"

    def test_one_to_one_carcass_animal_constraint(self, inventory_test_data):
        Carcass.objects.create(animal=inventory_test_data.animal, hot_carcass_weight=200, disposition="for_sale")
        with pytest.raises(IntegrityError):
            Carcass.objects.create(animal=inventory_test_data.animal, hot_carcass_weight=210, disposition="for_sale")

    def test_meat_cut_cascade_delete(self, inventory_test_data):
        carcass = Carcass.objects.create(
            animal=inventory_test_data.animal, hot_carcass_weight=200, disposition="for_sale"
        )
        MeatCut.objects.create(carcass=carcass, cut_type=MeatCut.BeefCuts.BRISKET, weight=15, disposition="for_sale")
        assert MeatCut.objects.count() == 1
        carcass.delete()
        assert MeatCut.objects.count() == 0

    def test_animal_cascade_delete(self, inventory_test_data):
        Offal.objects.create(
            animal=inventory_test_data.animal, offal_type=Offal.BeefOffalTypes.HEART, weight=2, disposition="for_sale"
        )
        ByProduct.objects.create(
            animal=inventory_test_data.animal, byproduct_type=ByProduct.ByProductTypes.FEET, disposition="disposed"
        )
        assert Offal.objects.count() == 1
        assert ByProduct.objects.count() == 1
        inventory_test_data.animal.delete()
        assert Offal.objects.count() == 0
        assert ByProduct.objects.count() == 0

    def test_reverse_relationships(self, inventory_test_data):
        carcass = Carcass.objects.create(
            animal=inventory_test_data.animal, hot_carcass_weight=200, disposition="for_sale"
        )
        mc1 = MeatCut.objects.create(
            carcass=carcass, cut_type=MeatCut.BeefCuts.CHUCK, weight=1.5, disposition="for_sale"
        )
        MeatCut.objects.create(carcass=carcass, cut_type=MeatCut.BeefCuts.SHANK, weight=2.5, disposition="for_sale")
        Offal.objects.create(
            animal=inventory_test_data.animal,
            offal_type=Offal.BeefOffalTypes.KIDNEY_FAT,
            weight=0.5,
            disposition="disposed",
        )
        by_product = ByProduct.objects.create(
            animal=inventory_test_data.animal,
            byproduct_type=ByProduct.ByProductTypes.HEAD,
            weight=20,
            disposition="disposed",
        )

        assert inventory_test_data.animal.carcass == carcass
        assert inventory_test_data.animal.offals.count() == 1
        assert inventory_test_data.animal.by_products.first() == by_product
        assert carcass.meat_cuts.count() == 2
        assert mc1 in carcass.meat_cuts.all()

    def test_nullable_label_id(self, inventory_test_data):
        carcass = Carcass.objects.create(
            animal=inventory_test_data.animal, hot_carcass_weight=200, disposition="for_sale"
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass, cut_type=MeatCut.BeefCuts.FLANK, weight=3.0, disposition="for_sale", label_id=None
        )
        assert meat_cut.label_id is None
