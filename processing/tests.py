from django.test import TestCase
from django.contrib.auth import get_user_model
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from .models import Animal, WeightLog, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails
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
            order_datetime=timezone.now(),
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
            identification_tag='TEST-CATTLE-001',  # Set a specific identification tag
            picture=image_file
        )
        self.assertIsNotNone(animal.picture)
        # Check that the filename uses the upload path function correctly
        self.assertTrue(animal.picture.name.startswith('animal_pictures/TEST-CATTLE-001_photo'))
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
            order_datetime=timezone.now(),
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

    def test_batch_weight_log_form_validation(self):
        """Test BatchWeightLogForm validation"""
        from .forms import BatchWeightLogForm
        
        # Create animals and mark them as slaughtered
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal1.perform_slaughter()
        animal2.perform_slaughter()
        animal1.save()
        animal2.save()
        
        # Test valid form data
        valid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 300.0,
            'animal_count': 2
        }
        form = BatchWeightLogForm(data=valid_data)
        self.assertTrue(form.is_valid())
        
        # Test invalid - too many animals
        invalid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 300.0,
            'animal_count': 5  # More than available slaughtered animals
        }
        form = BatchWeightLogForm(data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Cannot log weight for 5 animals', str(form.errors))
        
        # Test invalid - average weight too low
        invalid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 1.0,  # Very low total weight
            'animal_count': 2
        }
        form = BatchWeightLogForm(data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Average weight per animal seems unusually low', str(form.errors))

    def test_batch_weight_log_form_multiple_batches_validation(self):
        """Test that BatchWeightLogForm properly handles cumulative validation across multiple batches"""
        from .forms import BatchWeightLogForm
        from .models import WeightLog
        
        # Create and mark animals as slaughtered (3 total)
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal1.perform_slaughter()
        animal2.perform_slaughter()
        animal3.perform_slaughter()
        animal1.save()
        animal2.save()
        animal3.save()
        
        # Create existing weight log for 2 animals
        WeightLog.objects.create(
            slaughter_order=self.order,
            weight=150.0,
            weight_type='live_weight Group',
            is_group_weight=True,
            group_quantity=2,
            group_total_weight=300.0
        )
        
        # Try to create another batch for remaining animals (1 animal) - should succeed
        valid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',  # This will become 'live_weight Group'
            'total_weight': 155.0,
            'animal_count': 1  # Only 1 animal remains available (3 total - 2 already weighed)
        }
        form = BatchWeightLogForm(data=valid_data)
        self.assertTrue(form.is_valid(), f"Form should be valid but got errors: {form.errors}")
        
        # Try to create another batch for 2 animals when only 1 remains - should fail
        invalid_cumulative_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 310.0,
            'animal_count': 2  # Would exceed cumulative limit (2 already + 2 new = 4, but only 3 total)
        }
        form = BatchWeightLogForm(data=invalid_cumulative_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Only 1 animals remain available', str(form.errors))
        self.assertIn('2 already weighed out of 3 total', str(form.errors))
        
        # Try to log more animals than exist in the order - should fail
        invalid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 160.0,
            'animal_count': 10  # More than the 3 total animals in the order
        }
        form = BatchWeightLogForm(data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Cannot log weight for 10 animals', str(form.errors))
        self.assertIn('Only 3 animals are available for weighing', str(form.errors))

    def test_batch_weight_log_cumulative_validation(self):
        """Test that BatchWeightLogForm prevents cumulative animal count from exceeding available animals"""
        from .forms import BatchWeightLogForm
        from .models import WeightLog
        
        # Create and mark animals as slaughtered (4 total)
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal4 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        
        # Mark all animals as slaughtered
        for animal in [animal1, animal2, animal3, animal4]:
            animal.perform_slaughter()
            animal.save()
        
        # Total slaughtered animals is now 4
        
        # Create first batch weight log for 3 animals
        WeightLog.objects.create(
            slaughter_order=self.order,
            weight=150.0,
            weight_type='live_weight Group',
            is_group_weight=True,
            group_quantity=3,
            group_total_weight=450.0
        )
        
        # Try to create another batch for 2 animals (would exceed total of 4)
        invalid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',  # This will become 'live_weight Group'
            'total_weight': 310.0,
            'animal_count': 2  # 3 + 2 = 5, but only 4 available
        }
        form = BatchWeightLogForm(data=invalid_data)
        self.assertFalse(form.is_valid())
        self.assertIn('Only 1 animals remain available', str(form.errors))
        self.assertIn('3 already weighed out of 4 total', str(form.errors))
        
        # Try valid batch with exact remaining animals (1 animal)
        valid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 155.0,
            'animal_count': 1  # 3 + 1 = 4, exactly the available amount
        }
        form = BatchWeightLogForm(data=valid_data)
        self.assertTrue(form.is_valid(), f"Form should be valid but got errors: {form.errors}")
        
        # After adding the valid batch, try to add more - should fail
        WeightLog.objects.create(
            slaughter_order=self.order,
            weight=155.0,
            weight_type='live_weight Group',
            is_group_weight=True,
            group_quantity=1,
            group_total_weight=155.0
        )
        
        # Now try to add any more animals - should fail
        invalid_data_final = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': 160.0,
            'animal_count': 1  # All 4 animals already weighed
        }
        form = BatchWeightLogForm(data=invalid_data_final)
        self.assertFalse(form.is_valid())
        self.assertIn('Only 0 animals remain available', str(form.errors))
        self.assertIn('4 already weighed out of 4 total', str(form.errors))

    def test_batch_weight_log_decimal_handling(self):
        """Test BatchWeightLogForm handles Decimal inputs properly"""
        from .forms import BatchWeightLogForm
        from decimal import Decimal
        
        # Create animals and mark them as slaughtered
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal1.perform_slaughter()
        animal2.perform_slaughter()
        animal1.save()
        animal2.save()
        
        # Test form with Decimal values
        valid_data = {
            'order_id': str(self.order.id),
            'weight_type': 'live_weight',
            'total_weight': Decimal('300.50'),  # Using Decimal
            'animal_count': 2
        }
        form = BatchWeightLogForm(data=valid_data)
        self.assertTrue(form.is_valid(), f"Form should handle Decimal inputs but got errors: {form.errors}")
        
        # Test very precise decimal values
        precise_data = {
            'order_id': str(self.order.id),
            'weight_type': 'hot_carcass_weight',
            'total_weight': Decimal('275.75'),  # Using precise Decimal
            'animal_count': 2
        }
        form = BatchWeightLogForm(data=precise_data)
        self.assertTrue(form.is_valid(), f"Form should handle precise Decimal inputs but got errors: {form.errors}")
        
        # Ensure average calculation works with Decimals
        cleaned_data = form.clean()
        expected_average = Decimal('275.75') / 2
        actual_average = cleaned_data['total_weight'] / cleaned_data['animal_count']
        self.assertEqual(actual_average, expected_average)
