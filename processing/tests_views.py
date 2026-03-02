"""
View and service tests for the processing app.

Note: Some view tests may be skipped if templates are not available
in the test environment.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal, DisassemblyCut, WeightLog
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()


class ProcessingModelTestMixin:
    """Mixin class providing common setup for processing tests."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data for the test class."""
        cls.admin_user = User.objects.create_user(
            username="proc_admin", password="testpass123", role=User.Role.ADMIN, is_staff=True
        )
        cls.operator_user = User.objects.create_user(
            username="proc_operator", password="testpass123", role=User.Role.OPERATOR
        )
        cls.client_user = User.objects.create_user(
            username="proc_client", password="testpass123", role=User.Role.CLIENT
        )
        cls.client_profile = ClientProfile.objects.create(
            user=cls.client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="1234567890",
            address="123 Test St",
        )

        cls.full_service = ServicePackage.objects.create(
            name="Full Service Proc Test", includes_disassembly=True, includes_delivery=True
        )
        cls.basic_service = ServicePackage.objects.create(
            name="Basic Service Proc Test", includes_disassembly=False, includes_delivery=False
        )

    def setUp(self):
        """Set up test client and login."""
        self.test_client = Client()
        self.test_client.login(username="proc_admin", password="testpass123")

        self.order = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.full_service
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order, animal_type="cattle", identification_tag="PROC-TEST-001"
        )


class AnimalStatusTransitionTest(ProcessingModelTestMixin, TestCase):
    """Tests for animal status transitions."""

    def test_initial_status_is_received(self):
        """Test that new animals start in 'received' status."""
        self.assertEqual(self.animal.status, "received")

    def test_slaughter_transition(self):
        """Test transitioning animal to slaughtered status."""
        self.animal.perform_slaughter()
        self.animal.save()

        self.assertEqual(self.animal.status, "slaughtered")
        self.assertIsNotNone(self.animal.slaughter_date)

    def test_carcass_ready_transition(self):
        """Test transitioning to carcass_ready status."""
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()

        self.assertEqual(self.animal.status, "carcass_ready")

    def test_full_workflow_with_disassembly(self):
        """Test complete workflow with disassembly."""
        # Slaughter
        self.animal.perform_slaughter()
        self.assertEqual(self.animal.status, "slaughtered")

        # Carcass ready
        self.animal.prepare_carcass()
        self.assertEqual(self.animal.status, "carcass_ready")

        # Log hot carcass weight (required for disassembly transition)
        WeightLog.objects.create(animal=self.animal, weight=Decimal("300.00"), weight_type="hot_carcass_weight")

        # Disassembly (requires service package with disassembly + hot carcass weight)
        self.animal.perform_disassembly()
        self.assertEqual(self.animal.status, "disassembled")

        # Packaging
        self.animal.perform_packaging()
        self.assertEqual(self.animal.status, "packaged")

        # Delivery
        self.animal.deliver_product()
        self.animal.save()
        self.assertEqual(self.animal.status, "delivered")

    def test_invalid_transition_blocked(self):
        """Test that invalid transitions are blocked."""
        # Can't prepare carcass before slaughter
        with self.assertRaises(Exception):
            self.animal.prepare_carcass()

    def test_disassembly_blocked_without_service(self):
        """Test that disassembly is blocked when not in service package."""
        basic_order = SlaughterOrder.objects.create(
            client=self.client_profile, order_datetime=timezone.now(), service_package=self.basic_service
        )
        basic_animal = Animal.objects.create(
            slaughter_order=basic_order, animal_type="cattle", identification_tag="BASIC-TEST-001"
        )

        basic_animal.perform_slaughter()
        basic_animal.prepare_carcass()

        # Should fail - service doesn't include disassembly
        with self.assertRaises(Exception):
            basic_animal.perform_disassembly()


class WeightLogTest(ProcessingModelTestMixin, TestCase):
    """Tests for weight logging."""

    def test_log_live_weight(self):
        """Test logging live weight."""
        weight_log = WeightLog.objects.create(
            animal=self.animal, weight=Decimal("500.00"), weight_type="live_weight", is_group_weight=False
        )

        self.assertEqual(weight_log.animal, self.animal)
        self.assertEqual(weight_log.weight, Decimal("500.00"))

    def test_log_hot_carcass_weight(self):
        """Test logging hot carcass weight after slaughter."""
        self.animal.perform_slaughter()
        self.animal.save()

        weight_log = WeightLog.objects.create(
            animal=self.animal, weight=Decimal("300.00"), weight_type="hot_carcass_weight", is_group_weight=False
        )

        self.assertEqual(weight_log.weight_type, "hot_carcass_weight")

    def test_group_weight_log(self):
        """Test creating a group weight log."""
        weight_log = WeightLog.objects.create(
            slaughter_order=self.order,
            weight=Decimal("150.00"),
            weight_type="live_weight Group",
            is_group_weight=True,
            group_quantity=5,
            group_total_weight=Decimal("750.00"),
        )

        self.assertTrue(weight_log.is_group_weight)
        self.assertEqual(weight_log.group_quantity, 5)


class DisassemblyCutTest(ProcessingModelTestMixin, TestCase):
    """Tests for disassembly cuts."""

    def setUp(self):
        super().setUp()
        # Prepare animal for disassembly
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()

    def test_create_disassembly_cut(self):
        """Test creating a disassembly cut."""
        cut = DisassemblyCut.objects.create(animal=self.animal, cut_name="ribeye", weight_kg=Decimal("5.5"))

        self.assertEqual(cut.animal, self.animal)
        self.assertEqual(cut.cut_name, "ribeye")
        self.assertEqual(cut.weight_kg, Decimal("5.5"))

    def test_multiple_cuts_per_animal(self):
        """Test creating multiple cuts for one animal."""
        DisassemblyCut.objects.create(animal=self.animal, cut_name="ribeye", weight_kg=Decimal("5.5"))
        DisassemblyCut.objects.create(animal=self.animal, cut_name="tenderloin", weight_kg=Decimal("3.0"))
        DisassemblyCut.objects.create(animal=self.animal, cut_name="sirloin", weight_kg=Decimal("8.0"))

        self.assertEqual(self.animal.disassembly_cuts.count(), 3)


class OrderStatusUpdateTest(ProcessingModelTestMixin, TestCase):
    """Tests for order status updates based on animal processing."""

    def test_order_status_updates_to_in_progress(self):
        """Test that order status updates when animals are processed."""
        self.assertEqual(self.order.status, "PENDING")

        self.animal.perform_slaughter()
        self.animal.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(self.order)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "IN_PROGRESS")

    def test_order_completes_when_all_animals_delivered(self):
        """Test that order completes when all animals are delivered."""
        # Process animal through all stages
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()

        # Log hot carcass weight (required for disassembly)
        WeightLog.objects.create(animal=self.animal, weight=Decimal("300.00"), weight_type="hot_carcass_weight")

        self.animal.perform_disassembly()
        self.animal.perform_packaging()
        self.animal.deliver_product()
        self.animal.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(self.order)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "COMPLETED")


# ============================================================================
# Pytest-style tests
# ============================================================================


@pytest.mark.django_db
class TestAnimalWorkflow:
    """Pytest-style tests for animal workflow."""

    def test_animal_creation(self, animal_factory):
        """Test creating an animal."""
        animal = animal_factory()

        assert animal.status == "received"
        assert animal.identification_tag is not None

    def test_slaughter_sets_date(self, animal_factory):
        """Test that slaughtering sets the slaughter date."""
        animal = animal_factory()

        assert animal.slaughter_date is None

        animal.perform_slaughter()
        animal.save()

        assert animal.slaughter_date is not None

    def test_all_animal_types(self, slaughter_order_factory):
        """Test creating animals of all types."""
        order = slaughter_order_factory()

        animal_types = ["cattle", "sheep", "goat", "lamb", "oglak", "calf", "heifer", "beef"]

        for animal_type in animal_types:
            animal = Animal.objects.create(
                slaughter_order=order, animal_type=animal_type, identification_tag=f"{animal_type.upper()}-TEST"
            )
            assert animal.animal_type == animal_type


@pytest.mark.django_db
class TestWeightLogValidation:
    """Tests for weight log validation."""

    def test_individual_weight_log(self, animal_factory):
        """Test creating individual weight log."""
        animal = animal_factory()

        log = WeightLog.objects.create(
            animal=animal, weight=Decimal("100.00"), weight_type="live_weight", is_group_weight=False
        )

        assert log.animal == animal
        assert not log.is_group_weight

    def test_weight_log_requires_animal_or_order(self, db):
        """Test that weight log requires animal or order."""

        # This should fail during validation
        log = WeightLog(weight=Decimal("100.00"), weight_type="live_weight")

        with pytest.raises(Exception):
            log.full_clean()
            log.save()


# ============================================================================
# JSON / redirect view tests (no template rendering)
# ============================================================================


def _auth_post_request(user, post_data=None):
    """Build an authenticated POST request for view tests (avoids login/session in test env)."""
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    factory = RequestFactory()
    request = factory.post("/", post_data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
class TestAnimalSearchView:
    """Tests for AnimalSearchView JSON response."""

    def test_search_empty_query_returns_empty_list(self, client):
        """Short query returns empty animals list."""
        from django.urls import reverse

        url = reverse("processing:animal_search")
        resp = client.get(url, {"q": "a"})
        assert resp.status_code == 200
        assert resp["Content-Type"] == "application/json"
        data = resp.json()
        assert data["animals"] == []

    def test_search_no_query_returns_empty_list(self, client):
        """No q param returns empty list."""
        from django.urls import reverse

        url = reverse("processing:animal_search")
        resp = client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["animals"] == []

    def test_search_returns_matching_animals(self, client, animal_factory):
        """Query matching identification_tag returns JSON with animals."""
        from django.urls import reverse

        animal = animal_factory(identification_tag="UNIQUE-TAG-123")
        animal.slaughter_order.save()  # ensure slaughter_order_no exists
        url = reverse("processing:animal_search")
        resp = client.get(url, {"q": "UNIQUE-TAG"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["animals"]) >= 1
        found = next(a for a in data["animals"] if a["identification_tag"] == "UNIQUE-TAG-123")
        assert found["status"] == "received"
        assert "detail_url" in found


@pytest.mark.django_db
class TestMarkAnimalSlaughteredView:
    """Tests for MarkAnimalSlaughteredView POST + redirect."""

    def test_post_marks_slaughtered_and_redirects(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import MarkAnimalSlaughteredView

        animal = animal_factory(status="received")
        request = _auth_post_request(admin_user)
        view = MarkAnimalSlaughteredView.as_view()
        resp = view(request, pk=animal.pk)
        assert resp.status_code == 302
        expected = reverse("processing:animal_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        updated = Animal.objects.get(pk=animal.pk)
        assert updated.status == "slaughtered"
        assert updated.slaughter_date is not None

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        url = reverse("processing:mark_slaughtered", kwargs={"pk": animal.pk})
        resp = client.post(url)
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestAnimalWeightLogView:
    """Tests for AnimalWeightLogView POST + redirect."""

    def test_post_valid_weight_redirects(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import AnimalWeightLogView

        animal = animal_factory()
        animal.perform_slaughter()
        animal.save()
        request = _auth_post_request(admin_user, {"weight_type": "hot_carcass_weight", "weight": "250.00"})
        view = AnimalWeightLogView.as_view()
        resp = view(request, pk=animal.pk)
        assert resp.status_code == 302
        expected = reverse("processing:animal_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        assert WeightLog.objects.filter(animal=animal, weight_type="hot_carcass_weight").exists()

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        url = reverse("processing:animal_weights", kwargs={"pk": animal.pk})
        resp = client.post(url, {"weight_type": "live_weight", "weight": "300"})
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestLeatherWeightLogView:
    """Tests for LeatherWeightLogView POST + redirect."""

    def test_post_valid_leather_weight_redirects(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import LeatherWeightLogView

        animal = animal_factory()
        animal.perform_slaughter()
        animal.save()
        request = _auth_post_request(admin_user, {"leather_weight_kg": "12.5"})
        view = LeatherWeightLogView.as_view()
        resp = view(request, pk=animal.pk)
        assert resp.status_code == 302
        expected = reverse("processing:animal_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        assert Animal.objects.get(pk=animal.pk).leather_weight_kg == Decimal("12.5")

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        url = reverse("processing:leather_weight", kwargs={"pk": animal.pk})
        resp = client.post(url, {"leather_weight_kg": "10"})
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestOrderStatusUpdateView:
    """Tests for OrderStatusUpdateView POST + redirect."""

    def test_post_redirects_to_dashboard(self, admin_user, slaughter_order_factory):
        from django.urls import reverse

        from processing.views import OrderStatusUpdateView

        order = slaughter_order_factory()
        order.save()
        request = _auth_post_request(admin_user)
        view = OrderStatusUpdateView.as_view()
        resp = view(request, order_pk=order.pk)
        assert resp.status_code == 302
        expected = reverse("processing:dashboard")
        assert resp.url.endswith(expected) or expected in resp.url

    def test_post_requires_login(self, client, slaughter_order_factory):
        from django.urls import reverse

        order = slaughter_order_factory()
        url = reverse("processing:order_status_update", kwargs={"order_pk": order.pk})
        resp = client.post(url)
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestAddDisassemblyCutView:
    """Tests for AddDisassemblyCutView POST + redirect."""

    def test_post_valid_cut_redirects(self, admin_user, animal_factory, weight_log_factory):
        from django.urls import reverse

        from processing.views import AddDisassemblyCutView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.prepare_carcass()
        animal.save()
        weight_log_factory(animal=animal, weight_type="hot_carcass_weight", weight=200.0)
        request = _auth_post_request(admin_user, {"cut_name": "ANTREKOT", "weight_kg": "5.50"})
        view = AddDisassemblyCutView.as_view()
        resp = view(request, pk=animal.pk)
        assert resp.status_code == 302
        expected = reverse("processing:disassembly_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        assert DisassemblyCut.objects.filter(animal=animal, cut_name="ANTREKOT").exists()

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        url = reverse("processing:add_disassembly_cut", kwargs={"pk": animal.pk})
        resp = client.post(url, {"cut_name": "ANTREKOT", "weight_kg": "5"})
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestEditDisassemblyCutView:
    """Tests for EditDisassemblyCutView POST + redirect."""

    def test_post_valid_update_redirects(self, admin_user, animal_factory, weight_log_factory):
        from django.urls import reverse

        from processing.views import EditDisassemblyCutView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.prepare_carcass()
        animal.save()
        weight_log_factory(animal=animal, weight_type="hot_carcass_weight", weight=200.0)
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ANTREKOT", weight_kg=Decimal("5.00"))
        request = _auth_post_request(admin_user, {"cut_name": "ANTREKOT", "weight_kg": "7.25"})
        view = EditDisassemblyCutView.as_view()
        resp = view(request, pk=animal.pk, cut_pk=cut.pk)
        assert resp.status_code == 302
        expected = reverse("processing:disassembly_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        assert DisassemblyCut.objects.get(pk=cut.pk).weight_kg == Decimal("7.25")

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ANTREKOT", weight_kg=Decimal("5.00"))
        url = reverse("processing:edit_disassembly_cut", kwargs={"pk": animal.pk, "cut_pk": cut.pk})
        resp = client.post(url, {"cut_name": "ANTREKOT", "weight_kg": "6"})
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()


@pytest.mark.django_db
class TestDeleteDisassemblyCutView:
    """Tests for DeleteDisassemblyCutView POST + redirect."""

    def test_post_deletes_cut_and_redirects(self, admin_user, animal_factory, weight_log_factory):
        from django.urls import reverse

        from processing.views import DeleteDisassemblyCutView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.prepare_carcass()
        animal.save()
        weight_log_factory(animal=animal, weight_type="hot_carcass_weight", weight=200.0)
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ANTREKOT", weight_kg=Decimal("5.00"))
        cut_pk = cut.pk
        request = _auth_post_request(admin_user)
        view = DeleteDisassemblyCutView.as_view()
        resp = view(request, pk=animal.pk, cut_pk=cut.pk)
        assert resp.status_code == 302
        expected = reverse("processing:disassembly_detail", kwargs={"pk": animal.pk})
        assert resp.url.endswith(expected) or expected in resp.url
        assert not DisassemblyCut.objects.filter(pk=cut_pk).exists()

    def test_post_requires_login(self, client, animal_factory):
        from django.urls import reverse

        animal = animal_factory()
        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ANTREKOT", weight_kg=Decimal("5.00"))
        url = reverse("processing:delete_disassembly_cut", kwargs={"pk": animal.pk, "cut_pk": cut.pk})
        resp = client.post(url)
        assert resp.status_code == 302
        assert "/login/" in resp.url or "login" in resp.url.lower()
