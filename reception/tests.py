import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from processing.models import Animal
from users.models import ClientProfile

from .forms import BatchAnimalForm, SlaughterOrderForm, SlaughterOrderUpdateForm
from .models import ServicePackage, SlaughterOrder

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def reception_state():
    user = User.objects.create_user(username="testuser", password="password123", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1234567890",
        address="123 Test St",
    )
    service_package = ServicePackage.objects.create(name="Standard Slaughter", description="Basic slaughter service.")
    return {
        "user": user,
        "client_profile": client_profile,
        "service_package": service_package,
    }


class TestReceptionModels:
    def test_create_order_with_registered_client(self, reception_state):
        order = SlaughterOrder.objects.create(
            client=reception_state["client_profile"],
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        assert order.client == reception_state["client_profile"]
        assert order.service_package == reception_state["service_package"]
        assert SlaughterOrder.objects.count() == 1

    def test_create_order_with_walk_in_client(self, reception_state):
        order = SlaughterOrder.objects.create(
            client_name="John Doe",
            client_phone="555-1234",
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        assert order.client is None
        assert order.client_name == "John Doe"
        assert SlaughterOrder.objects.count() == 1

    def test_client_profile_deletion(self, reception_state):
        order = SlaughterOrder.objects.create(
            client=reception_state["client_profile"],
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        reception_state["client_profile"].delete()
        order.refresh_from_db()
        assert order.client is None

    def test_service_package_deletion(self, reception_state):
        order = SlaughterOrder.objects.create(
            client=reception_state["client_profile"],
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        reception_state["service_package"].delete()
        order.refresh_from_db()
        assert order.service_package is None

    def test_create_order_with_no_client_info(self, reception_state):
        order = SlaughterOrder.objects.create(
            order_datetime=timezone.now(), service_package=reception_state["service_package"]
        )
        assert order.client is None
        assert order.client_name == ""
        assert SlaughterOrder.objects.count() == 1


class TestSlaughterOrderFormValidation:
    """SlaughterOrderForm must require a service package despite nullable FK on the model."""

    def test_create_form_excludes_inactive_service_packages(self, reception_state):
        inactive = ServicePackage.objects.create(name="Retired Package", is_active=False)
        form = SlaughterOrderForm()
        pks = set(form.fields["service_package"].queryset.values_list("pk", flat=True))
        assert reception_state["service_package"].pk in pks
        assert inactive.pk not in pks

    def test_update_form_includes_inactive_package_when_already_on_order(self, reception_state):
        ServicePackage.objects.create(name="Other Active Package")
        pkg = reception_state["service_package"]
        pkg.is_active = False
        pkg.save(update_fields=["is_active"])
        order = SlaughterOrder.objects.create(
            client=reception_state["client_profile"],
            order_datetime=timezone.now(),
            service_package=pkg,
        )
        form = SlaughterOrderUpdateForm(instance=order)
        pks = set(form.fields["service_package"].queryset.values_list("pk", flat=True))
        assert pkg.pk in pks
        assert pks == set(ServicePackage.objects.filter(is_active=True).values_list("pk", flat=True)) | {pkg.pk}

    def test_service_package_required(self, reception_state):
        form_data = {
            "client_name": "Walk-in Customer",
            "client_phone": "5551234567",
            "order_datetime": "2026-04-01T12:00",
            "destination_search": "",
            "destination": "",
            "service_package": "",
        }
        form = SlaughterOrderForm(data=form_data)
        assert not form.is_valid()
        assert "service_package" in form.errors
        assert "service package" in str(form.errors["service_package"]).lower()

    def test_walk_in_phone_optional_for_create_form(self, reception_state):
        form = SlaughterOrderForm(
            data={
                "client_name": "Walk-in Customer",
                "client_phone_area_code": "+90",
                "client_phone": "",
                "destination_search": "",
                "destination": "",
                "service_package": str(reception_state["service_package"].id),
                "order_datetime": "2026-04-01T12:00",
            }
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["client_phone"] == ""

    def test_walk_in_phone_optional_for_update_form(self, reception_state):
        order = SlaughterOrder.objects.create(
            client_name="Walk-in Customer",
            client_phone="",
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        form = SlaughterOrderUpdateForm(
            instance=order,
            data={
                "client_name": "Walk-in Customer",
                "client_phone_area_code": "+90",
                "client_phone": "",
                "destination_search": "",
                "destination": "",
                "service_package": str(reception_state["service_package"].id),
                "order_datetime": "2026-04-01T12:00",
            },
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["client_phone"] == ""

    def test_walk_in_phone_normalized_when_provided(self, reception_state):
        form = SlaughterOrderForm(
            data={
                "client_name": "Walk-in Customer",
                "client_phone_area_code": "+90",
                "client_phone": "555 123 45 67",
                "destination_search": "",
                "destination": "",
                "service_package": str(reception_state["service_package"].id),
                "order_datetime": "2026-04-01T12:00",
            }
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["client_phone"] == "+905551234567"

    def test_walk_in_phone_rejects_too_short_turkish_number(self, reception_state):
        form = SlaughterOrderForm(
            data={
                "client_name": "Walk-in Customer",
                "client_phone_area_code": "+90",
                "client_phone": "5551234",
                "destination_search": "",
                "destination": "",
                "service_package": str(reception_state["service_package"].id),
                "order_datetime": "2026-04-01T12:00",
            }
        )

        assert not form.is_valid()
        assert "client_phone" in form.errors

    def test_destination_search_populates_destination_snapshot(self, reception_state):
        destination_user = User.objects.create_user(
            username="destination-form-user",
            password="password123",
            role=User.Role.CLIENT,
        )
        destination_client = ClientProfile.objects.create(
            user=destination_user,
            account_type=ClientProfile.AccountType.ENTERPRISE,
            company_name="Receiver Co",
            contact_person="Receiver",
            phone_number="+905551230099",
            address="Destination Address",
            tax_id="FORM-1",
        )
        form = SlaughterOrderForm(
            data={
                "client_name": "Walk-in Customer",
                "client_phone_area_code": "+90",
                "client_phone": "5551234567",
                "destination_search": "Receiver Co",
                "destination_client_id": str(destination_client.id),
                "service_package": str(reception_state["service_package"].id),
                "order_datetime": "2026-04-01T12:00",
            }
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["destination_search"] == "Receiver Co"
        assert form.cleaned_data["destination"] == "Receiver Co"
        assert form.cleaned_data["destination_client_id"] == str(destination_client.id)

    def test_update_form_locks_client_and_datetime_but_keeps_guarded_service_edit_after_animals_added(
        self, reception_state
    ):
        order = SlaughterOrder.objects.create(
            client=reception_state["client_profile"],
            destination="Original Route",
            order_datetime=timezone.now(),
            service_package=reception_state["service_package"],
        )
        Animal.objects.create(
            slaughter_order=order,
            animal_type="cattle",
            identification_tag="FORM-LOCK-001",
        )

        form = SlaughterOrderUpdateForm(instance=order)

        assert form.can_edit_client is False
        assert form.can_edit_order_datetime is False
        assert form.can_edit_service_package is True
        assert form.can_edit_destination is True
        assert form.fields["client_search"].disabled is True
        assert form.fields["service_package"].disabled is False
        assert form.fields["order_datetime"].disabled is True
        assert form.fields["destination_search"].disabled is False


class TestBatchAnimalForm:
    """Test cases for the BatchAnimalForm."""

    def test_batch_animal_form_valid_data(self):
        form_data = {
            "animal_type": "cattle",
            "quantity": 10,
            "tag_prefix": "FARM-001",
            "received_date": timezone.now(),
            "skip_photos": True,
        }
        form = BatchAnimalForm(data=form_data)
        assert form.is_valid()

    def test_batch_animal_form_minimum_quantity(self):
        form = BatchAnimalForm(data={"animal_type": "sheep", "quantity": 1, "skip_photos": True})
        assert form.is_valid()

    def test_batch_animal_form_maximum_quantity(self):
        form = BatchAnimalForm(data={"animal_type": "goat", "quantity": 100, "skip_photos": True})
        assert form.is_valid()

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_animal_form_invalid_quantity_too_high(self):
        form = BatchAnimalForm(data={"animal_type": "cattle", "quantity": 101, "skip_photos": True})
        assert not form.is_valid()
        assert "quantity" in form.errors
        error_message = str(form.errors["quantity"])
        assert "Maximum 100 animals" in error_message or "less than or equal to 100" in error_message

    def test_batch_animal_form_invalid_quantity_zero(self):
        form = BatchAnimalForm(data={"animal_type": "lamb", "quantity": 0, "skip_photos": True})
        assert not form.is_valid()
        assert "quantity" in form.errors

    def test_batch_animal_form_invalid_quantity_negative(self):
        form = BatchAnimalForm(data={"animal_type": "oglak", "quantity": -5, "skip_photos": True})
        assert not form.is_valid()
        assert "quantity" in form.errors

    def test_batch_animal_form_missing_required_fields(self):
        form = BatchAnimalForm(data={"tag_prefix": "TEST"})
        assert not form.is_valid()
        assert "animal_type" in form.errors
        assert "quantity" in form.errors

    def test_batch_animal_form_optional_fields(self):
        form = BatchAnimalForm(data={"animal_type": "cattle", "quantity": 5})
        assert form.is_valid()
        assert form.cleaned_data.get("tag_prefix") == ""
        assert form.cleaned_data.get("received_date") is None
        assert not form.cleaned_data.get("skip_photos")

    def test_batch_animal_form_tag_prefix_validation(self):
        form = BatchAnimalForm(
            data={"animal_type": "sheep", "quantity": 3, "tag_prefix": "VALID-PREFIX", "skip_photos": True}
        )
        assert form.is_valid()

        form_data = {"animal_type": "sheep", "quantity": 3, "tag_prefix": "", "skip_photos": True}
        form = BatchAnimalForm(data=form_data)
        assert form.is_valid()

    def test_batch_animal_form_all_animal_types(self):
        from processing.models import Animal

        for animal_type, _ in Animal.ANIMAL_TYPES:
            form = BatchAnimalForm(data={"animal_type": animal_type, "quantity": 2, "skip_photos": True})
            assert form.is_valid(), f"Form should be valid for animal type: {animal_type}"

    def test_batch_animal_form_widget_attributes(self):
        form = BatchAnimalForm()
        assert "modern-select-full" in form.fields["animal_type"].widget.attrs.get("class", "")

        quantity_attrs = form.fields["quantity"].widget.attrs
        assert "w-full" in quantity_attrs.get("class", "")
        assert "px-3" in quantity_attrs.get("class", "")

        tag_prefix_attrs = form.fields["tag_prefix"].widget.attrs
        assert "w-full" in tag_prefix_attrs.get("class", "")

        skip_photos_attrs = form.fields["skip_photos"].widget.attrs
        assert "h-4" in skip_photos_attrs.get("class", "")

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_animal_form_field_labels(self):
        form = BatchAnimalForm()

        assert form.fields["animal_type"].label == "Animal Type"
        assert form.fields["quantity"].label == "Number of Animals"
        assert form.fields["tag_prefix"].label == "Tag Prefix (Optional)"
        assert form.fields["received_date"].label == "Received Date & Time"
        assert form.fields["skip_photos"].label == "Skip Photos for Batch"

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_animal_form_help_text(self):
        form = BatchAnimalForm()

        assert "Custom prefix for identification tags" in form.fields["tag_prefix"].help_text
        assert "Pre-filled with the current date and time" in form.fields["received_date"].help_text
        assert "photos can be added later" in form.fields["skip_photos"].help_text

    def test_batch_animal_form_received_date_initial_now(self):
        form = BatchAnimalForm()
        assert form.fields["received_date"].initial is not None
