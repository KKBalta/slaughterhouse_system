"""
Tests for the portal app.

Note: The portal app doesn't have URL routes configured yet.
These tests focus on model and service functionality.
"""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def portal_test_data():
    service_package = ServicePackage.objects.create(
        name="Portal Test Package", includes_disassembly=True, includes_delivery=True
    )

    admin_user = User.objects.create_user(
        username="portal_admin", password="testpass123", role=User.Role.ADMIN, is_staff=True
    )

    client_user = User.objects.create_user(username="portal_client", password="testpass123", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=client_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="5551234567",
        address="123 Client Portal St",
    )

    other_client_user = User.objects.create_user(username="other_client", password="testpass123", role=User.Role.CLIENT)
    other_client_profile = ClientProfile.objects.create(
        user=other_client_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="5559876543",
        address="456 Other Client St",
    )

    return SimpleNamespace(
        service_package=service_package,
        admin_user=admin_user,
        client_user=client_user,
        client_profile=client_profile,
        other_client_user=other_client_user,
        other_client_profile=other_client_profile,
    )


class TestClientOrderAccess:
    def test_client_can_query_own_orders(self, portal_test_data):
        order1 = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        Animal.objects.create(slaughter_order=order1, animal_type="cattle", identification_tag="PORTAL-CATTLE-001")
        order2 = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        SlaughterOrder.objects.create(
            client=portal_test_data.other_client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )

        own_orders = SlaughterOrder.objects.filter(client=portal_test_data.client_profile)
        assert own_orders.count() == 2
        assert order1 in own_orders
        assert order2 in own_orders

    def test_client_cannot_query_other_orders(self, portal_test_data):
        order1 = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        other_order = SlaughterOrder.objects.create(
            client=portal_test_data.other_client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )

        own_orders = SlaughterOrder.objects.filter(client=portal_test_data.client_profile)
        assert order1 in own_orders
        assert other_order not in own_orders

    def test_order_has_animals(self, portal_test_data):
        order = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="PORTAL-CATTLE-001")

        animals = order.animals.all()
        assert animals.count() == 1
        assert animals.first().identification_tag == "PORTAL-CATTLE-001"


class TestClientDataIsolation:
    def test_clients_have_separate_profiles(self, portal_test_data):
        assert portal_test_data.client_profile != portal_test_data.other_client_profile
        assert portal_test_data.client_profile.user == portal_test_data.client_user
        assert portal_test_data.other_client_profile.user == portal_test_data.other_client_user

    def test_order_client_relationship(self, portal_test_data):
        order = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )

        assert order.client == portal_test_data.client_profile
        assert order.client_name in [None, ""]


class TestAnimalTracking:
    def test_animal_initial_status(self, portal_test_data):
        order = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="TRACKING-001")

        assert animal.status == "received"

    def test_animal_status_transitions(self, portal_test_data):
        order = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="TRACKING-001")

        animal.perform_slaughter()
        animal.save()

        assert animal.status == "slaughtered"
        assert animal.slaughter_date is not None

    def test_animal_linked_to_order(self, portal_test_data):
        order = SlaughterOrder.objects.create(
            client=portal_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=portal_test_data.service_package,
        )
        animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="TRACKING-001")

        assert animal.slaughter_order == order
        assert animal in order.animals.all()


class TestClientDataAccess:
    def test_client_order_query(self, client_profile_factory, slaughter_order_factory):
        profile = client_profile_factory()
        order1 = slaughter_order_factory(client=profile)
        order2 = slaughter_order_factory(client=profile)

        orders = SlaughterOrder.objects.filter(client=profile)
        assert orders.count() == 2
        assert order1 in orders
        assert order2 in orders

    def test_different_clients_isolated(self, client_profile_factory, slaughter_order_factory):
        profile1 = client_profile_factory()
        profile2 = client_profile_factory()

        order1 = slaughter_order_factory(client=profile1)
        order2 = slaughter_order_factory(client=profile2)

        orders1 = SlaughterOrder.objects.filter(client=profile1)
        assert order1 in orders1
        assert order2 not in orders1

        orders2 = SlaughterOrder.objects.filter(client=profile2)
        assert order2 in orders2
        assert order1 not in orders2
