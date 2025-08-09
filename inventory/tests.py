from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.core.exceptions import ValidationError
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal
from .models import Carcass, MeatCut, Offal, ByProduct
from datetime import date

User = get_user_model()

class InventoryModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123',
            role=User.Role.CLIENT
        )
        self.client_profile = ClientProfile.objects.create(
            user=self.user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number='1234567890',
            address='123 Test St'
        )
        self.service_package = ServicePackage.objects.create(
            name='Full Processing',
            includes_disassembly=True,
            includes_delivery=True
        )
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_date=date.today(),
            service_package=self.service_package
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-001'
        )

    def test_create_carcass(self):
        carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=250.75,
            disposition='for_sale'
        )
        self.assertEqual(carcass.animal, self.animal)
        self.assertEqual(carcass.hot_carcass_weight, 250.75)
        self.assertEqual(carcass.status, 'chilling')
        self.assertEqual(str(carcass), f"Carcass of {self.animal.identification_tag} - 250.75 kg (Hot)")

    def test_create_meat_cut(self):
        carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=250.75,
            disposition='returned_to_owner'
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass,
            cut_type=MeatCut.BeefCuts.RIBEYE,
            weight=10.5,
            disposition='returned_to_owner'
        )
        self.assertEqual(meat_cut.carcass, carcass)
        self.assertEqual(meat_cut.cut_type, 'RIBEYE')
        self.assertEqual(str(meat_cut), f"{meat_cut.cut_type} from {carcass.animal.identification_tag} - {meat_cut.weight} kg")

    def test_create_offal(self):
        offal = Offal.objects.create(
            animal=self.animal,
            offal_type=Offal.BeefOffalTypes.LIVER,
            weight=5.2,
            disposition='for_sale'
        )
        self.assertEqual(offal.animal, self.animal)
        self.assertEqual(offal.offal_type, 'LIVER')
        self.assertEqual(str(offal), f"{offal.offal_type} from {self.animal.identification_tag} - {offal.weight} kg")

    def test_create_by_product(self):
        by_product = ByProduct.objects.create(
            animal=self.animal,
            byproduct_type=ByProduct.ByProductTypes.SKIN,
            disposition='disposed'
        )
        self.assertEqual(by_product.animal, self.animal)
        self.assertEqual(by_product.byproduct_type, 'SKIN')
        self.assertEqual(str(by_product), f"{by_product.byproduct_type} from {self.animal.identification_tag}")

    def test_one_to_one_carcass_animal_constraint(self):
        Carcass.objects.create(animal=self.animal, hot_carcass_weight=200, disposition='for_sale')
        with self.assertRaises(IntegrityError):
            Carcass.objects.create(animal=self.animal, hot_carcass_weight=210, disposition='for_sale')

    def test_meat_cut_cascade_delete(self):
        carcass = Carcass.objects.create(animal=self.animal, hot_carcass_weight=200, disposition='for_sale')
        MeatCut.objects.create(carcass=carcass, cut_type=MeatCut.BeefCuts.BRISKET, weight=15, disposition='for_sale')
        self.assertEqual(MeatCut.objects.count(), 1)
        carcass.delete()
        self.assertEqual(MeatCut.objects.count(), 0)

    def test_animal_cascade_delete(self):
        Offal.objects.create(animal=self.animal, offal_type=Offal.BeefOffalTypes.HEART, weight=2, disposition='for_sale')
        ByProduct.objects.create(animal=self.animal, byproduct_type=ByProduct.ByProductTypes.FEET, disposition='disposed')
        self.assertEqual(Offal.objects.count(), 1)
        self.assertEqual(ByProduct.objects.count(), 1)
        self.animal.delete()
        self.assertEqual(Offal.objects.count(), 0)
        self.assertEqual(ByProduct.objects.count(), 0)

    def test_reverse_relationships(self):
        carcass = Carcass.objects.create(animal=self.animal, hot_carcass_weight=200, disposition='for_sale')
        mc1 = MeatCut.objects.create(carcass=carcass, cut_type=MeatCut.BeefCuts.CHUCK, weight=1.5, disposition='for_sale')
        mc2 = MeatCut.objects.create(carcass=carcass, cut_type=MeatCut.BeefCuts.SHANK, weight=2.5, disposition='for_sale')
        offal = Offal.objects.create(animal=self.animal, offal_type=Offal.BeefOffalTypes.KIDNEY_FAT, weight=0.5, disposition='disposed')
        by_product = ByProduct.objects.create(animal=self.animal, byproduct_type=ByProduct.ByProductTypes.HEAD, weight=20, disposition='disposed')

        self.assertEqual(self.animal.carcass, carcass)
        self.assertEqual(self.animal.offals.count(), 1)
        self.assertEqual(self.animal.by_products.first(), by_product)
        self.assertEqual(carcass.meat_cuts.count(), 2)
        self.assertIn(mc1, carcass.meat_cuts.all())

    def test_nullable_label_id(self):
        carcass = Carcass.objects.create(animal=self.animal, hot_carcass_weight=200, disposition='for_sale')
        meat_cut = MeatCut.objects.create(
            carcass=carcass,
            cut_type=MeatCut.BeefCuts.FLANK,
            weight=3.0,
            disposition='for_sale',
            label_id=None
        )
        self.assertIsNone(meat_cut.label_id)