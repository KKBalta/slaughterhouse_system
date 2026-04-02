"""Tests for scales app: multi-animal sessions, allocation, backward compatibility."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal, WeightLog
from reception.models import SlaughterOrder
from scales.models import DisassemblySession, EdgeDevice, ScaleDevice, Site, WeighingEvent
from scales.utils import get_event_allocation, get_session_per_animal_summary, maybe_mark_event_animals_disassembled
from users.models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


def _make_animal(slaughter_order, tag="TAG-1", animal_type="cattle"):
    """Create an animal in carcass_ready so it's eligible for scale sessions."""
    animal = Animal.objects.create(
        slaughter_order=slaughter_order,
        animal_type=animal_type,
        identification_tag=tag,
    )
    animal.perform_slaughter()
    animal.save()
    animal.prepare_carcass()
    animal.save()
    return animal


@pytest.fixture
def scale_base_data():
    site = Site.objects.create(name="Test Site")
    edge = EdgeDevice.objects.create(site=site, name="Edge1")
    device = ScaleDevice.objects.create(
        edge=edge,
        device_id="SCALE-01",
        global_device_id="TEST-SCALE-01",
    )
    user = User.objects.create_user(username="test", password="test", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="123",
        address="Addr",
    )
    service_package = ServicePackage.objects.create(
        name="Pkg",
        includes_disassembly=True,
    )
    order = SlaughterOrder.objects.create(
        client=client_profile,
        order_datetime=timezone.now(),
        service_package=service_package,
    )
    animal1 = _make_animal(order, "TAG-1")
    animal2 = _make_animal(order, "TAG-2")
    return {
        "site": site,
        "edge": edge,
        "device": device,
        "client_profile": client_profile,
        "service_package": service_package,
        "order": order,
        "animal1": animal1,
        "animal2": animal2,
        "animals_ordered": [animal1, animal2],
    }


class TestAllocationUtils:
    """Test get_event_allocation and get_session_per_animal_summary."""

    def test_get_event_allocation_split(self, scale_base_data):
        class MockEvent:
            weight_grams = 1000
            assigned_animal_id = None
            assigned_animal = None

        alloc = get_event_allocation(MockEvent(), scale_base_data["animals_ordered"])
        assert alloc[str(scale_base_data["animal1"].id)] == 500
        assert alloc[str(scale_base_data["animal2"].id)] == 500

        MockEvent.weight_grams = 1001
        alloc = get_event_allocation(MockEvent(), scale_base_data["animals_ordered"])
        assert alloc[str(scale_base_data["animal1"].id)] == 501
        assert alloc[str(scale_base_data["animal2"].id)] == 500
        assert sum(alloc.values()) == 1001

    def test_get_event_allocation_manual(self, scale_base_data):
        class MockEvent:
            weight_grams = 600
            assigned_animal_id = None
            assigned_animal = None

        MockEvent.assigned_animal_id = scale_base_data["animal2"].id
        alloc = get_event_allocation(MockEvent(), scale_base_data["animals_ordered"])
        assert alloc[str(scale_base_data["animal1"].id)] == 0
        assert alloc[str(scale_base_data["animal2"].id)] == 600

    def test_get_session_per_animal_summary_single_animal(self, scale_base_data):
        session = DisassemblySession.objects.create(
            site=scale_base_data["site"],
            device=scale_base_data["device"],
            animal=scale_base_data["animal1"],
            operator="op",
            started_at=timezone.now(),
            status="active",
        )
        session.animals.set([scale_base_data["animal1"]])
        WeighingEvent.objects.create(
            site=scale_base_data["site"],
            session=session,
            device=scale_base_data["device"],
            animal=scale_base_data["animal1"],
            plu_code="1",
            product_name="P",
            weight_grams=3000,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="e1",
        )
        summary = get_session_per_animal_summary(session)
        assert len(summary) == 1
        assert summary[0]["animal"].id == scale_base_data["animal1"].id
        assert summary[0]["total_allocated_grams"] == 3000
        assert summary[0]["effective_event_count"] == 1.0
        assert summary[0]["average_grams"] == 3000

    def test_get_session_per_animal_summary_two_animals_split(self, scale_base_data):
        session = DisassemblySession.objects.create(
            site=scale_base_data["site"],
            device=scale_base_data["device"],
            animal=scale_base_data["animal1"],
            operator="op",
            started_at=timezone.now(),
            status="active",
        )
        session.animals.set([scale_base_data["animal1"], scale_base_data["animal2"]])
        WeighingEvent.objects.create(
            site=scale_base_data["site"],
            session=session,
            device=scale_base_data["device"],
            animal=scale_base_data["animal1"],
            allocation_mode="split",
            plu_code="1",
            product_name="P",
            weight_grams=1000,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="e2",
        )
        summary = get_session_per_animal_summary(session)
        assert len(summary) == 2
        by_id = {row["animal"].id: row for row in summary}
        assert by_id[scale_base_data["animal1"].id]["total_allocated_grams"] == 500
        assert by_id[scale_base_data["animal2"].id]["total_allocated_grams"] == 500
        assert by_id[scale_base_data["animal1"].id]["effective_event_count"] == 0.5
        assert by_id[scale_base_data["animal2"].id]["effective_event_count"] == 0.5


class TestMultiAnimalSession:
    """Test session creation with multiple animals and backward compat."""

    @pytest.fixture(autouse=True)
    def _setup(self, scale_base_data):
        self.site = scale_base_data["site"]
        self.device = scale_base_data["device"]
        self.a1 = scale_base_data["animal1"]
        self.a2 = scale_base_data["animal2"]

    def test_session_create_multi_animal_sets_animals_and_primary(self):
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=self.a1,
            operator="op",
            started_at=timezone.now(),
            status="pending",
        )
        session.animals.set([self.a1, self.a2])
        assert session.animal_id == self.a1.id
        assert set(session.animals.values_list("id", flat=True)) == {self.a1.id, self.a2.id}
        primary = session.get_primary_animal()
        assert primary.id == self.a1.id

    def test_get_primary_animal_fallback_to_animals(self):
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=None,
            operator="op",
            started_at=timezone.now(),
            status="pending",
        )
        session.animals.set([self.a2, self.a1])
        primary = session.get_primary_animal()
        assert primary is not None
        assert primary.id in (self.a1.id, self.a2.id)


class TestEventAnimalStatusTransition:
    """Ensure scale events can auto-transition linked animals to disassembled."""

    @pytest.fixture(autouse=True)
    def _setup(self, scale_base_data):
        self.site = Site.objects.create(name="Transition Site")
        self.edge = EdgeDevice.objects.create(site=self.site, name="Edge-T")
        self.device = ScaleDevice.objects.create(
            edge=self.edge,
            device_id="SCALE-T",
            global_device_id="TEST-SCALE-T",
        )
        user = User.objects.create_user(username="test3", password="test", role=User.Role.CLIENT)
        cp = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="789",
            address="Addr",
        )
        pkg = ServicePackage.objects.create(name="Pkg3", includes_disassembly=True)
        self.order = SlaughterOrder.objects.create(
            client=cp,
            order_datetime=timezone.now(),
            service_package=pkg,
        )
        self.animal = _make_animal(self.order, "TRANS-1")

    def test_mark_disassembled_on_linked_scale_event(self):
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=self.animal,
            operator="op",
            started_at=timezone.now(),
            status="active",
        )
        session.animals.set([self.animal])

        WeightLog.objects.create(
            animal=self.animal,
            slaughter_order=self.order,
            weight=120.5,
            weight_type="hot_carcass_weight",
            is_group_weight=False,
        )

        event = WeighingEvent.objects.create(
            site=self.site,
            session=session,
            device=self.device,
            animal=self.animal,
            plu_code="1",
            product_name="P",
            weight_grams=1000,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="transition-e1",
        )

        transitioned = maybe_mark_event_animals_disassembled(event)
        refreshed = Animal.objects.get(pk=self.animal.pk)
        assert str(self.animal.id) in transitioned
        assert refreshed.status == "disassembled"
