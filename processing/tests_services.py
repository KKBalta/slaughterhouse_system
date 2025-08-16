from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import ServicePackage
from users.models import ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal, WeightLog, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails
from inventory.models import Carcass, MeatCut, Offal, ByProduct
from processing.services import (
    create_animal, mark_animal_slaughtered, create_carcass_from_slaughter, 
    log_individual_weight, disassemble_carcass, update_animal_details, 
    log_group_weight, package_animal_products, deliver_animal_products, 
    return_animal_to_owner, update_animal_metadata, record_cold_carcass_weight, 
    record_initial_byproducts, prepare_animal_carcass
)
from datetime import date
from django.utils import timezone
from django.core.exceptions import ValidationError

User = get_user_model()

class ProcessingServiceTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='testclient', role=User.Role.CLIENT)
        self.client_profile = ClientProfile.objects.create(user=self.user, account_type='INDIVIDUAL', phone_number='123', address='abc')
        self.service_package = ServicePackage.objects.create(name='Full Service', includes_disassembly=True, includes_delivery=True)
        self.order = SlaughterOrder.objects.create(client=self.client_profile, service_package=self.service_package, order_datetime=timezone.now())
        self.animal = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')

    def test_mark_animal_slaughtered_and_create_carcass_service(self):
        self.assertEqual(self.animal.status, 'received')
        
        # Test mark_animal_slaughtered
        slaughtered_animal = mark_animal_slaughtered(animal=self.animal)
        self.assertEqual(slaughtered_animal.status, 'slaughtered')
        self.assertIsNotNone(slaughtered_animal.slaughter_date)

        # Test create_carcass_from_slaughter
        carcass = create_carcass_from_slaughter(
            animal=slaughtered_animal,
            hot_carcass_weight=250.5,
            disposition='for_sale'
        )

        self.assertIsInstance(carcass, Carcass)
        self.assertEqual(Carcass.objects.count(), 1)
        self.assertEqual(carcass.animal, slaughtered_animal)
        self.assertEqual(carcass.hot_carcass_weight, 250.5)
        self.assertEqual(carcass.status, 'chilling') # Default status

    def test_log_individual_weight_service(self):
        weight_log = log_individual_weight(
            animal=self.animal,
            weight_type='Live Weight',
            weight=500.75
        )
        
        self.assertIsInstance(weight_log, WeightLog)
        self.assertEqual(WeightLog.objects.count(), 1)
        self.assertEqual(weight_log.animal, self.animal)
        self.assertEqual(weight_log.weight, 500.75)

    def test_disassemble_carcass_service(self):
        # Setup animal and carcass in the correct state
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()
        carcass = Carcass.objects.create(animal=self.animal, hot_carcass_weight=250.0, disposition='returned_to_owner')

        self.assertEqual(self.animal.status, 'carcass_ready')

        meat_cuts_data = [
            {'cut_type': MeatCut.BeefCuts.RIBEYE, 'weight': 10.5, 'disposition': 'returned_to_owner'},
            {'cut_type': MeatCut.BeefCuts.BRISKET, 'weight': 15.0, 'disposition': 'returned_to_owner'}
        ]
        offal_data = [
            {'offal_type': Offal.BeefOffalTypes.LIVER, 'weight': 5.2, 'disposition': 'returned_to_owner'}
        ]
        by_products_data = [
            {'byproduct_type': ByProduct.ByProductTypes.SKIN, 'disposition': 'disposed'}
        ]

        result = disassemble_carcass(
            animal=self.animal,
            meat_cuts_data=meat_cuts_data,
            offal_data=offal_data,
            by_products_data=by_products_data
        )

        # Assertions
        updated_animal = Animal.objects.get(pk=self.animal.pk)
        self.assertEqual(updated_animal.status, 'disassembled')

        updated_carcass = Carcass.objects.get(pk=carcass.pk)
        self.assertEqual(updated_carcass.status, 'disassembly_ready')

        self.assertEqual(result['meat_cuts_count'], 2)
        self.assertEqual(result['offal_count'], 1)
        self.assertEqual(result['by_products_count'], 1)

        self.assertEqual(MeatCut.objects.count(), 2)
        self.assertEqual(Offal.objects.count(), 1)
        self.assertEqual(ByProduct.objects.count(), 1)

    def test_update_animal_details_service(self):
        # Create CattleDetails for the animal
        CattleDetails.objects.create(animal=self.animal, breed='Old Breed', horn_status='Horned')

        details_data = {'breed': 'New Breed', 'horn_status': 'Polled'}
        updated_animal = update_animal_details(animal=self.animal, details_data=details_data)

        self.assertEqual(updated_animal.cattle_details.breed, 'New Breed')
        self.assertEqual(updated_animal.cattle_details.horn_status, 'Polled')

        

    def test_log_group_weight_service(self):
        group_weight_log = log_group_weight(
            slaughter_order=self.order,
            weight=1000.0,
            weight_type='Live Group',
            group_quantity=5,
            group_total_weight=5000.0
        )

        self.assertIsInstance(group_weight_log, WeightLog)
        self.assertEqual(WeightLog.objects.count(), 1)
        self.assertEqual(group_weight_log.slaughter_order, self.order)
        self.assertTrue(group_weight_log.is_group_weight)
        self.assertEqual(group_weight_log.group_quantity, 5)

    def test_package_animal_products_service(self):
        # Setup animal to carcass_ready state
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()

        packaged_animal = package_animal_products(animal=self.animal)
        self.assertEqual(packaged_animal.status, 'packaged')

    def test_deliver_animal_products_service(self):
        # Setup animal to packaged state
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.perform_disassembly()
        self.animal.perform_packaging()
        self.animal.save()

        delivered_animal = deliver_animal_products(animal=self.animal)
        self.assertEqual(delivered_animal.status, 'delivered')

    def test_return_animal_to_owner_service(self):
        # Setup animal to any state
        self.animal.perform_slaughter()
        self.animal.save()

        returned_animal = return_animal_to_owner(animal=self.animal)
        self.assertEqual(returned_animal.status, 'returned')

    def test_update_animal_metadata_service(self):
        updated_animal = update_animal_metadata(animal=self.animal, leather_weight_kg=123.45)
        self.assertEqual(updated_animal.leather_weight_kg, 123.45)

        updated_animal = update_animal_metadata(animal=self.animal, identification_tag='NEW-TAG-001')
        self.assertEqual(updated_animal.identification_tag, 'NEW-TAG-001')

    def test_record_cold_carcass_weight_service(self):
        # Setup animal to carcass_ready state
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()
        carcass = Carcass.objects.create(animal=self.animal, hot_carcass_weight=250.0, disposition='for_sale')

        self.assertEqual(carcass.status, 'chilling')
        self.assertIsNone(carcass.cold_carcass_weight)

        updated_carcass = record_cold_carcass_weight(carcass=carcass, cold_carcass_weight=245.0)

        self.assertEqual(updated_carcass.cold_carcass_weight, 245.0)
        self.assertEqual(updated_carcass.status, 'disassembly_ready')

    def test_record_initial_byproducts_service(self):
        # Test for cattle (should track offal/byproducts)
        offal_data_cattle = [{'offal_type': Offal.BeefOffalTypes.LIVER, 'weight': 5.0}]
        by_products_data_cattle = [{'byproduct_type': ByProduct.ByProductTypes.SKIN}]
        
        result_cattle = record_initial_byproducts(
            animal=self.animal, 
            offal_data=offal_data_cattle, 
            by_products_data=by_products_data_cattle
        )
        self.assertEqual(result_cattle['offal_count'], 1)
        self.assertEqual(result_cattle['by_products_count'], 1)
        self.assertEqual(Offal.objects.count(), 1)
        self.assertEqual(ByProduct.objects.count(), 1)

        # Test for sheep (should NOT track offal/byproducts)
        sheep_animal = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        offal_data_sheep = [{'offal_type': Offal.LambGoatOffalTypes.HEAD, 'weight': 2.0}]
        
        with self.assertRaises(ValidationError):
            record_initial_byproducts(
                animal=sheep_animal, 
                offal_data=offal_data_sheep, 
                by_products_data=[]
            )

        # Test for calf (should track offal/byproducts)
        calf_animal = Animal.objects.create(slaughter_order=self.order, animal_type='calf')
        offal_data_calf = [{'offal_type': Offal.BeefOffalTypes.HEART, 'weight': 1.5}]
        result_calf = record_initial_byproducts(
            animal=calf_animal, 
            offal_data=offal_data_calf, 
            by_products_data=[]
        )
        self.assertEqual(result_calf['offal_count'], 1)
        self.assertEqual(Offal.objects.count(), 2) # Total count

    def test_create_animal_with_unsupported_details_data(self):
        # Attempt to create an animal type that doesn't have a detail model, but provide details_data
        with self.assertRaises(ValidationError) as cm:
            create_animal(
                order=self.order,
                animal_type='chicken', # Assuming 'chicken' does not have a detail model
                details_data={'feather_color': 'white'},
                identification_tag='CHICKEN-001'
            )
        self.assertIn("Details provided for animal type 'chicken', but no detail model found.", str(cm.exception))
        
        # Ensure no Animal object was created
        self.assertEqual(Animal.objects.filter(animal_type='chicken').count(), 0)

    def test_create_animal_without_details_data_for_supported_type(self):
        # Create an animal type that *does* have a detail model, but don't provide details_data
        # This should succeed without creating a detail model instance
        animal = create_animal(
            order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-002'
        )
        self.assertIsInstance(animal, Animal)
        self.assertEqual(animal.animal_type, 'cattle')
        self.assertEqual(animal.identification_tag, 'CATTLE-002')
        
        # Assert that no CattleDetails object was created for this animal
        with self.assertRaises(CattleDetails.DoesNotExist):
            animal.cattle_details

    def test_disassemble_carcass_invalid_status(self):
        # Animal is in 'received' status, not 'carcass_ready'
        with self.assertRaises(ValidationError) as cm:
            disassemble_carcass(
                animal=self.animal, # Still in 'received' status from setUp
                meat_cuts_data=[],
                offal_data=[],
                by_products_data=[]
            )
        self.assertIn(f"Animal {self.animal.identification_tag} is not ready for disassembly.", str(cm.exception))

    def test_disassemble_carcass_unsupported_offal_byproduct_tracking(self):
        # Setup animal and carcass in the correct state
        sheep_animal = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        sheep_animal.perform_slaughter()
        sheep_animal.prepare_carcass()
        sheep_animal.save()
        Carcass.objects.create(animal=sheep_animal, hot_carcass_weight=50.0, disposition='for_sale')

        # Attempt to disassemble sheep with offal data
        with self.assertRaises(ValidationError) as cm:
            disassemble_carcass(
                animal=sheep_animal,
                meat_cuts_data=[{'cut_type': MeatCut.LambGoatCuts.LEG, 'weight': 5.0, 'disposition': 'returned_to_owner'}],
                offal_data=[{'offal_type': Offal.LambGoatOffalTypes.HEAD, 'weight': 2.0, 'disposition': 'returned_to_owner'}],
                by_products_data=[]
            )
        self.assertIn(f"Offal/Byproduct tracking is not applicable for animal type: sheep during disassembly.", str(cm.exception))

    def test_update_animal_details_no_detail_model(self):
        # Create an animal type that does not have a detail model
        chicken_animal = Animal.objects.create(slaughter_order=self.order, animal_type='chicken')

        # Attempt to update details for it
        with self.assertRaises(ValidationError) as cm:
            update_animal_details(animal=chicken_animal, details_data={'feather_color': 'brown'})
        self.assertIn("No detail model found for animal type: chicken", str(cm.exception))

    # ========================================
    # NEW TESTS FOR ORDER STATUS UPDATES
    # ========================================

    def test_mark_animal_slaughtered_updates_order_status_to_in_progress(self):
        """Test that slaughtering one animal changes order status from PENDING to IN_PROGRESS"""
        # Verify initial state
        self.assertEqual(self.order.status, SlaughterOrder.Status.PENDING)
        self.assertEqual(self.animal.status, 'received')
        
        # Slaughter the animal
        slaughtered_animal = mark_animal_slaughtered(animal=self.animal)
        
        # Refresh order from database to get updated status
        self.order.refresh_from_db()
        
        # Verify animal status changed
        self.assertEqual(slaughtered_animal.status, 'slaughtered')
        
        # Verify order status changed to IN_PROGRESS
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_multiple_animals_slaughter_maintains_in_progress_status(self):
        """Test that slaughtering multiple animals keeps order in IN_PROGRESS"""
        # Create additional animals
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='goat')
        
        # Verify initial state
        self.assertEqual(self.order.status, SlaughterOrder.Status.PENDING)
        
        # Slaughter first animal
        mark_animal_slaughtered(animal=self.animal)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)
        
        # Slaughter second animal
        mark_animal_slaughtered(animal=animal2)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)
        
        # Slaughter third animal
        mark_animal_slaughtered(animal=animal3)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_prepare_animal_carcass_updates_order_status(self):
        """Test that preparing carcass updates order status correctly"""
        # First slaughter the animal
        mark_animal_slaughtered(animal=self.animal)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)
        
        # Prepare carcass
        prepared_animal = prepare_animal_carcass(animal=self.animal)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify animal status changed
        self.assertEqual(prepared_animal.status, 'carcass_ready')
        
        # Verify order status remains IN_PROGRESS
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_package_animal_products_updates_order_status(self):
        """Test that packaging animal products updates order status"""
        # Setup animal to carcass_ready state
        mark_animal_slaughtered(animal=self.animal)
        prepare_animal_carcass(animal=self.animal)
        
        # Package the animal products
        packaged_animal = package_animal_products(animal=self.animal)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify animal status changed
        self.assertEqual(packaged_animal.status, 'packaged')
        
        # Verify order status remains IN_PROGRESS
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_deliver_single_animal_completes_order(self):
        """Test that delivering the only animal in an order changes status to COMPLETED"""
        # Setup animal to packaged state
        mark_animal_slaughtered(animal=self.animal)
        prepare_animal_carcass(animal=self.animal)
        package_animal_products(animal=self.animal)
        
        # Deliver the animal products
        delivered_animal = deliver_animal_products(animal=self.animal)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify animal status changed
        self.assertEqual(delivered_animal.status, 'delivered')
        
        # Verify order status changed to COMPLETED
        self.assertEqual(self.order.status, SlaughterOrder.Status.COMPLETED)

    def test_deliver_all_animals_completes_order(self):
        """Test that delivering all animals in an order changes status to COMPLETED"""
        # Create additional animals
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='goat')
        
        # Process all animals to delivered state
        for animal in [self.animal, animal2, animal3]:
            mark_animal_slaughtered(animal=animal)
            prepare_animal_carcass(animal=animal)
            package_animal_products(animal=animal)
            deliver_animal_products(animal=animal)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify all animals are delivered by fetching fresh instances
        fresh_animals = Animal.objects.filter(slaughter_order=self.order)
        for animal in fresh_animals:
            self.assertEqual(animal.status, 'delivered')
        
        # Verify order status changed to COMPLETED
        self.assertEqual(self.order.status, SlaughterOrder.Status.COMPLETED)

    def test_return_animal_to_owner_updates_order_status(self):
        """Test that returning animal to owner updates order status correctly"""
        # Slaughter the animal first
        mark_animal_slaughtered(animal=self.animal)
        
        # Return animal to owner
        returned_animal = return_animal_to_owner(animal=self.animal)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify animal status changed
        self.assertEqual(returned_animal.status, 'returned')
        
        # Verify order status changed to COMPLETED (since all animals are final state)
        self.assertEqual(self.order.status, SlaughterOrder.Status.COMPLETED)

    def test_mixed_animal_statuses_order_completion(self):
        """Test order completion with mixed final animal statuses (delivered/returned/disposed)"""
        # Create additional animals
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='goat')
        
        # Process animals to different final states
        # Animal 1: delivered
        mark_animal_slaughtered(animal=self.animal)
        prepare_animal_carcass(animal=self.animal)
        package_animal_products(animal=self.animal)
        deliver_animal_products(animal=self.animal)
        
        # Animal 2: returned to owner
        mark_animal_slaughtered(animal=animal2)
        return_animal_to_owner(animal=animal2)
        
        # Animal 3: disposed (from received state)
        animal3.dispose_animal()
        animal3.save()
        
        # Manually trigger order status update for the last animal
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(self.order)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify all animals are in final states by fetching fresh instances
        fresh_animal1 = Animal.objects.get(id=self.animal.id)
        fresh_animal2 = Animal.objects.get(id=animal2.id)
        fresh_animal3 = Animal.objects.get(id=animal3.id)
        
        self.assertEqual(fresh_animal1.status, 'delivered')
        self.assertEqual(fresh_animal2.status, 'returned')
        self.assertEqual(fresh_animal3.status, 'disposed')
        
        # Verify order status changed to COMPLETED
        self.assertEqual(self.order.status, SlaughterOrder.Status.COMPLETED)

    def test_partial_completion_maintains_in_progress(self):
        """Test that partial completion keeps order in IN_PROGRESS status"""
        # Create additional animals
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='sheep')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='goat')
        
        # Process only first animal to completion
        mark_animal_slaughtered(animal=self.animal)
        prepare_animal_carcass(animal=self.animal)
        package_animal_products(animal=self.animal)
        deliver_animal_products(animal=self.animal)
        
        # Process second animal partially
        mark_animal_slaughtered(animal=animal2)
        
        # Leave third animal in received state
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify order status is still IN_PROGRESS
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_order_status_update_with_no_animals(self):
        """Test order status update when order has no animals"""
        # Create order with no animals
        empty_order = SlaughterOrder.objects.create(
            client=self.client_profile, 
            service_package=self.service_package, 
            order_datetime=timezone.now()
        )
        
        # Manually trigger order status update
        from reception.services import update_order_status_from_animals
        updated_order = update_order_status_from_animals(empty_order)
        
        # Verify order status remains PENDING
        self.assertEqual(updated_order.status, SlaughterOrder.Status.PENDING)

    def test_batch_slaughter_order_status_update(self):
        """Test order status update during batch slaughter operations"""
        # Create multiple animals for batch processing
        animals = []
        for i in range(5):
            animal = Animal.objects.create(
                slaughter_order=self.order, 
                animal_type='sheep',
                identification_tag=f'SHEEP-{i+1:03d}'
            )
            animals.append(animal)
        
        # Verify initial order status
        self.assertEqual(self.order.status, SlaughterOrder.Status.PENDING)
        
        # Simulate batch slaughter (like in BatchSlaughterView)
        success_count = 0
        slaughtered_animals = []
        for animal in animals:
            try:
                slaughtered_animal = mark_animal_slaughtered(animal=animal)
                slaughtered_animals.append(slaughtered_animal)
                success_count += 1
            except Exception as e:
                # Print exception details for debugging
                print(f"Failed to slaughter animal {animal.identification_tag}: {e}")
        
        # Verify all animals were slaughtered
        self.assertEqual(success_count, 5)
        
        # Refresh order from database
        self.order.refresh_from_db()
        
        # Verify order status changed to IN_PROGRESS
        self.assertEqual(self.order.status, SlaughterOrder.Status.IN_PROGRESS)
        
        # Verify all animals are slaughtered by checking the returned animals
        for slaughtered_animal in slaughtered_animals:
            self.assertEqual(slaughtered_animal.status, 'slaughtered')

    def test_service_without_delivery_completion(self):
        """Test order completion for service packages without delivery"""
        # Create service package without delivery
        simple_service = ServicePackage.objects.create(
            name='Simple Service', 
            includes_disassembly=False, 
            includes_delivery=False
        )
        
        # Create order with simple service
        simple_order = SlaughterOrder.objects.create(
            client=self.client_profile, 
            service_package=simple_service, 
            order_datetime=timezone.now()
        )
        
        # Create animal for this order
        simple_animal = Animal.objects.create(slaughter_order=simple_order, animal_type='sheep')
        
        # Process animal through slaughter and packaging only
        mark_animal_slaughtered(animal=simple_animal)
        prepare_animal_carcass(animal=simple_animal)
        package_animal_products(animal=simple_animal)
        
        # For simple service, packaged might be final state
        # Refresh order from database
        simple_order.refresh_from_db()
        
        # Verify order status is IN_PROGRESS (since animal is in packaged, not final state)
        self.assertEqual(simple_order.status, SlaughterOrder.Status.IN_PROGRESS)

    def test_log_group_weight_service_enhanced(self):
        """Test the enhanced log_group_weight service with validation"""
        # First, mark some animals as slaughtered
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        
        # Mark them as slaughtered
        mark_animal_slaughtered(animal1)
        mark_animal_slaughtered(animal2)
        mark_animal_slaughtered(animal3)
        
        # Test successful group weight logging
        group_weight_log = log_group_weight(
            slaughter_order=self.order,
            weight=150.0,  # Average weight per animal
            weight_type='Live Weight Group',
            group_quantity=3,
            group_total_weight=450.0  # Total weight
        )

        self.assertIsInstance(group_weight_log, WeightLog)
        self.assertEqual(group_weight_log.slaughter_order, self.order)
        self.assertTrue(group_weight_log.is_group_weight)
        self.assertEqual(group_weight_log.group_quantity, 3)
        self.assertEqual(group_weight_log.group_total_weight, 450.0)
        self.assertEqual(group_weight_log.weight, 150.0)  # Average per animal
        self.assertEqual(group_weight_log.weight_type, 'Live Weight Group')

    def test_log_group_weight_validation_insufficient_animals(self):
        """Test that logging group weight fails when there aren't enough animals in the order"""
        # Only mark one animal as slaughtered
        mark_animal_slaughtered(self.animal)
        
        # Try to log weight for 3 animals when only 1 is slaughtered
        with self.assertRaises(ValueError) as context:
            log_group_weight(
                slaughter_order=self.order,
                weight=150.0,
                weight_type='Live Weight Group',
                group_quantity=3,
                group_total_weight=450.0
            )
        
        self.assertIn("Cannot log weight for 3 animals", str(context.exception))
        self.assertIn("Only 1 animals are available", str(context.exception))

    def test_log_group_weight_auto_individual_creation(self):
        """Test that individual weight logs are created when all animals are weighed"""
        # Mark 4 animals as slaughtered
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal3 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        
        mark_animal_slaughtered(self.animal)
        mark_animal_slaughtered(animal1)
        mark_animal_slaughtered(animal2)
        mark_animal_slaughtered(animal3)
        
        # First batch: 2 animals
        log_group_weight(
            slaughter_order=self.order,
            weight=150.0,
            weight_type='Live Weight Group',
            group_quantity=2,
            group_total_weight=300.0
        )
        
        # Check that no individual logs exist yet
        individual_logs = WeightLog.objects.filter(
            animal__slaughter_order=self.order,
            weight_type='Live Weight',
            is_group_weight=False
        )
        self.assertEqual(individual_logs.count(), 0)
        
        # Second batch: remaining 2 animals (completes all)
        log_group_weight(
            slaughter_order=self.order,
            weight=155.0,
            weight_type='Live Weight Group',
            group_quantity=2,
            group_total_weight=310.0
        )
        
        # Check that individual logs were created automatically
        individual_logs = WeightLog.objects.filter(
            animal__slaughter_order=self.order,
            weight_type='Live Weight',
            is_group_weight=False
        )
        self.assertEqual(individual_logs.count(), 4)  # One for each animal
        
        # Check that the average weight was calculated correctly
        # Total: 300 + 310 = 610kg, Total animals: 4, Average: 152.5kg
        for log in individual_logs:
            self.assertEqual(log.weight, 152.5)

    def test_get_batch_weight_summary_service(self):
        """Test the batch weight summary service"""
        from processing.services import get_batch_weight_summary
        
        # Mark animals as slaughtered
        animal1 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        animal2 = Animal.objects.create(slaughter_order=self.order, animal_type='cattle')
        mark_animal_slaughtered(self.animal)
        mark_animal_slaughtered(animal1)
        mark_animal_slaughtered(animal2)
        
        # Log different types of group weights
        log_group_weight(
            slaughter_order=self.order,
            weight=150.0,
            weight_type='Live Weight Group',
            group_quantity=3,
            group_total_weight=450.0
        )
        
        log_group_weight(
            slaughter_order=self.order,
            weight=120.0,
            weight_type='Hot Carcass Weight Group',
            group_quantity=3,
            group_total_weight=360.0
        )
        
        # Get summary
        summary = get_batch_weight_summary(self.order)
        
        self.assertEqual(summary['order'], self.order)
        self.assertEqual(summary['total_animals'], 3)
        self.assertEqual(summary['total_logs_count'], 2)
        self.assertEqual(len(summary['weight_logs']), 2)
        self.assertEqual(len(summary['weight_progression']), 2)
        
        # Check weight progression data
        progression = summary['weight_progression']
        self.assertEqual(progression[0]['weight_type'], 'Live Weight Group')
        self.assertEqual(progression[0]['total_weight'], 450.0)
        self.assertEqual(progression[0]['average_weight'], 150.0)

    def test_get_batch_weight_reports_service(self):
        """Test the comprehensive batch weight reports service"""
        from processing.services import get_batch_weight_reports
        
        # Create another order for testing
        order2 = SlaughterOrder.objects.create(
            client=self.client_profile, 
            service_package=self.service_package, 
            order_datetime=timezone.now()
        )
        animal_order2 = Animal.objects.create(slaughter_order=order2, animal_type='sheep')
        
        # Mark animals as slaughtered
        mark_animal_slaughtered(self.animal)
        mark_animal_slaughtered(animal_order2)
        
        # Log group weights for both orders
        log_group_weight(
            slaughter_order=self.order,
            weight=150.0,
            weight_type='Live Weight Group',
            group_quantity=1,
            group_total_weight=150.0
        )
        
        log_group_weight(
            slaughter_order=order2,
            weight=45.0,
            weight_type='Live Weight Group',
            group_quantity=1,
            group_total_weight=45.0
        )
        
        # Test general report
        report = get_batch_weight_reports()
        
        self.assertEqual(report['stats']['total_logs'], 2)
        self.assertEqual(report['stats']['total_animals_weighed'], 2)
        self.assertEqual(report['stats']['total_weight_logged'], 195.0)
        self.assertAlmostEqual(report['stats']['average_weight_per_animal'], 97.5)
        
        # Test filtered report by order
        filtered_report = get_batch_weight_reports(order_id=self.order.id)
        
        self.assertEqual(filtered_report['stats']['total_logs'], 1)
        self.assertEqual(filtered_report['stats']['total_animals_weighed'], 1)
        self.assertEqual(filtered_report['stats']['total_weight_logged'], 150.0)
        
        # Test weight type statistics
        self.assertIn('Live Weight Group', report['weight_type_stats'])
        live_weight_stats = report['weight_type_stats']['Live Weight Group']
        self.assertEqual(live_weight_stats['count'], 2)
        self.assertEqual(live_weight_stats['total_animals'], 2)
        self.assertEqual(live_weight_stats['total_weight'], 195.0)