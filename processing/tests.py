from django.test import TestCase
from django.contrib.auth import get_user_model
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from .models import Animal, WeightLog, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails, BeefDetails
from datetime import date
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
import datetime # Import datetime module

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

    def test_auto_generate_identification_tag(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='sheep'
        )
        self.assertIsNotNone(animal.identification_tag)
        self.assertTrue(animal.identification_tag.startswith('SHEEP-'))
        # Test uniqueness by creating another and checking prefix
        animal2 = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='sheep'
        )
        self.assertNotEqual(animal.identification_tag, animal2.identification_tag)

    def test_received_date_editable(self):
        past_datetime = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 0, 0))
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            received_date=past_datetime
        )
        self.assertEqual(animal.received_date, past_datetime)

    def test_animal_picture_field(self):
        # Create a dummy image file
        image_content = b'GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        image_file = SimpleUploadedFile("test_image.gif", image_content, content_type="image/gif")

        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            picture=image_file
        )
        self.assertIsNotNone(animal.picture)
        self.assertTrue(animal.picture.name.startswith('animal_pictures/test_image'))
        self.assertTrue(animal.picture.name.endswith('.gif'))

    def test_animal_fsm_transitions(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-002'
        )
        self.assertEqual(animal.status, 'received')

        animal.perform_slaughter()
        self.assertEqual(animal.status, 'slaughtered')
        self.assertIsNotNone(animal.slaughter_date)

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
            horn_status='Polled',
            liver_status=1.0,
            head_status=0.5,
            bowels_status=0.0
        )
        self.assertEqual(cattle_details.animal, animal)
        self.assertEqual(animal.cattle_details, cattle_details)
        self.assertEqual(cattle_details.liver_status, 1.0)
        self.assertEqual(cattle_details.head_status, 0.5)
        self.assertEqual(cattle_details.bowels_status, 0.0)

    def test_create_new_animal_details_types(self):
        animal_calf = Animal.objects.create(slaughter_order=self.order, animal_type='calf')
        CalfDetails.objects.create(animal=animal_calf)
        self.assertIsNotNone(animal_calf.calf_details)

        animal_heifer = Animal.objects.create(slaughter_order=self.order, animal_type='heifer')
        HeiferDetails.objects.create(animal=animal_heifer)
        self.assertIsNotNone(animal_heifer.heifer_details)

        animal_beef = Animal.objects.create(slaughter_order=self.order, animal_type='beef')
        BeefDetails.objects.create(animal=animal_beef)
        self.assertIsNotNone(animal_beef.beef_details)

        animal_goat = Animal.objects.create(slaughter_order=self.order, animal_type='goat')
        GoatDetails.objects.create(animal=animal_goat)
        self.assertIsNotNone(animal_goat.goat_details)

        animal_lamb = Animal.objects.create(slaughter_order=self.order, animal_type='lamb')
        LambDetails.objects.create(animal=animal_lamb)
        self.assertIsNotNone(animal_lamb.lamb_details)

        animal_oglak = Animal.objects.create(slaughter_order=self.order, animal_type='oglak')
        OglakDetails.objects.create(animal=animal_oglak)
        self.assertIsNotNone(animal_oglak.oglak_details)

    def test_animal_leather_weight_kg(self):
        animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            leather_weight_kg=150.75
        )
        self.assertEqual(animal.leather_weight_kg, 150.75)

        animal_sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='sheep',
            leather_weight_kg=10.20
        )
        self.assertEqual(animal_sheep.leather_weight_kg, 10.20)

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

    def test_weight_log_constraints(self):
        # Test case where neither animal nor slaughter_order is provided
        with self.assertRaises(Exception):
            WeightLog.objects.create(
                weight=10.0,
                weight_type='Test'
            )

        # Test case where group_quantity/group_total_weight are provided but not is_group_weight
        with self.assertRaises(Exception):
            WeightLog.objects.create(
                animal=Animal.objects.create(slaughter_order=self.order, animal_type='sheep'),
                weight=10.0,
                weight_type='Test',
                group_quantity=5
            )

        # Test case where is_group_weight is True but group_quantity/group_total_weight are missing
        with self.assertRaises(Exception):
            WeightLog.objects.create(
                slaughter_order=self.order,
                weight=10.0,
                weight_type='Test',
                is_group_weight=True
            )
