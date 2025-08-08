
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal
from .models import Carcass, MeatCut, Offal, ByProduct, Label
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
            weight=250.75,
            disposition='for_sale'
        )
        self.assertEqual(carcass.animal, self.animal)
        self.assertEqual(carcass.weight, 250.75)
        self.assertEqual(carcass.status, 'chilling')
        self.assertEqual(str(carcass), f"Carcass of {self.animal.identification_tag} - 250.75 kg")

    def test_create_meat_cut(self):
        carcass = Carcass.objects.create(
            animal=self.animal,
            weight=250.75,
            disposition='returned_to_owner'
        )
        meat_cut = MeatCut.objects.create(
            carcass=carcass,
            cut_type='Ribeye',
            weight=10.5,
            disposition='returned_to_owner'
        )
        self.assertEqual(meat_cut.carcass, carcass)
        self.assertEqual(meat_cut.cut_type, 'Ribeye')
        self.assertEqual(str(meat_cut), f"{meat_cut.cut_type} from {carcass.animal.identification_tag} - {meat_cut.weight} kg")

    def test_create_offal(self):
        offal = Offal.objects.create(
            animal=self.animal,
            offal_type='Liver',
            weight=5.2,
            disposition='for_sale'
        )
        self.assertEqual(offal.animal, self.animal)
        self.assertEqual(offal.offal_type, 'Liver')
        self.assertEqual(str(offal), f"{offal.offal_type} from {self.animal.identification_tag} - {offal.weight} kg")

    def test_create_by_product(self):
        by_product = ByProduct.objects.create(
            animal=self.animal,
            byproduct_type='Hide',
            disposition='disposed'
        )
        self.assertEqual(by_product.animal, self.animal)
        self.assertEqual(by_product.byproduct_type, 'Hide')
        self.assertEqual(str(by_product), f"{by_product.byproduct_type} from {self.animal.identification_tag}")

    def test_create_label(self):
        carcass = Carcass.objects.create(
            animal=self.animal,
            weight=250.75,
            disposition='for_sale'
        )
        label = Label.objects.create(
            label_code='QR-12345',
            item_type='carcass',
            item_id=carcass.id,
            printed_by=self.user
        )
        self.assertEqual(label.label_code, 'QR-12345')
        self.assertEqual(label.item_id, carcass.id)
        self.assertEqual(label.printed_by, self.user)
        self.assertEqual(str(label), f"Label {label.label_code} for {label.item_type} ID: {label.item_id}")

    def test_one_to_one_carcass_animal_constraint(self):
        Carcass.objects.create(animal=self.animal, weight=200, disposition='for_sale')
        with self.assertRaises(IntegrityError):
            Carcass.objects.create(animal=self.animal, weight=210, disposition='for_sale')

    def test_meat_cut_cascade_delete(self):
        carcass = Carcass.objects.create(animal=self.animal, weight=200, disposition='for_sale')
        MeatCut.objects.create(carcass=carcass, cut_type='Brisket', weight=15, disposition='for_sale')
        self.assertEqual(MeatCut.objects.count(), 1)
        carcass.delete()
        self.assertEqual(MeatCut.objects.count(), 0)

    def test_animal_cascade_delete(self):
        Offal.objects.create(animal=self.animal, offal_type='Heart', weight=2, disposition='for_sale')
        ByProduct.objects.create(animal=self.animal, byproduct_type='Hooves', disposition='disposed')
        self.assertEqual(Offal.objects.count(), 1)
        self.assertEqual(ByProduct.objects.count(), 1)
        self.animal.delete()
        self.assertEqual(Offal.objects.count(), 0)
        self.assertEqual(ByProduct.objects.count(), 0)

    def test_label_code_uniqueness(self):
        carcass = Carcass.objects.create(animal=self.animal, weight=200, disposition='for_sale')
        Label.objects.create(label_code='UNIQUE-CODE', item_type='carcass', item_id=carcass.id)
        with self.assertRaises(IntegrityError):
            Label.objects.create(label_code='UNIQUE-CODE', item_type='carcass', item_id=carcass.id)
