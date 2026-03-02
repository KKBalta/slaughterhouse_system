"""
Tests for the portal app.

Note: The portal app doesn't have URL routes configured yet.
These tests focus on model and service functionality.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()


class PortalTestMixin:
    """Mixin class providing common setup for portal tests."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the test class."""
        cls.service_package = ServicePackage.objects.create(
            name="Portal Test Package", includes_disassembly=True, includes_delivery=True
        )

        cls.admin_user = User.objects.create_user(
            username="portal_admin", password="testpass123", role=User.Role.ADMIN, is_staff=True
        )

        cls.client_user = User.objects.create_user(
            username="portal_client", password="testpass123", role=User.Role.CLIENT
        )
        cls.client_profile = ClientProfile.objects.create(
            user=cls.client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="5551234567",
            address="123 Client Portal St",
        )

        cls.other_client_user = User.objects.create_user(
            username="other_client", password="testpass123", role=User.Role.CLIENT
        )
        cls.other_client_profile = ClientProfile.objects.create(
            user=cls.other_client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="5559876543",
            address="456 Other Client St",
        )


class ClientOrderAccessTest(PortalTestMixin, TestCase):
    """Tests for client order access logic."""

    def setUp(self):
        """Set up test orders."""
        self.order1 = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.service_package
        )
        Animal.objects.create(slaughter_order=self.order1, animal_type="cattle", identification_tag="PORTAL-CATTLE-001")

        self.order2 = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.service_package
        )

        self.other_order = SlaughterOrder.objects.create(
            client=self.other_client_profile, order_datetime=timezone.now(), service_package=self.service_package
        )

    def test_client_can_query_own_orders(self):
        """Test that clients can query their own orders."""
        own_orders = SlaughterOrder.objects.filter(client=self.client_profile)
        self.assertEqual(own_orders.count(), 2)
        self.assertIn(self.order1, own_orders)
        self.assertIn(self.order2, own_orders)

    def test_client_cannot_query_other_orders(self):
        """Test that clients' queries don't include other clients' orders."""
        own_orders = SlaughterOrder.objects.filter(client=self.client_profile)
        self.assertNotIn(self.other_order, own_orders)

    def test_order_has_animals(self):
        """Test that orders have associated animals."""
        animals = self.order1.animals.all()
        self.assertEqual(animals.count(), 1)
        self.assertEqual(animals.first().identification_tag, "PORTAL-CATTLE-001")


class ClientDataIsolationTest(PortalTestMixin, TestCase):
    """Tests for data isolation between clients."""

    def test_clients_have_separate_profiles(self):
        """Test that each client has their own profile."""
        self.assertNotEqual(self.client_profile, self.other_client_profile)
        self.assertEqual(self.client_profile.user, self.client_user)
        self.assertEqual(self.other_client_profile.user, self.other_client_user)

    def test_order_client_relationship(self):
        """Test that orders are properly linked to clients."""
        order = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.service_package
        )

        self.assertEqual(order.client, self.client_profile)
        # client_name may be None or empty string when client is set
        self.assertIn(order.client_name, [None, ""])


class AnimalTrackingTest(PortalTestMixin, TestCase):
    """Tests for animal tracking functionality."""

    def setUp(self):
        """Set up test order and animal."""
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.service_package
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order, animal_type="cattle", identification_tag="TRACKING-001"
        )

    def test_animal_initial_status(self):
        """Test that animal starts in 'received' status."""
        self.assertEqual(self.animal.status, "received")

    def test_animal_status_transitions(self):
        """Test that animal status can transition correctly."""
        self.animal.perform_slaughter()
        self.animal.save()

        self.assertEqual(self.animal.status, "slaughtered")
        self.assertIsNotNone(self.animal.slaughter_date)

    def test_animal_linked_to_order(self):
        """Test that animal is properly linked to order."""
        self.assertEqual(self.animal.slaughter_order, self.order)
        self.assertIn(self.animal, self.order.animals.all())


# ============================================================================
# Pytest-style tests
# ============================================================================


@pytest.mark.django_db
class TestClientDataAccess:
    """Pytest-style tests for client data access."""

    def test_client_order_query(self, client_profile_factory, slaughter_order_factory):
        """Test querying orders by client."""
        profile = client_profile_factory()

        # Create orders for this client
        order1 = slaughter_order_factory(client=profile)
        order2 = slaughter_order_factory(client=profile)

        # Query orders
        orders = SlaughterOrder.objects.filter(client=profile)

        assert orders.count() == 2
        assert order1 in orders
        assert order2 in orders

    def test_different_clients_isolated(self, client_profile_factory, slaughter_order_factory):
        """Test that different clients' data is isolated."""
        profile1 = client_profile_factory()
        profile2 = client_profile_factory()

        order1 = slaughter_order_factory(client=profile1)
        order2 = slaughter_order_factory(client=profile2)

        # Profile 1's orders
        orders1 = SlaughterOrder.objects.filter(client=profile1)
        assert order1 in orders1
        assert order2 not in orders1

        # Profile 2's orders
        orders2 = SlaughterOrder.objects.filter(client=profile2)
        assert order2 in orders2
        assert order1 not in orders2
