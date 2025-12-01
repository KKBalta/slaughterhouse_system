from django.test import TestCase
from django.contrib.auth import get_user_model
from reception.models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal, DisassemblyCut
from labeling.models import AnimalLabel
from labeling.utils import create_cut_label
from django.utils import timezone
import datetime

User = get_user_model()

class DisassemblyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='password123',
            role=User.Role.CLIENT
        )
        self.client_profile = ClientProfile.objects.create(
            user=self.user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number='1234567890',
            address='123 Test St'
        )
        self.service_package = ServicePackage.objects.create(
            name='Full Processing',
            includes_disassembly=True,
            includes_delivery=True
        )
        self.order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.service_package
        )
        self.animal = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='cattle',
            identification_tag='CATTLE-TEST-001'
        )
        # Move animal to carcass_ready
        self.animal.perform_slaughter()
        self.animal.prepare_carcass()
        self.animal.save()

    def test_add_disassembly_cut(self):
        """Test adding a disassembly cut to an animal."""
        cut = DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='tenderloin',
            weight_kg=10.5
        )
        self.assertEqual(cut.animal, self.animal)
        self.assertEqual(cut.cut_name, 'tenderloin')
        self.assertEqual(cut.weight_kg, 10.5)
        
        # Verify animal status transition if applicable
        # The transition happens in the view, but we can test the method
        if self.animal.status == 'carcass_ready':
            self.animal.perform_disassembly()
            self.animal.save()
        
        self.assertEqual(self.animal.status, 'disassembled')

    def test_cut_choices_validation(self):
        """Test that cut choices are valid for the animal type."""
        # Cattle should have big cut choices
        cut = DisassemblyCut(
            animal=self.animal,
            cut_name='tenderloin',
            weight_kg=5.0
        )
        # This should be valid
        cut.full_clean()
        cut.save()
        
        # Create a sheep
        sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='sheep',
            identification_tag='SHEEP-TEST-001'
        )
        sheep.perform_slaughter()
        sheep.prepare_carcass()
        sheep.save()
        
        # Sheep should have small cut choices
        cut_sheep = DisassemblyCut(
            animal=sheep,
            cut_name='leg',
            weight_kg=2.0
        )
        cut_sheep.full_clean()
        cut_sheep.save()

    def test_generate_cut_label(self):
        """Test generating a label for a cut."""
        cut = DisassemblyCut.objects.create(
            animal=self.animal,
            cut_name='ribeye',
            weight_kg=3.5
        )
        
        # Generate label
        label = create_cut_label(cut, user=self.user)
        
        self.assertIsInstance(label, AnimalLabel)
        self.assertEqual(label.label_type, 'cut')
        self.assertEqual(label.animal, self.animal)
        self.assertTrue(len(label.prn_content) > 0)
        self.assertTrue(len(label.bat_content) > 0)
        self.assertTrue(label.pdf_file)
        
        # Check if PRN content contains cut info
        self.assertIn('RIBEYE', label.prn_content)
        self.assertIn('3.5', label.prn_content)

    def test_disassembly_cut_form_choices(self):
        """Test that DisassemblyCutForm filters choices based on animal type."""
        from processing.forms import DisassemblyCutForm
        
        # Test with Cattle (Big Cut)
        form_cattle = DisassemblyCutForm(animal=self.animal)
        choices_cattle = [c[0] for c in form_cattle.fields['cut_name'].widget.choices]
        self.assertIn('ribeye', choices_cattle)
        self.assertNotIn('leg', choices_cattle) # 'leg' is a small cut
        
        # Test with Sheep (Small Cut)
        sheep = Animal.objects.create(
            slaughter_order=self.order,
            animal_type='sheep',
            identification_tag='SHEEP-FORM-TEST'
        )
        form_sheep = DisassemblyCutForm(animal=sheep)
        choices_sheep = [c[0] for c in form_sheep.fields['cut_name'].widget.choices]
        self.assertIn('leg', choices_sheep)
        self.assertNotIn('ribeye', choices_sheep) # 'ribeye' is a big cut
