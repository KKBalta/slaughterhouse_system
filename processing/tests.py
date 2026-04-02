import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from reception.models import ServicePackage, SlaughterOrder
from users.models import ClientProfile

from .models import Animal, CalfDetails, CattleDetails, GoatDetails, HeiferDetails, LambDetails, OglakDetails, WeightLog

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def processing_test_context():
    user = User.objects.create_user(username="testuser", password="password123", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="1234567890",
        address="123 Test St",
    )
    service_package_full = ServicePackage.objects.create(
        name="Full Processing",
        includes_disassembly=True,
        includes_delivery=True,
    )
    service_package_simple = ServicePackage.objects.create(
        name="Slaughter Only",
        includes_disassembly=False,
        includes_delivery=False,
    )
    order = SlaughterOrder.objects.create(
        client=client_profile,
        order_datetime=timezone.now(),
        service_package=service_package_full,
    )
    return {
        "user": user,
        "client_profile": client_profile,
        "service_package_full": service_package_full,
        "service_package_simple": service_package_simple,
        "order": order,
    }


def _slaughter(animal):
    animal.perform_slaughter()
    animal.save()
    return animal


class TestProcessingModel:
    def test_create_animal(self, processing_test_context):
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            identification_tag="CATTLE-001",
        )

        assert animal.slaughter_order == processing_test_context["order"]
        assert animal.animal_type == "cattle"
        assert animal.identification_tag == "CATTLE-001"
        assert animal.status == "received"

    def test_auto_generate_identification_tag(self, processing_test_context):
        animal = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="sheep")
        animal2 = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="sheep")

        assert animal.identification_tag is not None
        assert animal.identification_tag.startswith("SHEEP-")
        assert animal.identification_tag != animal2.identification_tag

    def test_received_date_editable(self, processing_test_context):
        past_datetime = timezone.make_aware(datetime.datetime(2024, 1, 1, 10, 0, 0))
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            received_date=past_datetime,
        )

        assert animal.received_date == past_datetime

    def test_animal_picture_field(self, processing_test_context):
        image_content = b"GIF89a\x01\x00\x01\x00\x00\xff\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        image_file = SimpleUploadedFile("test_image.gif", image_content, content_type="image/gif")

        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            identification_tag="TEST-CATTLE-001",
            picture=image_file,
        )

        assert animal.picture is not None
        assert animal.picture.name.startswith("animal_pictures/TEST-CATTLE-001_photo")
        assert animal.picture.name.endswith(".gif")

    def test_animal_fsm_transitions(self, processing_test_context):
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            identification_tag="CATTLE-002",
        )

        assert animal.status == "received"

        animal.perform_slaughter()
        assert animal.status == "slaughtered"
        assert animal.slaughter_date is not None

        animal.prepare_carcass()
        assert animal.status == "carcass_ready"

        WeightLog.objects.create(
            animal=animal,
            weight=300.0,
            weight_type="hot_carcass_weight",
            is_group_weight=False,
        )
        animal.perform_disassembly()
        assert animal.status == "disassembled"

        animal.perform_packaging()
        assert animal.status == "packaged"

        animal.deliver_product()
        assert animal.status == "delivered"

    def test_animal_fsm_conditional_transition_fail(self, processing_test_context):
        simple_order = SlaughterOrder.objects.create(
            client=processing_test_context["client_profile"],
            order_datetime=timezone.now(),
            service_package=processing_test_context["service_package_simple"],
        )
        animal = Animal.objects.create(
            slaughter_order=simple_order,
            animal_type="sheep",
            identification_tag="SHEEP-001",
        )
        animal.perform_slaughter()
        animal.prepare_carcass()

        with pytest.raises(Exception):
            animal.perform_disassembly()

    def test_create_animal_details(self, processing_test_context):
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            identification_tag="CATTLE-003",
        )
        cattle_details = CattleDetails.objects.create(
            animal=animal,
            breed="Angus",
            sakatat_status=1.0,
            bowels_status=0.0,
        )

        assert cattle_details.animal == animal
        assert animal.cattle_details == cattle_details
        assert cattle_details.sakatat_status == 1.0
        assert cattle_details.bowels_status == 0.0

    def test_create_new_animal_details_types(self, processing_test_context):
        animal_calf = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="calf")
        CalfDetails.objects.create(animal=animal_calf)
        assert animal_calf.calf_details is not None

        animal_heifer = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="heifer")
        HeiferDetails.objects.create(animal=animal_heifer)
        assert animal_heifer.heifer_details is not None

        animal_goat = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="goat")
        GoatDetails.objects.create(animal=animal_goat)
        assert animal_goat.goat_details is not None

        animal_lamb = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="lamb")
        LambDetails.objects.create(animal=animal_lamb)
        assert animal_lamb.lamb_details is not None

        animal_oglak = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="oglak")
        OglakDetails.objects.create(animal=animal_oglak)
        assert animal_oglak.oglak_details is not None

    def test_animal_leather_weight_kg(self, processing_test_context):
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="cattle",
            leather_weight_kg=150.75,
        )
        animal_sheep = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="sheep",
            leather_weight_kg=10.20,
        )

        assert animal.leather_weight_kg == 150.75
        assert animal_sheep.leather_weight_kg == 10.20

    def test_create_individual_weight_log(self, processing_test_context):
        animal = Animal.objects.create(
            slaughter_order=processing_test_context["order"],
            animal_type="goat",
            identification_tag="GOAT-001",
        )
        weight_log = WeightLog.objects.create(animal=animal, weight=50.5, weight_type="Live")

        assert weight_log.animal == animal
        assert weight_log.weight == 50.5

    def test_create_group_weight_log(self, processing_test_context):
        weight_log = WeightLog.objects.create(
            slaughter_order=processing_test_context["order"],
            weight=45.0,
            weight_type="Live Group",
            is_group_weight=True,
            group_quantity=10,
            group_total_weight=450.0,
        )

        assert weight_log.slaughter_order == processing_test_context["order"]
        assert weight_log.is_group_weight
        assert weight_log.group_quantity == 10

    def test_weight_log_constraints(self, processing_test_context):
        with pytest.raises(Exception):
            WeightLog.objects.create(weight=10.0, weight_type="Test")

        with pytest.raises(Exception):
            WeightLog.objects.create(
                animal=Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="sheep"),
                weight=10.0,
                weight_type="Test",
                group_quantity=5,
            )

        with pytest.raises(Exception):
            WeightLog.objects.create(
                slaughter_order=processing_test_context["order"],
                weight=10.0,
                weight_type="Test",
                is_group_weight=True,
            )

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_weight_log_form_validation(self, processing_test_context):
        from .forms import BatchWeightLogForm

        animal1 = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
        animal2 = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
        _slaughter(animal1)
        _slaughter(animal2)

        valid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 300.0,
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=valid_data)
        assert form.is_valid()

        invalid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 300.0,
            "animal_count": 5,
        }
        form = BatchWeightLogForm(data=invalid_data)
        assert not form.is_valid()
        assert "Cannot log weight for 5 animals" in str(form.errors)

        invalid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 1.0,
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=invalid_data)
        assert not form.is_valid()
        assert "Average weight per animal seems unusually low" in str(form.errors)

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_weight_log_form_multiple_batches_validation(self, processing_test_context):
        from .forms import BatchWeightLogForm

        animals = [
            Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
            for _ in range(3)
        ]
        for animal in animals:
            _slaughter(animal)

        WeightLog.objects.create(
            slaughter_order=processing_test_context["order"],
            weight=150.0,
            weight_type="live_weight Group",
            is_group_weight=True,
            group_quantity=2,
            group_total_weight=300.0,
        )

        valid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 155.0,
            "animal_count": 1,
        }
        form = BatchWeightLogForm(data=valid_data)
        assert form.is_valid(), f"Form should be valid but got errors: {form.errors}"

        invalid_cumulative_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 310.0,
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=invalid_cumulative_data)
        assert not form.is_valid()
        assert "Only 1 animals remain available" in str(form.errors)
        assert "2 already weighed out of 3 total" in str(form.errors)

        invalid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 160.0,
            "animal_count": 10,
        }
        form = BatchWeightLogForm(data=invalid_data)
        assert not form.is_valid()
        errors_str = str(form.errors)
        assert "animals" in errors_str.lower()
        assert "available" in errors_str.lower()

    @override_settings(LANGUAGE_CODE="en")
    def test_batch_weight_log_cumulative_validation(self, processing_test_context):
        from .forms import BatchWeightLogForm

        animals = [
            Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
            for _ in range(4)
        ]
        for animal in animals:
            _slaughter(animal)

        WeightLog.objects.create(
            slaughter_order=processing_test_context["order"],
            weight=150.0,
            weight_type="live_weight Group",
            is_group_weight=True,
            group_quantity=3,
            group_total_weight=450.0,
        )

        invalid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 310.0,
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=invalid_data)
        assert not form.is_valid()
        assert "Only 1 animals remain available" in str(form.errors)
        assert "3 already weighed out of 4 total" in str(form.errors)

        valid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 155.0,
            "animal_count": 1,
        }
        form = BatchWeightLogForm(data=valid_data)
        assert form.is_valid(), f"Form should be valid but got errors: {form.errors}"

        WeightLog.objects.create(
            slaughter_order=processing_test_context["order"],
            weight=155.0,
            weight_type="live_weight Group",
            is_group_weight=True,
            group_quantity=1,
            group_total_weight=155.0,
        )

        invalid_data_final = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": 160.0,
            "animal_count": 1,
        }
        form = BatchWeightLogForm(data=invalid_data_final)
        assert not form.is_valid()
        assert "Only 0 animals remain available" in str(form.errors)
        assert "4 already weighed out of 4 total" in str(form.errors)

    def test_batch_weight_log_decimal_handling(self, processing_test_context):
        from .forms import BatchWeightLogForm

        animal1 = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
        animal2 = Animal.objects.create(slaughter_order=processing_test_context["order"], animal_type="cattle")
        _slaughter(animal1)
        _slaughter(animal2)

        valid_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "live_weight",
            "total_weight": Decimal("300.50"),
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=valid_data)
        assert form.is_valid(), f"Form should handle Decimal inputs but got errors: {form.errors}"

        precise_data = {
            "order_id": str(processing_test_context["order"].id),
            "weight_type": "hot_carcass_weight",
            "total_weight": Decimal("275.75"),
            "animal_count": 2,
        }
        form = BatchWeightLogForm(data=precise_data)
        assert form.is_valid(), f"Form should handle precise Decimal inputs but got errors: {form.errors}"

        cleaned_data = form.clean()
        expected_average = Decimal("275.75") / 2
        actual_average = cleaned_data["total_weight"] / cleaned_data["animal_count"]
        assert actual_average == expected_average
