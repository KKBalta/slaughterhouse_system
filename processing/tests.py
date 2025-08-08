from django.test import TestCase
from django.contrib.auth import get_user_model
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from .models import Animal, WeightLog, CattleDetails
from datetime import date

User = get_user_model()

class ProcessingModelTest(TestCase):
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
        self.service_package_full = ServicePackage.objects.create(
            name='Full Processing',
            includes_disassembly=True,
            includes_delivery=True
        )
        self.service_package_simple = ServicePackage.objects.create(
            name='Slaughter Only',
            includes_disassembly=False,
            includes_delivery=False
        )
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_date=date.today(),
            service_package=self.service_package_full
        )

    def test_create_animal(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-001'
        )
        self.assertEqual(animal.slaughter_order, self.order)
        self.assertEqual(animal.animal_type, 'cattle')
        self.assertEqual(animal.identification_tag, 'CATTLE-001')
        self.assertEqual(animal.status, 'received')

    def test_animal_fsm_transitions(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-002'
        )
        self.assertEqual(animal.status, 'received')

        animal.perform_slaughter()
        self.assertEqual(animal.status, 'slaughtered')

        animal.prepare_carcass()
        self.assertEqual(animal.status, 'carcass_ready')

        # Test conditional transition
        animal.perform_disassembly()
        self.assertEqual(animal.status, 'disassembled')

        animal.perform_packaging()
        self.assertEqual(animal.status, 'packaged')

        animal.deliver_product()
        self.assertEqual(animal.status, 'delivered')

    def test_animal_fsm_conditional_transition_fail(self):
        simple_order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_date=date.today(),
            service_package=self.service_package_simple
        )
        animal = Animal.objects.create(
            slaughter_order=simple_order,
            animal_type='sheep',
            identification_tag='SHEEP-001'
        )
        animal.perform_slaughter()
        animal.prepare_carcass()

        with self.assertRaises(Exception): # Should fail as disassembly is not included
            animal.perform_disassembly()

    def test_create_animal_details(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-003'
        )
        cattle_details = CattleDetails.objects.create(
            animal=animal,
            breed='Angus',
            horn_status='Polled'
        )
        self.assertEqual(cattle_details.animal, animal)
        self.assertEqual(animal.cattle_details, cattle_details)

    def test_create_individual_weight_log(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='goat',
            identification_tag='GOAT-001'
        )
        weight_log = WeightLog.objects.create(
            animal=animal,
            weight=50.5,
            weight_type='Live'
        )
        self.assertEqual(weight_log.animal, animal)
        self.assertEqual(weight_log.weight, 50.5)

    def test_create_group_weight_log(self):
        weight_log = WeightLog.objects.create(
            slaughter_order=self.order,
            weight=45.0,
            weight_type='Live Group',
            is_group_weight=True,
            group_quantity=10,
            group_total_weight=450.0
        )
        self.assertEqual(weight_log.slaughter_order, self.order)
        self.assertTrue(weight_log.is_group_weight)
        self.assertEqual(weight_log.group_quantity, 10)