"""
View and service tests for the processing app.

Note: Some view tests may be skipped if templates are not available
in the test environment.
"""
import pytest
from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal

from reception.models import SlaughterOrder
from core.models import ServicePackage
from users.models import ClientProfile
from processing.models import Animal, WeightLog, CattleDetails, DisassemblyCut


User = get_user_model()


class ProcessingModelTestMixin:
    """Mixin class providing common setup for processing tests."""
    
    @classmethod
    def setUpTestData(cls):
        """Set up test data for the test class."""
        cls.admin_user = User.objects.create_user(
            username='proc_admin',
            password='testpass123',
            role=User.Role.ADMIN,
            is_staff=True
        )
        cls.operator_user = User.objects.create_user(
            username='proc_operator',
            password='testpass123',
            role=User.Role.OPERATOR
        )
        cls.client_user = User.objects.create_user(
            username='proc_client',
            password='testpass123',
            role=User.Role.CLIENT
        )
        cls.client_profile = ClientProfile.objects.create(
            user=cls.client_user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number='1234567890',
            address='123 Test St'
        )
        
        cls.full_service = ServicePackage.objects.create(
            name='Full Service Proc Test',
            includes_disassembly=True,
            includes_delivery=True
        )
        cls.basic_service = ServicePackage.objects.create(
            name='Basic Service Proc Test',
            includes_disassembly=False,
            includes_delivery=False
        )

    def setUp(self):
        """Set up test client and login."""
        self.test_client = Client()
        self.test_client.login(username='proc_admin', password='testpass123')
        
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.full_service
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='PROC-TEST-001'
        )


class AnimalStatusTransitionTest(ProcessingModelTestMixin, TestCase):
    """Tests for animal status transitions."""
    
    def test_initial_status_is_received(self):
        """Test that new animals start in 'received' status."""
        self.assertEqual(self.animal.status, 'received')
    
    def test_slaughter_transition(self):
        """Test transitioning animal to slaughtered status."""
        self.animal.perform_slaughter()
        self.animal.save()
        
        self.assertEqual(self.animal.status, 'slaughtered')
        self.assertIsNotNone(self.animal.slaughter_date)
    
    def test_carcass_ready_transition(self):
        """Test transitioning to carcass_ready status."""
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()
        
        self.assertEqual(self.animal.status, 'carcass_ready')
    
    def test_full_workflow_with_disassembly(self):
        """Test complete workflow with disassembly."""
        # Slaughter
        self.animal.perform_slaughter()
        self.assertEqual(self.animal.status, 'slaughtered')
        
        # Carcass ready
        self.animal.prepare_carcass()
        self.assertEqual(self.animal.status, 'carcass_ready')
        
        # Log hot carcass weight (required for disassembly transition)
        WeightLog.objects.create(
            animal=self.animal,
            weight=Decimal('300.00'),
            weight_type='hot_carcass_weight'
        )
        
        # Disassembly (requires service package with disassembly + hot carcass weight)
        self.animal.perform_disassembly()
        self.assertEqual(self.animal.status, 'disassembled')
        
        # Packaging
        self.animal.perform_packaging()
        self.assertEqual(self.animal.status, 'packaged')
        
        # Delivery
        self.animal.deliver_product()
        self.animal.save()
        self.assertEqual(self.animal.status, 'delivered')
    
    def test_invalid_transition_blocked(self):
        """Test that invalid transitions are blocked."""
        # Can't prepare carcass before slaughter
        with self.assertRaises(Exception):
            self.animal.prepare_carcass()
    
    def test_disassembly_blocked_without_service(self):
        """Test that disassembly is blocked when not in service package."""
        basic_order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.basic_service
        )
        basic_animal = Animal.objects.create(
            slaughter_order=basic_order,
            animal_type='cattle',
            identification_tag='BASIC-TEST-001'
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
            animal=self.animal,
            weight=Decimal('500.00'),
            weight_type='live_weight',
            is_group_weight=False
        )
        
        self.assertEqual(weight_log.animal, self.animal)
        self.assertEqual(weight_log.weight, Decimal('500.00'))
    
    def test_log_hot_carcass_weight(self):
        """Test logging hot carcass weight after slaughter."""
        self.animal.perform_slaughter()
        self.animal.save()
        
        weight_log = WeightLog.objects.create(
            animal=self.animal,
            weight=Decimal('300.00'),
            weight_type='hot_carcass_weight',
            is_group_weight=False
        )
        
        self.assertEqual(weight_log.weight_type, 'hot_carcass_weight')
    
    def test_group_weight_log(self):
        """Test creating a group weight log."""
        weight_log = WeightLog.objects.create(
            slaughter_order=self.order,
            weight=Decimal('150.00'),
            weight_type='live_weight Group',
            is_group_weight=True,
            group_quantity=5,
            group_total_weight=Decimal('750.00')
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
        cut = DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='ribeye',
            weight_kg=Decimal('5.5')
        )
        
        self.assertEqual(cut.animal, self.animal)
        self.assertEqual(cut.cut_name, 'ribeye')
        self.assertEqual(cut.weight_kg, Decimal('5.5'))
    
    def test_multiple_cuts_per_animal(self):
        """Test creating multiple cuts for one animal."""
        DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='ribeye',
            weight_kg=Decimal('5.5')
        )
        DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='tenderloin',
            weight_kg=Decimal('3.0')
        )
        DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='sirloin',
            weight_kg=Decimal('8.0')
        )
        
        self.assertEqual(self.animal.disassembly_cuts.count(), 3)


class OrderStatusUpdateTest(ProcessingModelTestMixin, TestCase):
    """Tests for order status updates based on animal processing."""
    
    def test_order_status_updates_to_in_progress(self):
        """Test that order status updates when animals are processed."""
        self.assertEqual(self.order.status, 'PENDING')
        
        self.animal.perform_slaughter()
        self.animal.save()
        
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(self.order)
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'IN_PROGRESS')
    
    def test_order_completes_when_all_animals_delivered(self):
        """Test that order completes when all animals are delivered."""
        # Process animal through all stages
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        
        # Log hot carcass weight (required for disassembly)
        WeightLog.objects.create(
            animal=self.animal,
            weight=Decimal('300.00'),
            weight_type='hot_carcass_weight'
        )
        
        self.animal.perform_disassembly()
        self.animal.perform_packaging()
        self.animal.deliver_product()
        self.animal.save()
        
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(self.order)
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'COMPLETED')


# ============================================================================
# Pytest-style tests
# ============================================================================

@pytest.mark.django_db
class TestAnimalWorkflow:
    """Pytest-style tests for animal workflow."""
    
    def test_animal_creation(self, animal_factory):
        """Test creating an animal."""
        animal = animal_factory()
        
        assert animal.status == 'received'
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
        
        animal_types = ['cattle', 'sheep', 'goat', 'lamb', 'oglak', 'calf', 'heifer', 'beef']
        
        for animal_type in animal_types:
            animal = Animal.objects.create(
                slaughter_order=order,
                animal_type=animal_type,
                identification_tag=f'{animal_type.upper()}-TEST'
            )
            assert animal.animal_type == animal_type


@pytest.mark.django_db
class TestWeightLogValidation:
    """Tests for weight log validation."""
    
    def test_individual_weight_log(self, animal_factory):
        """Test creating individual weight log."""
        animal = animal_factory()
        
        log = WeightLog.objects.create(
            animal=animal,
            weight=Decimal('100.00'),
            weight_type='live_weight',
            is_group_weight=False
        )
        
        assert log.animal == animal
        assert not log.is_group_weight
    
    def test_weight_log_requires_animal_or_order(self, db):
        """Test that weight log requires animal or order."""
        from django.core.exceptions import ValidationError
        
        # This should fail during validation
        log = WeightLog(
            weight=Decimal('100.00'),
            weight_type='live_weight'
        )
        
        with pytest.raises(Exception):
            log.full_clean()
            log.save()
