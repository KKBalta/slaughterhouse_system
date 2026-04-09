"""
View and service tests for the processing app.

Note: Some view tests may be skipped if templates are not available
in the test environment.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal, CattleDetails, DisassemblyCut, WeightLog
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()


@pytest.fixture
def processing_test_data(db):
    admin_user = User.objects.create_user(
        username="proc_admin", password="testpass123", role=User.Role.ADMIN, is_staff=True
    )
    operator_user = User.objects.create_user(username="proc_operator", password="testpass123", role=User.Role.OPERATOR)
    client_user = User.objects.create_user(username="proc_client", password="testpass123", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=client_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1234567890",
        address="123 Test St",
    )
    full_service = ServicePackage.objects.create(
        name="Full Service Proc Test", includes_disassembly=True, includes_delivery=True
    )
    basic_service = ServicePackage.objects.create(
        name="Basic Service Proc Test", includes_disassembly=False, includes_delivery=False
    )
    order = SlaughterOrder.objects.create(
        client=client_profile, order_datetime=timezone.now(), service_package=full_service
    )
    animal = Animal.objects.create(slaughter_order=order, animal_type="cattle", identification_tag="PROC-TEST-001")

    return SimpleNamespace(
        admin_user=admin_user,
        operator_user=operator_user,
        client_user=client_user,
        client_profile=client_profile,
        full_service=full_service,
        basic_service=basic_service,
        order=order,
        animal=animal,
    )


@pytest.mark.django_db
class TestAnimalStatusTransition:
    """Tests for animal status transitions."""

    def test_initial_status_is_received(self, processing_test_data):
        """Test that new animals start in 'received' status."""
        assert processing_test_data.animal.status == "received"

    def test_slaughter_transition(self, processing_test_data):
        """Test transitioning animal to slaughtered status."""
        processing_test_data.animal.perform_slaughter()
        processing_test_data.animal.save()

        assert processing_test_data.animal.status == "slaughtered"
        assert processing_test_data.animal.slaughter_date is not None

    def test_carcass_ready_transition(self, processing_test_data):
        """Test transitioning to carcass_ready status."""
        processing_test_data.animal.perform_slaughter()
        processing_test_data.animal.prepare_carcass()
        processing_test_data.animal.save()

        assert processing_test_data.animal.status == "carcass_ready"

    def test_full_workflow_with_disassembly(self, processing_test_data):
        """Test complete workflow with disassembly."""
        # Slaughter
        processing_test_data.animal.perform_slaughter()
        assert processing_test_data.animal.status == "slaughtered"

        # Carcass ready
        processing_test_data.animal.prepare_carcass()
        assert processing_test_data.animal.status == "carcass_ready"

        # Log hot carcass weight (required for disassembly transition)
        WeightLog.objects.create(
            animal=processing_test_data.animal, weight=Decimal("300.00"), weight_type="hot_carcass_weight"
        )

        # Disassembly (requires service package with disassembly + hot carcass weight)
        processing_test_data.animal.perform_disassembly()
        assert processing_test_data.animal.status == "disassembled"

        # Packaging
        processing_test_data.animal.perform_packaging()
        assert processing_test_data.animal.status == "packaged"

        # Delivery
        processing_test_data.animal.deliver_product()
        processing_test_data.animal.save()
        assert processing_test_data.animal.status == "delivered"

    def test_invalid_transition_blocked(self, processing_test_data):
        """Test that invalid transitions are blocked."""
        # Can't prepare carcass before slaughter
        with pytest.raises(Exception):
            processing_test_data.animal.prepare_carcass()

    def test_disassembly_blocked_without_service(self, processing_test_data):
        """Test that disassembly is blocked when not in service package."""
        basic_order = SlaughterOrder.objects.create(
            client=processing_test_data.client_profile,
            order_datetime=timezone.now(),
            service_package=processing_test_data.basic_service,
        )
        basic_animal = Animal.objects.create(
            slaughter_order=basic_order, animal_type="cattle", identification_tag="BASIC-TEST-001"
        )

        basic_animal.perform_slaughter()
        basic_animal.prepare_carcass()

        # Should fail - service doesn't include disassembly
        with pytest.raises(Exception):
            basic_animal.perform_disassembly()


@pytest.mark.django_db
class TestWeightLog:
    """Tests for weight logging."""

    def test_log_live_weight(self, processing_test_data):
        """Test logging live weight."""
        weight_log = WeightLog.objects.create(
            animal=processing_test_data.animal,
            weight=Decimal("500.00"),
            weight_type="live_weight",
            is_group_weight=False,
        )

        assert weight_log.animal == processing_test_data.animal
        assert weight_log.weight == Decimal("500.00")

    def test_log_hot_carcass_weight(self, processing_test_data):
        """Test logging hot carcass weight after slaughter."""
        processing_test_data.animal.perform_slaughter()
        processing_test_data.animal.save()

        weight_log = WeightLog.objects.create(
            animal=processing_test_data.animal,
            weight=Decimal("300.00"),
            weight_type="hot_carcass_weight",
            is_group_weight=False,
        )

        assert weight_log.weight_type == "hot_carcass_weight"

    def test_group_weight_log(self, processing_test_data):
        """Test creating a group weight log."""
        weight_log = WeightLog.objects.create(
            slaughter_order=processing_test_data.order,
            weight=Decimal("150.00"),
            weight_type="live_weight Group",
            is_group_weight=True,
            group_quantity=5,
            group_total_weight=Decimal("750.00"),
        )

        assert weight_log.is_group_weight
        assert weight_log.group_quantity == 5


@pytest.mark.django_db
class TestDisassemblyCut:
    """Tests for disassembly cuts."""

    def test_create_disassembly_cut(self, processing_test_data):
        """Test creating a disassembly cut."""
        animal = processing_test_data.animal
        animal.perform_slaughter()
        animal.prepare_carcass()
        animal.save()

        cut = DisassemblyCut.objects.create(animal=animal, cut_name="ribeye", weight_kg=Decimal("5.5"))

        assert cut.animal == animal
        assert cut.cut_name == "ribeye"
        assert cut.weight_kg == Decimal("5.5")

    def test_multiple_cuts_per_animal(self, processing_test_data):
        """Test creating multiple cuts for one animal."""
        animal = processing_test_data.animal
        animal.perform_slaughter()
        animal.prepare_carcass()
        animal.save()

        DisassemblyCut.objects.create(animal=animal, cut_name="ribeye", weight_kg=Decimal("5.5"))
        DisassemblyCut.objects.create(animal=animal, cut_name="tenderloin", weight_kg=Decimal("3.0"))
        DisassemblyCut.objects.create(animal=animal, cut_name="sirloin", weight_kg=Decimal("8.0"))

        assert animal.disassembly_cuts.count() == 3


@pytest.mark.django_db
class TestOrderStatusUpdate:
    """Tests for order status updates based on animal processing."""

    def test_order_status_updates_to_in_progress(self, processing_test_data):
        """Test that order status updates when animals are processed."""
        assert processing_test_data.order.status == "PENDING"

        processing_test_data.animal.perform_slaughter()
        processing_test_data.animal.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(processing_test_data.order)

        processing_test_data.order.refresh_from_db()
        assert processing_test_data.order.status == "IN_PROGRESS"

    def test_order_completes_when_all_animals_delivered(self, processing_test_data):
        """Test that order completes when all animals are delivered."""
        # Process animal through all stages
        processing_test_data.animal.perform_slaughter()
        processing_test_data.animal.prepare_carcass()

        # Log hot carcass weight (required for disassembly)
        WeightLog.objects.create(
            animal=processing_test_data.animal, weight=Decimal("300.00"), weight_type="hot_carcass_weight"
        )

        processing_test_data.animal.perform_disassembly()
        processing_test_data.animal.perform_packaging()
        processing_test_data.animal.deliver_product()
        processing_test_data.animal.save()

        from reception.services import update_order_status_from_animals

        update_order_status_from_animals(processing_test_data.order)

        processing_test_data.order.refresh_from_db()
        assert processing_test_data.order.status == "COMPLETED"


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
class TestProcessingDashboardView:
    """Tests for the processing dashboard GET flow."""

    def test_dashboard_renders_without_tenant_schema_name(self, admin_user):
        from django.test import RequestFactory

        from processing.views import ProcessingDashboardView

        factory = RequestFactory()

        first = factory.get("/processing/")
        first.user = admin_user
        second = factory.get("/processing/")
        second.user = admin_user

        first_response = ProcessingDashboardView.as_view()(first)
        second_response = ProcessingDashboardView.as_view()(second)

        assert first_response.status_code == 200
        assert second_response.status_code == 200


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


def _auth_get_request(user, query_data=None):
    """Build an authenticated GET request for view tests."""
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    factory = RequestFactory()
    request = factory.get("/", query_data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
class TestAnimalListView:
    """Tests for AnimalListView queryset and alert context."""

    def test_get_paginate_by_clamps_and_defaults(self, admin_user):
        from processing.views import AnimalListView

        low_request = _auth_get_request(admin_user, {"page_size": "5"})
        low_response = AnimalListView.as_view()(low_request)

        high_request = _auth_get_request(admin_user, {"page_size": "500"})
        high_response = AnimalListView.as_view()(high_request)

        invalid_request = _auth_get_request(admin_user, {"page_size": "not-a-number"})
        invalid_response = AnimalListView.as_view()(invalid_request)

        assert low_response.context_data["current_page_size"] == 10
        assert high_response.context_data["current_page_size"] == 200
        assert invalid_response.context_data["current_page_size"] == 50

    def test_filters_queryset_and_sets_alert_flags(
        self,
        admin_user,
        client_profile_factory,
        service_package_factory,
        slaughter_order_factory,
        animal_factory,
    ):
        from processing.views import AnimalListView
        from users.models import ClientProfile, User

        search_user = User.objects.create_user(
            username="animal_list_match",
            password="testpass123",
            first_name="Aylin",
            last_name="Kasap",
            role=User.Role.CLIENT,
        )
        search_profile = client_profile_factory(
            user=search_user,
            account_type=ClientProfile.AccountType.ENTERPRISE,
            company_name="Acme Butchery",
            contact_person="Aylin Kasap",
        )
        service_package = service_package_factory(name="List View Package")
        matching_order = slaughter_order_factory(client=search_profile, service_package=service_package)
        matching_animal = animal_factory(
            slaughter_order=matching_order,
            animal_type="cattle",
            identification_tag="LIST-MATCH-001",
            status="received",
        )
        matching_animal.perform_slaughter()
        matching_animal.save()

        nonmatching_order = slaughter_order_factory(service_package=service_package, client_name="Walk-in Customer")
        animal_factory(
            slaughter_order=nonmatching_order,
            animal_type="sheep",
            identification_tag="LIST-OTHER-001",
            status="received",
        )

        request = _auth_get_request(
            admin_user,
            {
                "status": "slaughtered",
                "animal_type": "cattle",
                "search": "Acme",
                "page_size": "25",
            },
        )
        response = AnimalListView.as_view()(request)

        animals = list(response.context_data["animals"])
        alerts = response.context_data["animals_with_alerts"]

        assert [animal.pk for animal in animals] == [matching_animal.pk]
        assert len(alerts) == 1
        assert alerts[0]["animal"].pk == matching_animal.pk
        assert alerts[0]["missing_details"] is True
        assert alerts[0]["missing_leather_weight"] is True
        assert alerts[0]["missing_hot_carcass_weight"] is True
        assert response.context_data["current_status"] == "slaughtered"
        assert response.context_data["current_animal_type"] == "cattle"
        assert response.context_data["current_search"] == "Acme"
        assert response.context_data["has_filters"] is True
        assert response.context_data["current_page_size"] == 25
        assert response.context_data["available_page_sizes"] == [25, 50, 100, 200]

    def test_orders_by_newest_order_first_and_tag_within_same_order(
        self,
        admin_user,
        slaughter_order_factory,
        animal_factory,
    ):
        from processing.views import AnimalListView

        older_order = slaughter_order_factory(order_datetime=timezone.now() - timedelta(days=1))
        newer_order = slaughter_order_factory(order_datetime=timezone.now())

        animal_factory(slaughter_order=older_order, identification_tag="DJI-005", status="slaughtered")
        animal_factory(slaughter_order=older_order, identification_tag="DJI-004", status="carcass_ready")
        animal_factory(slaughter_order=newer_order, identification_tag="DJI-001", status="received")

        request = _auth_get_request(admin_user, {"page_size": "50"})
        response = AnimalListView.as_view()(request)

        animals = list(response.context_data["animals"])

        assert [animal.identification_tag for animal in animals[:3]] == ["DJI-001", "DJI-004", "DJI-005"]
        assert [animal.slaughter_order_id for animal in animals[:3]] == [newer_order.pk, older_order.pk, older_order.pk]


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
class TestAnimalDetailView:
    """Tests for AnimalDetailView context and receipt upload/delete flows."""

    def test_get_context_data_for_slaughtered_animal_without_details(self, admin_user, animal_factory):
        from processing.views import AnimalDetailView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_get_request(admin_user)
        response = AnimalDetailView.as_view()(request, pk=animal.pk)

        context = response.context_data

        assert response.status_code == 200
        assert context["missing_hot_carcass_weight"] is True
        assert context["can_fill_details"] is True
        assert context["has_details"] is False
        assert context["can_proceed_to_disassembly"]["can_proceed"] is False
        assert context["scale_sessions_with_allocation"] == []
        assert "detail_form" in context
        assert "Cattle Details" in context["detail_form_title"]

    def test_get_context_data_for_received_animal_exposes_existing_details(self, admin_user, animal_factory):
        from processing.views import AnimalDetailView

        animal = animal_factory(animal_type="cattle", status="received")
        detail = CattleDetails.objects.create(animal=animal, breed="Holstein", sakatat_status=1.0, bowels_status=0.5)

        request = _auth_get_request(admin_user)
        response = AnimalDetailView.as_view()(request, pk=animal.pk)

        context = response.context_data

        assert response.status_code == 200
        assert context["missing_hot_carcass_weight"] is False
        assert context["can_fill_details"] is False
        assert context["has_details"] is False
        assert context["existing_details"] == detail
        assert "detail_form" not in context

    def test_post_delete_scale_receipt_without_existing_file_redirects(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import AnimalDetailView

        animal = animal_factory()
        request = _auth_post_request(admin_user, {"delete_scale_receipt": "1"})
        response = AnimalDetailView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal.pk})

    def test_post_valid_scale_receipt_upload_redirects(self, admin_user, animal_factory, monkeypatch):
        from django.urls import reverse

        from processing.views import AnimalDetailView

        class _ValidForm:
            def __init__(self, *args, **kwargs):
                self.saved = False

            def is_valid(self):
                return True

            def save(self):
                self.saved = True

        animal = animal_factory()
        monkeypatch.setattr("processing.views.ScaleReceiptUploadForm", _ValidForm)

        request = _auth_post_request(admin_user)
        response = AnimalDetailView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal.pk})


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
class TestBatchWeightLogView:
    """Tests for BatchWeightLogView POST actions."""

    def test_get_ignores_none_order_query_param(self, admin_user):
        from django.test import RequestFactory

        from processing.views import BatchWeightLogView

        factory = RequestFactory()
        request = factory.get("/processing/batch/weights/", {"order": "None", "recent_page": "1"})
        request.user = admin_user
        response = BatchWeightLogView.as_view()(request)

        assert response.status_code == 200

    def test_post_edit_batch_log_updates_total_and_redirects(self, admin_user, slaughter_order_factory, animal_factory):
        from django.urls import reverse

        from processing.services import log_group_weight
        from processing.views import BatchWeightLogView

        order = slaughter_order_factory()
        animal_factory(slaughter_order=order, identification_tag="BATCH-VIEW-001")
        animal_factory(slaughter_order=order, identification_tag="BATCH-VIEW-002")
        batch_log = log_group_weight(
            slaughter_order=order,
            weight=Decimal("100.00"),
            weight_type="live_weight Group",
            group_quantity=2,
            group_total_weight=Decimal("200.00"),
        )

        url = reverse("processing:batch_weights")
        request = _auth_post_request(
            admin_user,
            {
                "action": "edit_batch_log",
                "log_id": str(batch_log.pk),
                "total_weight": "250.00",
                "order": str(order.pk),
                "recent_page": "2",
            },
        )
        view = BatchWeightLogView.as_view()
        resp = view(request)

        assert resp.status_code == 302
        assert resp.url == f"{url}?order={order.pk}&recent_page=2"

        updated_log = WeightLog.objects.get(pk=batch_log.pk)
        assert updated_log.group_total_weight == Decimal("250.00")
        assert updated_log.weight == Decimal("125.00")
        individual_weights = list(
            WeightLog.objects.filter(
                animal__slaughter_order=order,
                weight_type="live_weight",
                is_group_weight=False,
            )
            .order_by("animal__identification_tag")
            .values_list("weight", flat=True)
        )
        assert individual_weights == [Decimal("125.00"), Decimal("125.00")]


@pytest.mark.django_db
class TestBatchSlaughterView:
    """Tests for BatchSlaughterView GET and POST flows."""

    def test_get_lists_received_orders_with_type_breakdown(self, admin_user, slaughter_order_factory, animal_factory):
        from processing.views import BatchSlaughterView

        order = slaughter_order_factory()
        animal_factory(slaughter_order=order, animal_type="sheep", status="received", identification_tag="BS-001")
        animal_factory(slaughter_order=order, animal_type="cattle", status="received", identification_tag="BS-002")
        animal_factory(slaughter_order=order, animal_type="cattle", status="slaughtered", identification_tag="BS-003")

        request = _auth_get_request(admin_user, {"order": str(order.pk)})
        response = BatchSlaughterView.as_view()(request)

        context = response.context_data

        assert response.status_code == 200
        assert context["selected_order"].pk == order.pk
        assert len(context["orders"]) == 1
        assert context["orders"][0].received_type_rows == [
            {"label": "Cattle", "count": 1},
            {"label": "Sheep", "count": 1},
        ]

    def test_post_without_order_id_redirects(self, admin_user):
        from django.urls import reverse

        from processing.views import BatchSlaughterView

        request = _auth_post_request(admin_user)
        response = BatchSlaughterView.as_view()(request)

        assert response.status_code == 302
        assert response.url == reverse("processing:batch_slaughter")

    def test_post_processes_successes_and_failures(
        self, admin_user, slaughter_order_factory, animal_factory, monkeypatch
    ):
        from django.urls import reverse

        from processing.views import BatchSlaughterView

        order = slaughter_order_factory()
        success_animal = animal_factory(slaughter_order=order, status="received", identification_tag="BS-OK-001")
        failing_animal = animal_factory(slaughter_order=order, status="received", identification_tag="BS-FAIL-001")

        def _fake_mark_slaughtered(animal):
            if animal.pk == failing_animal.pk:
                raise RuntimeError("boom")
            animal.perform_slaughter()
            animal.save()

        monkeypatch.setattr("processing.views.mark_animal_slaughtered", _fake_mark_slaughtered)

        request = _auth_post_request(admin_user, {"order_id": str(order.pk)})
        response = BatchSlaughterView.as_view()(request)

        success_status = Animal.objects.get(pk=success_animal.pk).status
        failing_status = Animal.objects.get(pk=failing_animal.pk).status

        assert response.status_code == 302
        assert response.url == reverse("processing:batch_slaughter")
        assert success_status == "slaughtered"
        assert failing_status == "received"


@pytest.mark.django_db
class TestBatchWeightReportsView:
    """Tests for BatchWeightReportsView filter parsing."""

    def test_get_parses_dates_and_preserves_form_data(self, admin_user, mocker):
        from processing.views import BatchWeightReportsView

        reports_mock = mocker.patch(
            "processing.views.services.get_batch_weight_reports",
            return_value={"report_rows": [{"weight_type": "hot_carcass_weight"}], "summary": {"count": 1}},
        )

        request = _auth_get_request(
            admin_user,
            {"date_from": "2026-03-01", "date_to": "not-a-date", "order_id": "order-123"},
        )
        response = BatchWeightReportsView.as_view()(request)

        context = response.context_data

        assert response.status_code == 200
        reports_mock.assert_called_once_with(
            date_from=timezone.datetime(2026, 3, 1).date(), date_to=None, order_id="order-123"
        )
        assert context["report_rows"] == [{"weight_type": "hot_carcass_weight"}]
        assert context["summary"] == {"count": 1}
        assert context["form_data"] == {"date_from": "2026-03-01", "date_to": "", "order_id": "order-123"}


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
class TestAnimalSearchDebugView:
    """Tests for AnimalSearchDebugView debug payloads."""

    def test_short_query_returns_debug_hint(self, client):
        from django.urls import reverse

        response = client.get(reverse("processing:animal_search_debug"), {"q": "x"})

        assert response.status_code == 200
        assert response.json() == {"debug": "query too short", "animals": []}

    def test_search_returns_walk_in_client_when_client_name_missing(
        self, client, slaughter_order_factory, animal_factory
    ):
        from django.urls import reverse

        order = slaughter_order_factory(client=None, client_name="")
        animal = animal_factory(slaughter_order=order, identification_tag="DEBUG-TAG-001")

        response = client.get(reverse("processing:animal_search_debug"), {"q": "DEBUG-TAG"})

        data = response.json()

        assert response.status_code == 200
        assert data["debug"] == "found 1 results for query: DEBUG-TAG"
        assert data["animals"][0]["id"] == str(animal.pk)
        assert data["animals"][0]["client_info"] == "Walk-in Client"

    def test_search_returns_error_payload_on_exception(self, client, mocker):
        from django.urls import reverse

        mocker.patch("processing.views.Animal.objects.select_related", side_effect=RuntimeError("search exploded"))

        response = client.get(reverse("processing:animal_search_debug"), {"q": "debug"})

        data = response.json()

        assert response.status_code == 200
        assert data["animals"] == []
        assert data["error"] == "search exploded"
        assert data["debug"] == "error: search exploded"


@pytest.mark.django_db
class TestAnimalDetailsUpdateView:
    """Tests for AnimalDetailsUpdateView POST branches."""

    def test_post_rejects_received_animals(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import AnimalDetailsUpdateView

        animal = animal_factory(animal_type="cattle", status="received")
        request = _auth_post_request(admin_user, {"breed": "Holstein", "sakatat_status": "1.0", "bowels_status": "1.0"})
        response = AnimalDetailsUpdateView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal.pk})
        assert not CattleDetails.objects.filter(animal=animal).exists()

    def test_post_creates_cattle_details(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import AnimalDetailsUpdateView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {"breed": "Holstein", "sakatat_status": "1.0", "bowels_status": "0.5"},
        )
        response = AnimalDetailsUpdateView.as_view()(request, pk=animal.pk)

        details = CattleDetails.objects.get(animal=animal)

        assert response.status_code == 302
        assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal.pk})
        assert details.breed == "Holstein"
        assert details.sakatat_status == Decimal("1.0")
        assert details.bowels_status == Decimal("0.5")

    def test_post_updates_existing_cattle_details(self, admin_user, animal_factory):
        from processing.views import AnimalDetailsUpdateView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()
        details = CattleDetails.objects.create(animal=animal, breed="Old Breed", sakatat_status=0.5, bowels_status=0.5)

        request = _auth_post_request(
            admin_user,
            {"breed": "New Breed", "sakatat_status": "1.0", "bowels_status": "1.0"},
        )
        AnimalDetailsUpdateView.as_view()(request, pk=animal.pk)

        details.refresh_from_db()
        assert details.breed == "New Breed"
        assert details.sakatat_status == Decimal("1.0")
        assert details.bowels_status == Decimal("1.0")

    def test_post_invalid_details_form_does_not_save(self, admin_user, animal_factory):
        from processing.views import AnimalDetailsUpdateView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {"breed": "Holstein", "sakatat_status": "9.9", "bowels_status": "9.9"},
        )
        AnimalDetailsUpdateView.as_view()(request, pk=animal.pk)

        assert not CattleDetails.objects.filter(animal=animal).exists()


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


@pytest.mark.django_db
class TestAnimalWeightLogViewExtra:
    """Tests for AnimalWeightLogView validation and overwrite branches."""

    def test_post_invalid_weight_type_does_not_create_log(self, admin_user, animal_factory):
        from processing.views import AnimalWeightLogView

        animal = animal_factory(status="received")
        request = _auth_post_request(admin_user, {"weight_type": "hot_carcass_weight", "weight": "250.00"})
        response = AnimalWeightLogView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert not WeightLog.objects.filter(animal=animal, weight_type="hot_carcass_weight").exists()

    def test_post_existing_weight_updates_single_log(self, admin_user, animal_factory, weight_log_factory):
        from processing.views import AnimalWeightLogView

        animal = animal_factory(status="received")
        animal.perform_slaughter()
        animal.save()
        weight_log_factory(animal=animal, weight_type="hot_carcass_weight", weight=200.0)

        request = _auth_post_request(admin_user, {"weight_type": "hot_carcass_weight", "weight": "250.00"})
        response = AnimalWeightLogView.as_view()(request, pk=animal.pk)

        logs = WeightLog.objects.filter(animal=animal, weight_type="hot_carcass_weight")
        assert response.status_code == 302
        assert logs.count() == 1
        assert logs.get().weight == Decimal("250.00")


@pytest.mark.django_db
class TestLeatherWeightLogViewExtra:
    """Tests for invalid leather weight submissions."""

    def test_post_invalid_leather_weight_keeps_existing_value_empty(self, admin_user, animal_factory):
        from processing.views import LeatherWeightLogView

        animal = animal_factory(status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(admin_user, {"leather_weight_kg": "500"})
        response = LeatherWeightLogView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert Animal.objects.get(pk=animal.pk).leather_weight_kg is None


@pytest.mark.django_db
class TestQuickProcessView:
    """Tests for QuickProcessView GET, POST, Save & Next, and Save & Print Label."""

    # -- Helper to test internal methods without template rendering -----------

    def _view_instance(self):
        from processing.views import QuickProcessView

        return QuickProcessView()

    # -- GET ------------------------------------------------------------------

    def test_get_defaults_sakatat_bowels_to_good(self, admin_user, animal_factory):
        view = self._view_instance()
        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        initial = view._build_initial(animal)
        assert initial["sakatat_status"] == 1.0
        assert initial["bowels_status"] == 1.0

    def test_get_prefills_existing_data(self, admin_user, animal_factory, weight_log_factory):
        view = self._view_instance()
        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()
        CattleDetails.objects.create(animal=animal, breed="Angus", sakatat_status=0.5, bowels_status=1.0)
        weight_log_factory(animal=animal, weight=350.0, weight_type="live_weight")

        initial = view._build_initial(animal)
        assert initial["breed"] == "Angus"
        assert float(initial["sakatat_status"]) == 0.5
        assert float(initial["live_weight"]) == 350.0

    def test_get_requires_login(self, client, animal_factory):
        animal = animal_factory()
        response = client.get(f"/tr/processing/animals/{animal.pk}/quick/")
        assert response.status_code == 302
        assert "login" in response.url

    # -- POST: Save All -------------------------------------------------------

    def test_post_saves_details_and_weights(self, admin_user, animal_factory):
        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {
                "save": "",
                "breed": "Holstein",
                "sakatat_status": "1.0",
                "bowels_status": "0.5",
                "live_weight": "450.00",
                "hot_carcass_weight": "220.00",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        # Verify details saved
        details = CattleDetails.objects.get(animal=animal)
        assert details.breed == "Holstein"
        assert float(details.bowels_status) == 0.5
        # Verify weights saved
        assert WeightLog.objects.filter(animal=animal, weight_type="live_weight").exists()
        assert WeightLog.objects.filter(animal=animal, weight_type="hot_carcass_weight").exists()

    def test_post_saves_leather_weight(self, admin_user, animal_factory):
        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {
                "save": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
                "leather_weight": "12.50",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        # Re-fetch from DB (refresh_from_db blocked by django-fsm protected status)
        updated = Animal.objects.get(pk=animal.pk)
        assert float(updated.leather_weight_kg) == 12.50

    def test_post_no_changes_shows_info(self, admin_user, animal_factory):
        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="lamb", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {
                "save": "",
                "sakatat_status": "",
                "bowels_status": "",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302

    def test_post_invalid_weight_rerenders_form(self, admin_user, animal_factory):
        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {
                "save": "",
                "live_weight": "99999",  # exceeds 2000 limit
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        # Re-renders the form (not a redirect)
        assert response.status_code == 200

    # -- POST: Save & Next ----------------------------------------------------

    def test_save_next_redirects_to_sibling(self, admin_user, slaughter_order_factory, animal_factory):
        from django.urls import reverse

        from processing.views import QuickProcessView

        order = slaughter_order_factory()
        a1 = animal_factory(slaughter_order=order, animal_type="sheep", status="received")
        a1.perform_slaughter()
        a1.save()
        a2 = animal_factory(slaughter_order=order, animal_type="sheep", status="received")

        request = _auth_post_request(
            admin_user,
            {
                "save_next": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
            },
        )
        response = QuickProcessView.as_view()(request, pk=a1.pk)

        assert response.status_code == 302
        assert response.url == reverse("processing:quick_process", kwargs={"pk": a2.pk})

    def test_save_next_cycles_back_to_first(self, admin_user, slaughter_order_factory, animal_factory):
        from django.urls import reverse

        from processing.views import QuickProcessView

        order = slaughter_order_factory()
        a1 = animal_factory(slaughter_order=order, animal_type="sheep", status="received")
        a2 = animal_factory(slaughter_order=order, animal_type="sheep", status="received")
        a2.perform_slaughter()
        a2.save()

        request = _auth_post_request(
            admin_user,
            {
                "save_next": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
            },
        )
        response = QuickProcessView.as_view()(request, pk=a2.pk)

        assert response.status_code == 302
        assert response.url == reverse("processing:quick_process", kwargs={"pk": a1.pk})

    def test_save_next_single_animal_stays(self, admin_user, animal_factory):
        from django.urls import reverse

        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="sheep", status="received")
        animal.perform_slaughter()
        animal.save()

        request = _auth_post_request(
            admin_user,
            {
                "save_next": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        # Falls through to default redirect (same animal) since no next sibling
        assert response.url == reverse("processing:quick_process", kwargs={"pk": animal.pk})

    # -- POST: Save & Print Label ---------------------------------------------

    def test_save_print_generates_label_and_redirects(self, admin_user, animal_factory, mocker):
        from django.urls import reverse

        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        # Mock label generation to avoid file I/O
        mock_label = SimpleNamespace(pk="00000000-0000-0000-0000-000000000099")
        mock_create = mocker.patch(
            "labeling.utils.create_animal_label",
            return_value=mock_label,
        )

        request = _auth_post_request(
            admin_user,
            {
                "save_print": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
                "hot_carcass_weight": "200.00",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": mock_label.pk})
        mock_create.assert_called_once()
        # Verify weight was still saved
        assert WeightLog.objects.filter(animal=animal, weight_type="hot_carcass_weight").exists()

    def test_save_print_without_weight_falls_through(self, admin_user, animal_factory, mocker):
        from django.urls import reverse

        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="sheep", status="received")
        animal.perform_slaughter()
        animal.save()

        mock_create = mocker.patch("labeling.utils.create_animal_label")

        request = _auth_post_request(
            admin_user,
            {
                "save_print": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
                # No hot_carcass_weight
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        assert response.status_code == 302
        # Should redirect to self, not label detail
        assert response.url == reverse("processing:quick_process", kwargs={"pk": animal.pk})
        mock_create.assert_not_called()

    def test_save_print_label_error_falls_through(self, admin_user, animal_factory, mocker):
        from django.urls import reverse

        from processing.views import QuickProcessView

        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()

        mocker.patch(
            "labeling.utils.create_animal_label",
            side_effect=Exception("Printer on fire"),
        )

        request = _auth_post_request(
            admin_user,
            {
                "save_print": "",
                "sakatat_status": "1.0",
                "bowels_status": "1.0",
                "hot_carcass_weight": "200.00",
            },
        )
        response = QuickProcessView.as_view()(request, pk=animal.pk)

        # Falls through to default redirect with error message
        assert response.status_code == 302
        assert response.url == reverse("processing:quick_process", kwargs={"pk": animal.pk})

    # -- Progress tracking ----------------------------------------------------

    def test_progress_tracks_filled_fields(self, admin_user, animal_factory, weight_log_factory):
        view = self._view_instance()
        animal = animal_factory(animal_type="cattle", status="received")
        animal.perform_slaughter()
        animal.save()
        CattleDetails.objects.create(animal=animal, breed="Angus", sakatat_status=1.0, bowels_status=1.0)
        weight_log_factory(animal=animal, weight=350.0, weight_type="live_weight")

        progress = view._get_progress(animal)
        assert progress["sakatat_status"] is True
        assert progress["bowels_status"] is True
        assert progress["breed"] is True
        assert progress["live_weight"] is True
        assert progress["hot_carcass_weight"] is False
        assert progress["leather_weight"] is False
        filled = sum(1 for v in progress.values() if v)
        assert filled == 4
        assert len(progress) == 6

    # -- Form field visibility ------------------------------------------------

    def test_lamb_has_no_breed_or_leather(self, admin_user, animal_factory):
        from processing.forms import QuickProcessForm

        animal = animal_factory(animal_type="lamb", status="received")
        animal.perform_slaughter()
        animal.save()

        form = QuickProcessForm(animal=animal)
        assert "breed" not in form.fields
        assert "leather_weight" not in form.fields
        assert "sakatat_status" in form.fields

    def test_received_animal_hides_hot_carcass_and_leather(self, admin_user, animal_factory):
        from processing.forms import QuickProcessForm

        animal = animal_factory(animal_type="cattle", status="received")

        form = QuickProcessForm(animal=animal)
        assert "hot_carcass_weight" not in form.fields
        assert "leather_weight" not in form.fields
        assert "live_weight" in form.fields
