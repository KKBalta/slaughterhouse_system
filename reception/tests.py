from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from django.utils import timezone

User = get_user_model()

class ReceptionModelTest(TestCase):
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
            name='Standard Slaughter',
            description='Basic slaughter service.'
        )

    def test_create_order_with_registered_client(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.service_package
        )
        self.assertEqual(order.client, self.client_profile)
        self.assertEqual(order.service_package, self.service_package)
        self.assertEqual(SlaughterOrder.objects.count(), 1)

    def test_create_order_with_walk_in_client(self):
        order = SlaughterOrder.objects.create(
            client_name='John Doe',
            client_phone='555-1234',
            order_datetime=timezone.now(),
            service_package=self.service_package
        )
        self.assertIsNone(order.client)
        self.assertEqual(order.client_name, 'John Doe')
        self.assertEqual(SlaughterOrder.objects.count(), 1)

    def test_client_profile_deletion(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.client_profile.delete()
        order.refresh_from_db()
        self.assertIsNone(order.client)

    def test_service_package_deletion(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.service_package.delete()
        order.refresh_from_db()
        self.assertIsNone(order.service_package)

    def test_create_order_with_no_client_info(self):
        # This might be a valid scenario for some internal processes
        order = SlaughterOrder.objects.create(
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.assertIsNone(order.client)
        self.assertEqual(order.client_name, '')
        self.assertEqual(SlaughterOrder.objects.count(), 1)