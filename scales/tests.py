"""Tests for scales app: multi-animal sessions, allocation, backward compatibility."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from processing.models import Animal, WeightLog
from reception.models import ServicePackage, SlaughterOrder
from scales.models import DisassemblySession, EdgeDevice, ScaleDevice, Site, WeighingEvent
from scales.utils import get_event_allocation, get_session_per_animal_summary, maybe_mark_event_animals_disassembled
from users.models import ClientProfile

User = get_user_model()


def _make_animal(slaughter_order, tag="TAG-1", animal_type="cattle"):
    """Create an animal in carcass_ready so it's eligible for scale sessions."""
    a = Animal.objects.create(
        slaughter_order=slaughter_order,
        animal_type=animal_type,
        identification_tag=tag,
    )
    a.perform_slaughter()
    a.save()
    a.prepare_carcass()
    a.save()
    return a


class AllocationUtilsTest(TestCase):
    """Test get_event_allocation and get_session_per_animal_summary."""

    def setUp(self):
        self.site = Site.objects.create(name="Test Site")
        self.edge = EdgeDevice.objects.create(site=self.site, name="Edge1")
        self.device = ScaleDevice.objects.create(
            edge=self.edge,
            device_id="SCALE-01",
            global_device_id="TEST-SCALE-01",
        )
        user = User.objects.create_user(username="test", password="test", role=User.Role.CLIENT)
        self.client_profile = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="123",
            address="Addr",
        )
        self.service_package = ServicePackage.objects.create(
            name="Pkg",
            includes_disassembly=True,
        )
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.service_package,
        )
        self.animal1 = _make_animal(self.order, "TAG-1")
        self.animal2 = _make_animal(self.order, "TAG-2")
        self.animals_ordered = [self.animal1, self.animal2]

    def test_get_event_allocation_split(self):
        """Split: weight divided evenly; remainder to first animals by id order."""

        class MockEvent:
            weight_grams = 1000
            assigned_animal_id = None
            assigned_animal = None

        alloc = get_event_allocation(MockEvent(), self.animals_ordered)
        self.assertEqual(alloc[str(self.animal1.id)], 500)
        self.assertEqual(alloc[str(self.animal2.id)], 500)

        MockEvent.weight_grams = 1001
        alloc = get_event_allocation(MockEvent(), self.animals_ordered)
        self.assertEqual(alloc[str(self.animal1.id)], 501)
        self.assertEqual(alloc[str(self.animal2.id)], 500)
        self.assertEqual(sum(alloc.values()), 1001)

    def test_get_event_allocation_manual(self):
        """Manual: full weight to assigned_animal only."""

        class MockEvent:
            weight_grams = 600
            assigned_animal_id = None
            assigned_animal = None

        MockEvent.assigned_animal_id = self.animal2.id
        alloc = get_event_allocation(MockEvent(), self.animals_ordered)
        self.assertEqual(alloc[str(self.animal1.id)], 0)
        self.assertEqual(alloc[str(self.animal2.id)], 600)

    def test_get_session_per_animal_summary_single_animal(self):
        """Session with one animal: all weight to that animal."""
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=self.animal1,
            operator="op",
            started_at=timezone.now(),
            status="active",
        )
        session.animals.set([self.animal1])
        WeighingEvent.objects.create(
            site=self.site,
            session=session,
            device=self.device,
            animal=self.animal1,
            plu_code="1",
            product_name="P",
            weight_grams=3000,
            barcode="",
            scale_timestamp=timezone.now(),
            edge_received_at=timezone.now(),
            edge_event_id="e1",
        )
        summary = get_session_per_animal_summary(session)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["animal"].id, self.animal1.id)
        self.assertEqual(summary[0]["total_allocated_grams"], 3000)
        self.assertEqual(summary[0]["effective_event_count"], 1.0)
        self.assertEqual(summary[0]["average_grams"], 3000)

    def test_get_session_per_animal_summary_two_animals_split(self):
        """Session with two animals, one event: split evenly."""
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=self.animal1,
            operator="op",
            started_at=timezone.now(),
            status="active",
        )
        session.animals.set([self.animal1, self.animal2])
        WeighingEvent.objects.create(
            site=self.site,
            session=session,
            device=self.device,
            animal=self.animal1,
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
        self.assertEqual(len(summary), 2)
        by_id = {row["animal"].id: row for row in summary}
        self.assertEqual(by_id[self.animal1.id]["total_allocated_grams"], 500)
        self.assertEqual(by_id[self.animal2.id]["total_allocated_grams"], 500)
        self.assertEqual(by_id[self.animal1.id]["effective_event_count"], 0.5)
        self.assertEqual(by_id[self.animal2.id]["effective_event_count"], 0.5)


class MultiAnimalSessionTest(TestCase):
    """Test session creation with multiple animals and backward compat."""

    def setUp(self):
        self.site = Site.objects.create(name="Test Site")
        self.edge = EdgeDevice.objects.create(site=self.site, name="Edge1")
        self.device = ScaleDevice.objects.create(
            edge=self.edge,
            device_id="SCALE-01",
            global_device_id="TEST-SCALE-02",
        )
        user = User.objects.create_user(username="test2", password="test", role=User.Role.CLIENT)
        cp = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="456",
            address="Addr",
        )
        pkg = ServicePackage.objects.create(name="Pkg2", includes_disassembly=True)
        self.order = SlaughterOrder.objects.create(
            client=cp,
            order_datetime=timezone.now(),
            service_package=pkg,
        )
        self.a1 = _make_animal(self.order, "A1")
        self.a2 = _make_animal(self.order, "A2")

    def test_session_create_multi_animal_sets_animals_and_primary(self):
        """Creating a session with two animals sets M2M and animal FK to first."""
        session = DisassemblySession.objects.create(
            site=self.site,
            device=self.device,
            animal=self.a1,
            operator="op",
            started_at=timezone.now(),
            status="pending",
        )
        session.animals.set([self.a1, self.a2])
        self.assertEqual(session.animal_id, self.a1.id)
        self.assertEqual(set(session.animals.values_list("id", flat=True)), {self.a1.id, self.a2.id})
        primary = session.get_primary_animal()
        self.assertEqual(primary.id, self.a1.id)

    def test_get_primary_animal_fallback_to_animals(self):
        """When animal FK is null, get_primary_animal returns first from animals."""
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
        self.assertIsNotNone(primary)
        self.assertIn(primary.id, (self.a1.id, self.a2.id))


class EventAnimalStatusTransitionTest(TestCase):
    """Ensure scale events can auto-transition linked animals to disassembled."""

    def setUp(self):
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
        self.assertIn(str(self.animal.id), transitioned)
        self.assertEqual(refreshed.status, "disassembled")
