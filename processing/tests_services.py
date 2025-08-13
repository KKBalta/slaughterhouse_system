from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import ServicePackage
from users.models import ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal, WeightLog, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails
from inventory.models import Carcass, MeatCut, Offal, ByProduct
from processing.services import create_animal, mark_animal_slaughtered, create_carcass_from_slaughter, log_individual_weight, disassemble_carcass, update_animal_details, log_group_weight, package_animal_products, deliver_animal_products, return_animal_to_owner, update_animal_metadata, record_cold_carcass_weight, record_initial_byproducts
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