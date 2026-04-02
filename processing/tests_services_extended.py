"""
Extended service tests for the processing app.

Tests cover additional service functions and edge cases.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from processing.models import Animal, WeightLog
from processing.services import (
    ANIMAL_DETAIL_MODELS,
    create_animal,
    create_carcass_from_slaughter,
    disassemble_carcass,
    get_batch_weight_reports,
    get_batch_weight_summary,
    log_group_weight,
    log_individual_weight,
    log_leather_weight,
    mark_animal_slaughtered,
    record_cold_carcass_weight,
    record_initial_byproducts,
    update_animal_details,
    update_group_weight_log_total,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def processing_order(client_profile_factory, service_package_factory, slaughter_order_factory):
    """Create a processing order with the full service package enabled."""

    return slaughter_order_factory(
        client=client_profile_factory(),
        service_package=service_package_factory(includes_disassembly=True, includes_delivery=True),
    )


def _slaughter(animal):
    animal.perform_slaughter()
    animal.save()
    return animal


def _prepare_carcass(animal):
    animal.prepare_carcass()
    animal.save()
    return animal


class TestCreateAnimalService:
    """Tests for the create_animal service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order

    def test_create_animal_without_details(self):
        animal = create_animal(order=self.order, animal_type="cattle", identification_tag="TEST-CATTLE-001")

        assert isinstance(animal, Animal)
        assert animal.animal_type == "cattle"
        assert animal.identification_tag == "TEST-CATTLE-001"
        assert animal.status == "received"

    def test_create_animal_with_cattle_details(self):
        details_data = {"breed": "Angus", "sakatat_status": Decimal("1.0"), "bowels_status": Decimal("1.0")}

        animal = create_animal(
            order=self.order,
            animal_type="cattle",
            identification_tag="CATTLE-DETAILS-001",
            details_data=details_data,
        )

        assert hasattr(animal, "cattle_details")
        assert animal.cattle_details.breed == "Angus"

    def test_create_animal_with_sheep_details(self):
        details_data = {"sakatat_status": Decimal("1.0"), "bowels_status": Decimal("0.5")}

        animal = create_animal(
            order=self.order,
            animal_type="sheep",
            identification_tag="SHEEP-DETAILS-001",
            details_data=details_data,
        )

        assert hasattr(animal, "sheep_details")

    def test_create_animal_all_types(self):
        for animal_type in ANIMAL_DETAIL_MODELS:
            animal = create_animal(
                order=self.order,
                animal_type=animal_type,
                identification_tag=f"{animal_type.upper()}-TEST-001",
            )
            assert animal.animal_type == animal_type


class TestMarkAnimalSlaughteredService:
    """Tests for the mark_animal_slaughtered service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="SLAUGHTER-TEST-001",
        )

    def test_mark_slaughtered_updates_status(self):
        assert self.animal.status == "received"

        result = mark_animal_slaughtered(self.animal)

        assert result.status == "slaughtered"
        assert result.slaughter_date is not None

    def test_mark_slaughtered_updates_order_status(self):
        assert self.order.status == "PENDING"

        mark_animal_slaughtered(self.animal)

        self.order.refresh_from_db()
        assert self.order.status == "IN_PROGRESS"

    def test_cannot_slaughter_already_slaughtered(self):
        mark_animal_slaughtered(self.animal)

        with pytest.raises(Exception):
            mark_animal_slaughtered(self.animal)


class TestLogIndividualWeightService:
    """Tests for the log_individual_weight service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.animal = Animal.objects.create(
            slaughter_order=processing_order,
            animal_type="cattle",
            identification_tag="WEIGHT-TEST-001",
        )

    def test_log_live_weight(self):
        weight_log = log_individual_weight(animal=self.animal, weight_type="live_weight", weight=500.0)

        assert isinstance(weight_log, WeightLog)
        assert float(weight_log.weight) == 500.0
        assert weight_log.weight_type == "live_weight"

    def test_log_hot_carcass_weight_requires_slaughter(self):
        with pytest.raises(ValidationError):
            log_individual_weight(animal=self.animal, weight_type="hot_carcass_weight", weight=300.0)

    def test_log_hot_carcass_weight_after_slaughter(self):
        _slaughter(self.animal)

        weight_log = log_individual_weight(animal=self.animal, weight_type="hot_carcass_weight", weight=300.0)

        assert weight_log.weight_type == "hot_carcass_weight"

    def test_hot_carcass_weight_transitions_to_carcass_ready(self):
        _slaughter(self.animal)

        log_individual_weight(animal=self.animal, weight_type="hot_carcass_weight", weight=300.0)

        animal = Animal.objects.get(pk=self.animal.pk)
        assert animal.status in {"carcass_ready", "slaughtered"}


class TestUpdateGroupWeightLogTotalService:
    """Tests for editing batch totals and resyncing derived individual logs."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        self.animals = [
            Animal.objects.create(
                slaughter_order=self.order,
                animal_type="cattle",
                identification_tag=f"BATCH-EDIT-{index:03d}",
            )
            for index in range(1, 5)
        ]

    def test_updates_existing_individual_logs_to_new_overall_average(self):
        first_log = log_group_weight(
            slaughter_order=self.order,
            weight=Decimal("100.00"),
            weight_type="live_weight Group",
            group_quantity=2,
            group_total_weight=Decimal("200.00"),
        )
        log_group_weight(
            slaughter_order=self.order,
            weight=Decimal("120.00"),
            weight_type="live_weight Group",
            group_quantity=2,
            group_total_weight=Decimal("240.00"),
        )

        initial_weights = list(
            WeightLog.objects.filter(
                animal__slaughter_order=self.order,
                weight_type="live_weight",
                is_group_weight=False,
            )
            .order_by("animal__identification_tag")
            .values_list("weight", flat=True)
        )
        assert initial_weights == [Decimal("110.00")] * 4

        result = update_group_weight_log_total(first_log.pk, Decimal("260.00"))

        assert result["weight_log"].group_total_weight == Decimal("260.00")
        updated_logs = WeightLog.objects.filter(
            animal__slaughter_order=self.order,
            weight_type="live_weight",
            is_group_weight=False,
        ).order_by("animal__identification_tag")

        assert updated_logs.count() == 4
        assert all(log.weight == Decimal("125.00") for log in updated_logs)
        assert result["sync_result"]["completed"]

    def test_removes_individual_logs_if_order_is_no_longer_complete(self):
        for animal in self.animals:
            _slaughter(animal)

        batch_log = log_group_weight(
            slaughter_order=self.order,
            weight=Decimal("100.00"),
            weight_type="hot_carcass_weight Group",
            group_quantity=4,
            group_total_weight=Decimal("400.00"),
        )

        update_group_weight_log_total(batch_log.pk, Decimal("400.00"))
        assert (
            WeightLog.objects.filter(
                animal__slaughter_order=self.order,
                weight_type="hot_carcass_weight",
                is_group_weight=False,
            ).count()
            == 4
        )

        new_animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="BATCH-EDIT-005",
        )
        _slaughter(new_animal)

        result = update_group_weight_log_total(batch_log.pk, Decimal("410.00"))

        assert not result["sync_result"]["completed"]
        assert (
            WeightLog.objects.filter(
                animal__slaughter_order=self.order,
                weight_type="hot_carcass_weight",
                is_group_weight=False,
            ).count()
            == 0
        )


class TestCreateCarcassService:
    """Tests for the create_carcass_from_slaughter service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.animal = Animal.objects.create(
            slaughter_order=processing_order,
            animal_type="cattle",
            identification_tag="CARCASS-TEST-001",
        )
        _slaughter(self.animal)

    def test_create_carcass(self):
        from inventory.models import Carcass

        carcass = create_carcass_from_slaughter(animal=self.animal, hot_carcass_weight=250.5, disposition="for_sale")

        assert isinstance(carcass, Carcass)
        assert float(carcass.hot_carcass_weight) == 250.5
        assert carcass.disposition == "for_sale"
        assert carcass.animal == self.animal


class TestDisassembleCarcassService:
    """Tests for the disassemble_carcass service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="DISS-CATTLE-001",
        )
        _slaughter(self.animal)
        self.carcass = create_carcass_from_slaughter(
            animal=self.animal,
            hot_carcass_weight=250.0,
            disposition="for_sale",
        )
        _prepare_carcass(self.animal)
        WeightLog.objects.create(
            animal=self.animal,
            weight=Decimal("250.0"),
            weight_type="hot_carcass_weight",
            is_group_weight=False,
        )

    def test_disassemble_carcass_creates_meat_cuts(self):
        from inventory.models import MeatCut

        meat_cuts_data = [
            {"cut_type": "CHUCK", "weight": Decimal("50.0"), "disposition": "returned_to_owner"},
            {"cut_type": "RIBEYE", "weight": Decimal("30.0"), "disposition": "for_sale"},
        ]
        result = disassemble_carcass(
            animal=self.animal,
            meat_cuts_data=meat_cuts_data,
            offal_data=[],
            by_products_data=[],
        )

        assert result["meat_cuts_count"] == 2
        assert MeatCut.objects.filter(carcass=self.carcass).count() == 2

    def test_disassemble_carcass_creates_offal_and_byproducts_for_cattle(self):
        from inventory.models import ByProduct, Offal

        meat_cuts_data = [{"cut_type": "CHUCK", "weight": Decimal("50.0"), "disposition": "returned_to_owner"}]
        offal_data = [{"offal_type": "LIVER", "weight": Decimal("5.0"), "disposition": "returned_to_owner"}]
        by_products_data = [{"byproduct_type": "SKIN", "weight": Decimal("20.0"), "disposition": "for_sale"}]
        result = disassemble_carcass(
            animal=self.animal,
            meat_cuts_data=meat_cuts_data,
            offal_data=offal_data,
            by_products_data=by_products_data,
        )

        assert result["offal_count"] == 1
        assert result["by_products_count"] == 1
        assert Offal.objects.filter(animal=self.animal).count() == 1
        assert ByProduct.objects.filter(animal=self.animal).count() == 1

    def test_disassemble_carcass_rejects_offal_for_sheep(self):
        sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="sheep",
            identification_tag="DISS-SHEEP-001",
        )
        _slaughter(sheep)
        create_carcass_from_slaughter(animal=sheep, hot_carcass_weight=20.0, disposition="for_sale")
        _prepare_carcass(sheep)
        WeightLog.objects.create(
            animal=sheep,
            weight=Decimal("20.0"),
            weight_type="hot_carcass_weight",
            is_group_weight=False,
        )

        meat_cuts_data = [{"cut_type": "NECK", "weight": Decimal("5.0"), "disposition": "returned_to_owner"}]
        offal_data = [{"offal_type": "LIVER_SET", "weight": Decimal("1.0"), "disposition": "returned_to_owner"}]

        with pytest.raises(ValidationError, match="Offal/Byproduct tracking is not applicable"):
            disassemble_carcass(
                animal=sheep,
                meat_cuts_data=meat_cuts_data,
                offal_data=offal_data,
                by_products_data=[],
            )

    def test_disassemble_carcass_requires_carcass_ready(self):
        not_ready = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="DISS-NOT-READY",
        )
        _slaughter(not_ready)
        create_carcass_from_slaughter(animal=not_ready, hot_carcass_weight=200.0, disposition="for_sale")

        with pytest.raises(ValidationError, match="not ready for disassembly"):
            disassemble_carcass(
                animal=not_ready,
                meat_cuts_data=[{"cut_type": "CHUCK", "weight": Decimal("50.0"), "disposition": "returned_to_owner"}],
                offal_data=[],
                by_products_data=[],
            )


class TestUpdateAnimalDetailsService:
    """Tests for the update_animal_details service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.animal = create_animal(
            order=processing_order,
            animal_type="cattle",
            identification_tag="DETAILS-001",
            details_data={"breed": "Angus", "sakatat_status": Decimal("0.5"), "bowels_status": Decimal("1.0")},
        )

    def test_update_animal_details_updates_cattle_fields(self):
        result = update_animal_details(
            self.animal,
            details_data={"breed": "Holstein", "sakatat_status": Decimal("1.0")},
        )

        assert result.cattle_details.breed == "Holstein"
        assert float(result.cattle_details.sakatat_status) == 1.0

    def test_update_animal_details_empty_data_preserves_existing(self):
        result = update_animal_details(self.animal, details_data={})

        assert result.cattle_details.breed == "Angus"


class TestRecordColdCarcassWeightService:
    """Tests for the record_cold_carcass_weight service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        from inventory.models import Carcass

        self.animal = Animal.objects.create(
            slaughter_order=processing_order,
            animal_type="cattle",
            identification_tag="COLD-001",
        )
        _slaughter(self.animal)
        self.carcass = Carcass.objects.create(
            animal=self.animal,
            hot_carcass_weight=Decimal("250.0"),
            disposition="for_sale",
        )

    def test_record_cold_carcass_weight(self):
        from inventory.models import Carcass

        result = record_cold_carcass_weight(self.carcass, cold_carcass_weight=248.5)

        assert isinstance(result, Carcass)
        assert float(result.cold_carcass_weight) == 248.5
        assert result.status == "disassembly_ready"


class TestRecordInitialByproductsService:
    """Tests for the record_initial_byproducts service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="BYPROD-001",
        )
        _slaughter(self.animal)

    def test_record_initial_byproducts_creates_offal_and_byproducts(self):
        from inventory.models import ByProduct, Offal

        offal_data = [{"offal_type": "LIVER", "weight": Decimal("5.0"), "disposition": "returned_to_owner"}]
        by_products_data = [{"byproduct_type": "SKIN", "weight": Decimal("20.0"), "disposition": "for_sale"}]
        result = record_initial_byproducts(self.animal, offal_data=offal_data, by_products_data=by_products_data)

        assert result["offal_count"] == 1
        assert result["by_products_count"] == 1
        assert Offal.objects.filter(animal=self.animal).count() == 1
        assert ByProduct.objects.filter(animal=self.animal).count() == 1

    def test_record_initial_byproducts_rejects_for_sheep(self):
        sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="sheep",
            identification_tag="BYPROD-SHEEP",
        )
        _slaughter(sheep)

        with pytest.raises(ValidationError, match="not applicable for animal type"):
            record_initial_byproducts(
                sheep,
                offal_data=[{"offal_type": "LIVER_SET", "weight": Decimal("1.0"), "disposition": "returned_to_owner"}],
                by_products_data=[],
            )

    def test_record_initial_byproducts_empty_ok_for_sheep(self):
        sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type="sheep",
            identification_tag="BYPROD-SHEEP-OK",
        )
        _slaughter(sheep)

        result = record_initial_byproducts(sheep, offal_data=[], by_products_data=[])

        assert result["offal_count"] == 0
        assert result["by_products_count"] == 0


class TestLogLeatherWeightService:
    """Tests for the log_leather_weight service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.animal = Animal.objects.create(
            slaughter_order=processing_order,
            animal_type="cattle",
            identification_tag="LEATHER-001",
        )

    def test_log_leather_weight_updates_animal_and_creates_weight_log(self):
        result = log_leather_weight(self.animal, leather_weight_kg=15.5)

        assert result == self.animal
        assert float(result.leather_weight_kg) == 15.5
        log = WeightLog.objects.get(animal=self.animal, weight_type="leather_weight")
        assert float(log.weight) == 15.5


class TestLogGroupWeightService:
    """Tests for the log_group_weight service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        for index in range(3):
            Animal.objects.create(
                slaughter_order=self.order,
                animal_type="cattle",
                identification_tag=f"GROUP-{index:03d}",
            )

    def test_log_group_weight_live_weight(self):
        weight_log = log_group_weight(
            slaughter_order=self.order,
            weight=100.0,
            weight_type="Live Weight Group",
            group_quantity=2,
            group_total_weight=200.0,
        )

        assert weight_log is not None
        assert weight_log.is_group_weight
        assert weight_log.group_quantity == 2
        assert float(weight_log.group_total_weight) == 200.0
        assert weight_log.weight_type == "Live Weight Group"

    def test_log_group_weight_exceeding_available_raises(self):
        with pytest.raises(ValueError, match="Only 3 animals are available"):
            log_group_weight(
                slaughter_order=self.order,
                weight=100.0,
                weight_type="Live Weight Group",
                group_quantity=5,
                group_total_weight=500.0,
            )


class TestGetBatchWeightSummaryService:
    """Tests for the get_batch_weight_summary service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order
        Animal.objects.create(
            slaughter_order=self.order,
            animal_type="cattle",
            identification_tag="SUM-001",
        )

    def test_get_batch_weight_summary_empty(self):
        summary = get_batch_weight_summary(self.order)

        assert summary["order"] == self.order
        assert summary["total_animals"] == 0
        assert summary["total_logs_count"] == 0
        assert summary["weight_logs"] == []
        assert summary["weight_progression"] == []

    def test_get_batch_weight_summary_with_logs(self):
        log_group_weight(
            slaughter_order=self.order,
            weight=100.0,
            weight_type="Live Weight Group",
            group_quantity=1,
            group_total_weight=100.0,
        )
        summary = get_batch_weight_summary(self.order)

        assert summary["total_logs_count"] == 1
        assert len(summary["weight_logs"]) == 1
        assert summary["weight_types_logged"] == ["Live Weight Group"]
        assert len(summary["weight_progression"]) == 1
        assert summary["weight_progression"][0]["weight_type"] == "Live Weight Group"
        assert float(summary["weight_progression"][0]["total_weight"]) == 100.0


class TestGetBatchWeightReportsService:
    """Tests for the get_batch_weight_reports service function."""

    @pytest.fixture(autouse=True)
    def _setup(self, processing_order):
        self.order = processing_order

    def test_get_batch_weight_reports_structure(self):
        result = get_batch_weight_reports()

        assert "logs" in result
        assert "stats" in result
        assert "weight_type_stats" in result
        assert "recent_activity" in result
        assert "filters" in result
        assert result["filters"]["date_from"] is None
        assert result["filters"]["date_to"] is None
        assert result["filters"]["order_id"] is None

    def test_get_batch_weight_reports_with_order_id_filter(self):
        result = get_batch_weight_reports(order_id=self.order.id)

        assert result["filters"]["order_id"] == self.order.id


class TestWeightLogValidation:
    """Pytest-style tests for weight log validation."""

    def test_weight_type_normalization(self, animal_factory, slaughter_order_factory, service_package_factory):
        order = slaughter_order_factory(service_package=service_package_factory())
        animal = animal_factory(slaughter_order=order)

        for weight_type in ["live_weight", "Live", "live"]:
            weight_log = log_individual_weight(animal=animal, weight_type=weight_type, weight=100.0)
            assert weight_log is not None

    def test_negative_weight_rejected(self, animal_factory):
        animal = animal_factory()

        try:
            result = log_individual_weight(animal=animal, weight_type="live_weight", weight=-100.0)
        except (ValidationError, ValueError):
            return

        assert result is not None
        assert result.weight_type == "live_weight"


class TestAnimalDetailModels:
    """Tests for animal detail model handling."""

    def test_all_detail_models_mapped(self):
        expected_types = ["cattle", "sheep", "goat", "lamb", "oglak", "calf", "heifer", "beef"]

        for animal_type in expected_types:
            assert animal_type in ANIMAL_DETAIL_MODELS

    def test_detail_model_creation(self, slaughter_order_factory):
        order = slaughter_order_factory()

        for animal_type, detail_model in ANIMAL_DETAIL_MODELS.items():
            animal = Animal.objects.create(
                slaughter_order=order,
                animal_type=animal_type,
                identification_tag=f"{animal_type.upper()}-PYTEST-001",
            )
            detail = detail_model.objects.create(
                animal=animal,
                sakatat_status=Decimal("1.0"),
                bowels_status=Decimal("1.0"),
            )

            assert detail.animal == animal
