from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import ServicePackage
from users.models import ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal, CattleDetails, SheepDetails
from reception.services import (
    create_slaughter_order, update_slaughter_order, cancel_slaughter_order,
    update_order_status_from_animals, bill_order,
    add_animal_to_order, remove_animal_from_order, create_batch_animals,
    generate_order_number
)
from datetime import date, datetime
from django.utils import timezone
from django.core.exceptions import ValidationError

User = get_user_model()

class ReceptionServiceTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testclient', role=User.Role.CLIENT)
        self.client_profile = ClientProfile.objects.create(
            user=self.user,
            account_type='INDIVIDUAL',
            phone_number='1234567890',
            address='123 Test St'
        )
        self.service_package = ServicePackage.objects.create(
            name='Full Service',
            includes_disassembly=True,
            includes_delivery=True
        )
        self.service_package_simple = ServicePackage.objects.create(name='Simple Service')

    def test_create_slaughter_order_service(self):
        animals_data = [
            {'animal_type': 'cattle', 'identification_tag': 'CATTLE-001', 'details_data': {'breed': 'Angus'}},
            {'animal_type': 'sheep', 'identification_tag': 'SHEEP-001', 'details_data': {'breed': 'Merino'}}
        ]
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=animals_data
        )
        self.assertEqual(SlaughterOrder.objects.count(), 1)
        self.assertEqual(order.animals.count(), 2)

    def test_update_slaughter_order_service(self):
        order = create_slaughter_order(client_id=self.client_profile.id, service_package_id=self.service_package.id, order_datetime=timezone.now(), animals_data=[])
        self.assertEqual(order.destination, None)

        updated_order = update_slaughter_order(order=order, destination='New Market', service_package=self.service_package_simple)
        self.assertEqual(updated_order.destination, 'New Market')
        self.assertEqual(updated_order.service_package, self.service_package_simple)

        # Test that update fails if order is not pending
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with self.assertRaises(ValidationError):
            update_slaughter_order(order=order, destination='Another Market')

    def test_cancel_slaughter_order_service(self):
        order = create_slaughter_order(client_id=self.client_profile.id, service_package_id=self.service_package.id, order_datetime=timezone.now(), animals_data=[{'animal_type': 'cattle'}])
        self.assertEqual(order.status, SlaughterOrder.Status.PENDING)
        
        cancelled_order = cancel_slaughter_order(order=order)
        self.assertEqual(cancelled_order.status, SlaughterOrder.Status.CANCELLED)
        self.assertEqual(cancelled_order.animals.first().status, 'disposed')

        # Test that cancellation fails if order is not pending
        order.status = SlaughterOrder.Status.COMPLETED
        order.save()
        with self.assertRaises(ValidationError):
            cancel_slaughter_order(order=order)

    def test_update_order_status_from_animals_service(self):
        order = create_slaughter_order(
            client_id=self.client_profile.id, 
            service_package_id=self.service_package.id, 
            order_datetime=timezone.now(),
            animals_data=[
                {'animal_type': 'cattle'}, {'animal_type': 'sheep'}
            ]
        )
        
        # Test IN_PROGRESS status
        animal_1 = order.animals.all()[0]
        animal_1.perform_slaughter()
        animal_1.save()
        
        update_order_status_from_animals(order=order)
        order.refresh_from_db()
        self.assertEqual(order.status, SlaughterOrder.Status.IN_PROGRESS)

        # Test COMPLETED status
        for animal in order.animals.all():
            if animal.status == 'received':
                animal.perform_slaughter()
            animal.prepare_carcass()
            # Our test service package includes disassembly and delivery
            animal.perform_disassembly()
            animal.perform_packaging()
            animal.deliver_product()
            animal.save()

        update_order_status_from_animals(order=order)
        order.refresh_from_db()
        self.assertEqual(order.status, SlaughterOrder.Status.COMPLETED)

    def test_bill_order_service(self):
        order = create_slaughter_order(client_id=self.client_profile.id, service_package_id=self.service_package.id, order_datetime=timezone.now(), animals_data=[])
        order.status = SlaughterOrder.Status.COMPLETED
        order.save()

        billed_order = bill_order(order=order)
        self.assertEqual(billed_order.status, SlaughterOrder.Status.BILLED)

        # Test that billing fails if order is not complete
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with self.assertRaises(ValidationError):
            bill_order(order=order)

    def test_add_animal_to_order_service(self):
        order = create_slaughter_order(client_id=self.client_profile.id, service_package_id=self.service_package.id, order_datetime=timezone.now(), animals_data=[])
        self.assertEqual(order.animals.count(), 0)

        animal_data = {'animal_type': 'goat', 'identification_tag': 'GOAT-001'}
        added_animal = add_animal_to_order(order=order, animal_data=animal_data)

        self.assertEqual(order.animals.count(), 1)
        self.assertEqual(added_animal.animal_type, 'goat')
        self.assertEqual(added_animal.identification_tag, 'GOAT-001')

        # Test adding to a non-pending order
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with self.assertRaises(ValidationError):
            add_animal_to_order(order=order, animal_data={'animal_type': 'lamb'})

    def test_remove_animal_from_order_service(self):
        order = create_slaughter_order(client_id=self.client_profile.id, service_package_id=self.service_package.id, order_datetime=timezone.now(), animals_data=[
            {'animal_type': 'cattle', 'identification_tag': 'CATTLE-001'},
            {'animal_type': 'sheep', 'identification_tag': 'SHEEP-001'}
        ])
        self.assertEqual(order.animals.count(), 2)

        animal_to_remove = order.animals.get(identification_tag='SHEEP-001')
        remove_animal_from_order(order=order, animal=animal_to_remove)

        self.assertEqual(order.animals.count(), 1)
        self.assertFalse(Animal.objects.filter(identification_tag='SHEEP-001').exists())

        # Test removing from a non-pending order
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        animal_to_remove_2 = order.animals.get(identification_tag='CATTLE-001')
        with self.assertRaises(ValidationError):
            remove_animal_from_order(order=order, animal=animal_to_remove_2)

    def test_create_batch_animals_service(self):
        """Test creating multiple animals at once with auto-generated tags"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )
        self.assertEqual(order.animals.count(), 0)

        # Test batch creation with custom prefix
        created_animals = create_batch_animals(
            order=order,
            animal_type='cattle',
            quantity=5,
            tag_prefix='FARM-A',
            received_date=timezone.now(),
            skip_photos=True
        )

        self.assertEqual(len(created_animals), 5)
        self.assertEqual(order.animals.count(), 5)
        
        # Check tag generation with custom prefix
        tags = [animal.identification_tag for animal in created_animals]
        expected_tags = ['FARM-A-001', 'FARM-A-002', 'FARM-A-003', 'FARM-A-004', 'FARM-A-005']
        self.assertEqual(sorted(tags), sorted(expected_tags))
        
        # Check all animals have the same type and status
        for animal in created_animals:
            self.assertEqual(animal.animal_type, 'cattle')
            self.assertEqual(animal.status, 'received')
            self.assertEqual(animal.slaughter_order, order)

    def test_create_batch_animals_auto_generated_tags(self):
        """Test batch creation with auto-generated tags"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        # Test batch creation without custom prefix
        created_animals = create_batch_animals(
            order=order,
            animal_type='sheep',
            quantity=3,
            skip_photos=True
        )

        self.assertEqual(len(created_animals), 3)
        
        # Check auto-generated tag format
        for animal in created_animals:
            self.assertTrue(animal.identification_tag.startswith('SHEEP-BATCH-'))
            self.assertTrue(animal.identification_tag.endswith(('-01', '-02', '-03')))

    def test_create_batch_animals_validation_errors(self):
        """Test batch creation validation errors"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        # Test maximum quantity validation
        with self.assertRaises(ValidationError) as context:
            create_batch_animals(
                order=order,
                animal_type='cattle',
                quantity=101,  # Exceeds maximum
                skip_photos=True
            )
        self.assertIn("Maximum 100 animals", str(context.exception))

        # Test non-pending order validation
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        
        with self.assertRaises(ValidationError) as context:
            create_batch_animals(
                order=order,
                animal_type='cattle',
                quantity=5,
                skip_photos=True
            )
        self.assertIn("Can only add animals to a PENDING order", str(context.exception))

    def test_create_batch_animals_different_types(self):
        """Test batch creation with different animal types"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        # Test with different animal types
        animal_types = ['cattle', 'sheep', 'goat', 'lamb']
        
        for animal_type in animal_types:
            created_animals = create_batch_animals(
                order=order,
                animal_type=animal_type,
                quantity=2,
                tag_prefix=f'TEST-{animal_type.upper()}',
                skip_photos=True
            )
            
            for animal in created_animals:
                self.assertEqual(animal.animal_type, animal_type)

        # Should have 8 animals total (2 of each type)
        self.assertEqual(order.animals.count(), 8)

    def test_create_batch_animals_with_received_date(self):
        """Test batch creation with custom received date"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        custom_date = timezone.now() - timezone.timedelta(days=1)
        
        created_animals = create_batch_animals(
            order=order,
            animal_type='cattle',
            quantity=3,
            received_date=custom_date,
            skip_photos=True
        )

        # All animals should have the same custom received date
        for animal in created_animals:
            self.assertEqual(animal.received_date.date(), custom_date.date())

    def test_create_batch_animals_atomic_transaction(self):
        """Test that batch creation is atomic - all or nothing"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        initial_count = order.animals.count()

        # Test with invalid quantity to trigger exception
        with self.assertRaises(ValidationError):
            create_batch_animals(
                order=order,
                animal_type='cattle',
                quantity=101,  # Invalid quantity
                skip_photos=True
            )

        # Should still have the same count (no partial creation)
        self.assertEqual(order.animals.count(), initial_count)

    def test_create_batch_animals_edge_cases(self):
        """Test edge cases for batch creation"""
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        # Test minimum quantity (1)
        created_animals = create_batch_animals(
            order=order,
            animal_type='cattle',
            quantity=1,
            tag_prefix='SINGLE',
            skip_photos=True
        )
        
        self.assertEqual(len(created_animals), 1)
        self.assertEqual(created_animals[0].identification_tag, 'SINGLE-001')

        # Test maximum valid quantity (100)
        order_2 = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

        created_animals = create_batch_animals(
            order=order_2,
            animal_type='sheep',
            quantity=100,
            tag_prefix='MAX',
            skip_photos=True
        )
        
        self.assertEqual(len(created_animals), 100)
        self.assertEqual(order_2.animals.count(), 100)
        
        # Check first and last tags
        tags = [animal.identification_tag for animal in created_animals]
        self.assertIn('MAX-001', tags)
        self.assertIn('MAX-100', tags)

    def test_concurrent_order_creation_race_condition(self):
        """
        Test that concurrent order creation generates unique order numbers.
        This test verifies that the race condition fix works correctly.
        """
        from concurrent.futures import ThreadPoolExecutor
        from django.db import transaction
        
        order_datetime = timezone.now()
        orders = []
        errors = []
        
        def create_order():
            try:
                order = create_slaughter_order(
                    client_id=None,
                    service_package_id=str(self.service_package.id),
                    order_datetime=order_datetime,
                    animals_data=[],
                    client_name="Test Client",
                    client_phone="1234567890"
                )
                orders.append(order.slaughter_order_no)
            except Exception as e:
                errors.append(str(e))
        
        # Create 20 orders concurrently
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(create_order) for _ in range(20)]
            [f.result() for f in futures]
        
        # Verify all order numbers are unique
        self.assertEqual(len(set(orders)), len(orders), 
                         f"All order numbers should be unique. Got duplicates: {[x for x in orders if orders.count(x) > 1]}")
        
        # Verify format: ORD-YYYYMMDD-NNNN
        for order_no in orders:
            self.assertTrue(order_no.startswith("ORD-"), 
                          f"Order number should start with 'ORD-': {order_no}")
            parts = order_no.split('-')
            self.assertEqual(len(parts), 3, 
                           f"Order number should have 3 parts: {order_no}")
            self.assertEqual(len(parts[1]), 8, 
                           f"Date part should be 8 digits: {order_no}")
            self.assertEqual(len(parts[2]), 4, 
                           f"Sequence part should be 4 digits: {order_no}")
        
        # Verify sequential numbering
        numbers = [int(order_no.split('-')[-1]) for order_no in sorted(orders)]
        expected_numbers = list(range(1, len(orders) + 1))
        self.assertEqual(numbers, expected_numbers,
                         f"Order numbers should be sequential: {numbers}")
        
        # Verify no errors occurred
        self.assertEqual(len(errors), 0, 
                         f"No errors should occur during concurrent creation: {errors}")

    def test_generate_order_number_function(self):
        """Test the generate_order_number function directly"""
        from django.db import transaction
        
        order_datetime = timezone.now()
        
        # Generate first order number (must be in transaction for select_for_update)
        with transaction.atomic():
            order_no_1 = generate_order_number(order_datetime)
        self.assertTrue(order_no_1.startswith("ORD-"))
        
        # Create an order with this number to test sequential generation
        order1 = create_slaughter_order(
            client_id=None,
            service_package_id=str(self.service_package.id),
            order_datetime=order_datetime,
            animals_data=[],
            client_name="Test Client 1"
        )
        self.assertEqual(order1.slaughter_order_no, order_no_1)
        
        # Generate second order number (should be sequential)
        with transaction.atomic():
            order_no_2 = generate_order_number(order_datetime)
        self.assertTrue(order_no_2.startswith("ORD-"))
        
        # Extract numbers
        num_1 = int(order_no_1.split('-')[-1])
        num_2 = int(order_no_2.split('-')[-1])
        
        self.assertEqual(num_2, num_1 + 1, 
                        "Second order number should be one more than first")
        
        # Verify same date prefix
        date_part_1 = order_no_1.split('-')[1]
        date_part_2 = order_no_2.split('-')[1]
        self.assertEqual(date_part_1, date_part_2,
                         "Both order numbers should have the same date prefix")
