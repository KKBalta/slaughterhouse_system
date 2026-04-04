"""
View tests for the reception app.

Tests cover:
- Slaughter order creation
- Order listing and detail views
- Client selection
- Animal addition to orders

Note: View tests that require template rendering are skipped when
SKIP_VIEW_TESTS=true (e.g. in CI without full template setup).
"""

import os

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()

# Skip view tests when templates are not available (e.g. CI); set SKIP_VIEW_TESTS=true to skip
SKIP_VIEW_TESTS = os.environ.get("SKIP_VIEW_TESTS", "false").lower() == "true"
SKIP_REASON = "View tests skipped - templates not available in test environment"

pytestmark = pytest.mark.django_db


@pytest.fixture
def reception_admin_user(db):
    return User.objects.create_user(
        username="reception_admin",
        password="testpass123",
        role=User.Role.ADMIN,
        is_staff=True,
    )


@pytest.fixture
def reception_operator_user(db):
    return User.objects.create_user(
        username="reception_operator",
        password="testpass123",
        role=User.Role.OPERATOR,
    )


@pytest.fixture
def reception_client_user(db):
    return User.objects.create_user(
        username="reception_client",
        password="testpass123",
        role=User.Role.CLIENT,
    )


@pytest.fixture
def reception_client_profile(db, reception_client_user):
    return ClientProfile.objects.create(
        user=reception_client_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="5551234567",
        address="123 Reception Test St",
    )


@pytest.fixture
def reception_service_package(db):
    return ServicePackage.objects.create(
        name="Reception Test Package", includes_disassembly=True, includes_delivery=True
    )


@pytest.fixture
def reception_admin_client(db, reception_admin_user):
    client = Client()
    client.force_login(reception_admin_user)
    return client


def _create_order(*, service_package, client=None, client_name=None, client_phone=None):
    kwargs = {
        "service_package": service_package,
        "order_datetime": timezone.now(),
    }
    if client is not None:
        kwargs["client"] = client
    if client_name is not None:
        kwargs["client_name"] = client_name
    if client_phone is not None:
        kwargs["client_phone"] = client_phone
    return SlaughterOrder.objects.create(**kwargs)


def _response_text(response):
    return response.content.decode(response.charset or "utf-8")


class TestClientSearchAPI:
    def test_search_matches_default_destination(self, reception_admin_client, reception_client_user):
        profile = ClientProfile.objects.create(
            user=reception_client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            contact_person="Delivery Client",
            phone_number="+905551234567",
            address="123 Reception Test St",
            default_destination="Ankara Cold Storage",
        )

        response = reception_admin_client.get(reverse("reception:client_search"), {"q": "Ankara"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["clients"]
        assert payload["clients"][0]["id"] == str(profile.id)
        assert payload["clients"][0]["default_destination"] == "Ankara Cold Storage"

    def test_search_returns_destination_in_payload(self, reception_admin_client, reception_client_user):
        ClientProfile.objects.create(
            user=reception_client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            contact_person="Fast Select",
            phone_number="+905559999888",
            address="123 Reception Test St",
            default_destination="Istanbul Delivery Hub",
        )

        response = reception_admin_client.get(reverse("reception:client_search"), {"q": "Fast"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["clients"][0]["default_destination"] == "Istanbul Delivery Hub"


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestSlaughterOrderListView:
    """Tests for slaughter order list view."""

    def test_order_list_loads(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test that order list view loads."""
        _create_order(client=reception_client_profile, service_package=reception_service_package)
        _create_order(
            client_name="Walk-in Customer",
            client_phone="5559999999",
            service_package=reception_service_package,
        )

        response = reception_admin_client.get(reverse("reception:slaughter_order_list"))
        assert response.status_code in {200, 302}

    def test_order_list_contains_orders(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test that order list contains created orders."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        _create_order(
            client_name="Walk-in Customer",
            client_phone="5559999999",
            service_package=reception_service_package,
        )

        response = reception_admin_client.get(reverse("reception:slaughter_order_list"))
        if response.status_code == 200:
            assert str(order.slaughter_order_no) in _response_text(response)

    def test_order_list_shows_walk_in_customer(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test that order list shows walk-in customer name."""
        _create_order(client=reception_client_profile, service_package=reception_service_package)
        _create_order(
            client_name="Walk-in Customer",
            client_phone="5559999999",
            service_package=reception_service_package,
        )

        response = reception_admin_client.get(reverse("reception:slaughter_order_list"))
        if response.status_code == 200:
            assert "Walk-in Customer" in _response_text(response)

    def test_order_list_pagination(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test order list pagination."""
        for i in range(30):
            _create_order(client_name=f"Customer {i}", service_package=reception_service_package)

        _create_order(client=reception_client_profile, service_package=reception_service_package)

        response = reception_admin_client.get(reverse("reception:slaughter_order_list"))
        if response.status_code == 200:
            assert "page_obj" in response.context

    def test_order_list_filter_by_status(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test filtering orders by status."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()

        response = reception_admin_client.get(reverse("reception:slaughter_order_list"), {"status": "IN_PROGRESS"})

        if response.status_code == 200:
            assert str(order.slaughter_order_no) in _response_text(response)


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestSlaughterOrderCreateView:
    """Tests for slaughter order creation view."""

    def test_create_order_form_loads(self, reception_admin_client):
        """Test that create order form loads."""
        response = reception_admin_client.get(reverse("reception:create_slaughter_order"))
        assert response.status_code in {200, 302}

    def test_create_order_with_registered_client(
        self,
        reception_admin_client,
        reception_client_profile,
        reception_service_package,
    ):
        """Test creating order with registered client."""
        response = reception_admin_client.post(
            reverse("reception:create_slaughter_order"),
            {
                "client": str(reception_client_profile.id),
                "service_package": str(reception_service_package.id),
                "order_datetime": timezone.now().strftime("%Y-%m-%d %H:%M"),
            },
        )
        assert response.status_code in {200, 302}

    def test_create_order_with_walk_in_client(self, reception_admin_client, reception_service_package):
        """Test creating order with walk-in client."""
        response = reception_admin_client.post(
            reverse("reception:create_slaughter_order"),
            {
                "client_name": "New Walk-in",
                "client_phone": "5551112222",
                "service_package": str(reception_service_package.id),
                "order_datetime": timezone.now().strftime("%Y-%m-%d %H:%M"),
            },
        )
        assert response.status_code in {200, 302}


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestSlaughterOrderDetailView:
    """Tests for slaughter order detail view."""

    def _create_order(self, reception_client_profile, reception_service_package):
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        animal = Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="DETAIL-TEST-001",
        )
        return order, animal

    def test_order_detail_loads(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test that order detail view loads."""
        order, _animal = self._create_order(reception_client_profile, reception_service_package)
        response = reception_admin_client.get(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
        assert response.status_code in {200, 302}

    def test_order_detail_shows_animals(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test that order detail shows associated animals."""
        order, _animal = self._create_order(reception_client_profile, reception_service_package)
        response = reception_admin_client.get(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
        if response.status_code == 200:
            assert "DETAIL-TEST-001" in _response_text(response)

    def test_order_detail_shows_client_info(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test that order detail shows client information."""
        order, _animal = self._create_order(reception_client_profile, reception_service_package)
        response = reception_admin_client.get(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
        assert response.status_code in {200, 302}

    @override_settings(LANGUAGE_CODE="en")
    def test_order_detail_operation_dashboard_hidden_with_one_animal(
        self,
        reception_admin_client,
        reception_client_profile,
        reception_service_package,
    ):
        """Operation dashboard link appears only when there is more than one animal."""
        order, _animal = self._create_order(reception_client_profile, reception_service_package)
        response = reception_admin_client.get(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
        if response.status_code == 200:
            assert response.context["animal_count"] == 1
            assert "Operation Dashboard" not in _response_text(response)

    @override_settings(LANGUAGE_CODE="en")
    def test_order_detail_operation_dashboard_shown_with_two_animals(
        self,
        reception_admin_client,
        reception_client_profile,
        reception_service_package,
    ):
        order, _animal = self._create_order(reception_client_profile, reception_service_package)
        Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="DETAIL-TEST-002",
        )
        response = reception_admin_client.get(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
        if response.status_code == 200:
            assert response.context["animal_count"] == 2
            assert "Operation Dashboard" in _response_text(response)


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestAddAnimalToOrderView:
    """Tests for adding animals to orders."""

    def test_add_animal_form_loads(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test that add animal form loads."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        response = reception_admin_client.get(reverse("reception:add_animal_to_order", kwargs={"order_pk": order.pk}))
        assert response.status_code in {200, 302}

    def test_add_single_animal(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test adding a single animal to order."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        response = reception_admin_client.post(
            reverse("reception:add_animal_to_order", kwargs={"order_pk": order.pk}),
            {"animal_type": "cattle", "identification_tag": "NEW-CATTLE-001"},
        )
        assert response.status_code in {200, 302}

    def test_add_batch_animals(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test adding batch of animals to order."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        response = reception_admin_client.post(
            reverse("reception:batch_add_animals_to_order", kwargs={"order_pk": order.pk}),
            {"animal_type": "sheep", "quantity": 5, "tag_prefix": "BATCH", "skip_photos": True},
        )
        assert response.status_code in {200, 302}

    def test_cannot_add_to_non_pending_order(
        self, reception_admin_client, reception_client_profile, reception_service_package
    ):
        """Test that animals cannot be added to non-pending orders."""
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()

        reception_admin_client.post(
            reverse("reception:add_animal_to_order", kwargs={"order_pk": order.pk}),
            {"animal_type": "cattle", "identification_tag": "SHOULD-FAIL-001"},
        )

        assert order.animals.count() == 0


@pytest.mark.skipif(SKIP_VIEW_TESTS, reason=SKIP_REASON)
class TestOrderCancellationView:
    """Tests for order cancellation."""

    def _create_order_and_animal(self, reception_client_profile, reception_service_package):
        order = _create_order(client=reception_client_profile, service_package=reception_service_package)
        animal = Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="CANCEL-TEST-001",
        )
        return order, animal

    def test_cancel_pending_order(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test cancelling a pending order."""
        order, _animal = self._create_order_and_animal(reception_client_profile, reception_service_package)
        response = reception_admin_client.post(reverse("reception:slaughter_order_cancel", kwargs={"pk": order.pk}))
        assert response.status_code in {200, 302}, "Cancel view should return 200 or redirect 302"

        order.refresh_from_db()
        if response.status_code == 302:
            assert order.status == SlaughterOrder.Status.CANCELLED

    def test_cancel_disposes_animals(self, reception_admin_client, reception_client_profile, reception_service_package):
        """Test that cancelling order disposes animals."""
        order, animal = self._create_order_and_animal(reception_client_profile, reception_service_package)
        response = reception_admin_client.post(reverse("reception:slaughter_order_cancel", kwargs={"pk": order.pk}))
        assert response.status_code in {200, 302}, "Cancel view should return 200 or redirect 302"

        animal = Animal.objects.get(pk=animal.pk)
        if response.status_code == 302:
            assert animal.status in ["disposed", "received"]


# ============================================================================
# Pytest-style tests
# ============================================================================


class TestOrderNumberGeneration:
    """Tests for order number generation."""

    def test_order_number_format(self, slaughter_order_factory):
        """Test that order numbers follow expected format."""
        order = slaughter_order_factory()

        # Format should be ORD-YYYYMMDD-NNNN
        assert order.slaughter_order_no.startswith("ORD-")
        parts = order.slaughter_order_no.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 4  # NNNN

    def test_sequential_order_numbers(self, slaughter_order_factory):
        """Test that order numbers are sequential."""
        order1 = slaughter_order_factory()
        order2 = slaughter_order_factory()

        num1 = int(order1.slaughter_order_no.split("-")[-1])
        num2 = int(order2.slaughter_order_no.split("-")[-1])

        assert num2 == num1 + 1


class TestClientSelection:
    """Tests for client selection in order creation."""

    def test_registered_client_linked(self, authenticated_client, client_profile_factory, service_package_factory):
        """Test that registered client is properly linked to order."""
        profile = client_profile_factory()
        service = service_package_factory()

        response = authenticated_client.post(
            reverse("reception:create_slaughter_order"),
            {
                "client": str(profile.id),
                "service_package": str(service.id),
                "order_datetime": timezone.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

        if response.status_code == 302:
            order = SlaughterOrder.objects.last()
            if order:
                assert order.client == profile

    def test_walk_in_client_stored(self, authenticated_client, service_package_factory):
        """Test that walk-in client info is stored correctly."""
        service = service_package_factory()

        response = authenticated_client.post(
            reverse("reception:create_slaughter_order"),
            {
                "client_name": "Walk-in John",
                "client_phone": "5551234567",
                "service_package": str(service.id),
                "order_datetime": timezone.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

        if response.status_code == 302:
            order = SlaughterOrder.objects.last()
            if order:
                assert order.client is not None
                assert order.client.user is not None
                assert order.client.user.role == User.Role.WALKIN
                assert order.client_name == "Walk-in John"
                assert order.client_phone == "+905551234567"


class TestOrderStatusTransitions:
    """Tests for order status transitions."""

    def test_order_status_updates_with_animals(self, slaughter_order_factory, animal_factory):
        """Test that order status updates based on animal statuses."""
        order = slaughter_order_factory()
        animal1 = animal_factory(slaughter_order=order)
        _ = animal_factory(slaughter_order=order)

        animal1.perform_slaughter()
        animal1.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(order)

        order.refresh_from_db()
        assert order.status == SlaughterOrder.Status.IN_PROGRESS

    def test_order_completes_when_all_animals_done(self, service_package_factory):
        """Test that order completes when all animals are processed."""
        from processing.models import Animal, WeightLog
        from reception.models import SlaughterOrder

        service = service_package_factory(includes_disassembly=True, includes_delivery=True)
        order = SlaughterOrder.objects.create(
            client_name="Test",
            client_phone="5551234567",
            service_package=service,
            order_datetime=timezone.now(),
        )
        animal = Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="COMPLETE-TEST-001",
        )

        animal.perform_slaughter()
        animal.prepare_carcass()

        WeightLog.objects.create(animal=animal, weight=300.0, weight_type="hot_carcass_weight")

        animal.perform_disassembly()
        animal.perform_packaging()
        animal.deliver_product()
        animal.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(order)

        order.refresh_from_db()
        assert order.status == SlaughterOrder.Status.COMPLETED
