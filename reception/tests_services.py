
from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import ServicePackage
from users.models import ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal, CattleDetails, SheepDetails
from reception.services import (
    create_slaughter_order, update_slaughter_order, cancel_slaughter_order,
    update_order_status_from_animals, bill_order,
    add_animal_to_order, remove_animal_from_order
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
