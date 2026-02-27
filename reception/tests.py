from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from .models import SlaughterOrder, ServicePackage
from .forms import BatchAnimalForm
from users.models import ClientProfile
from django.utils import timezone

User = get_user_model()

class ReceptionModelTest(TestCase):
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
            name='Standard Slaughter',
            description='Basic slaughter service.'
        )

    def test_create_order_with_registered_client(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),
            service_package=self.service_package
        )
        self.assertEqual(order.client, self.client_profile)
        self.assertEqual(order.service_package, self.service_package)
        self.assertEqual(SlaughterOrder.objects.count(), 1)

    def test_create_order_with_walk_in_client(self):
        order = SlaughterOrder.objects.create(
            client_name='John Doe',
            client_phone='555-1234',
            order_datetime=timezone.now(),
            service_package=self.service_package
        )
        self.assertIsNone(order.client)
        self.assertEqual(order.client_name, 'John Doe')
        self.assertEqual(SlaughterOrder.objects.count(), 1)

    def test_client_profile_deletion(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.client_profile.delete()
        order.refresh_from_db()
        self.assertIsNone(order.client)

    def test_service_package_deletion(self):
        order = SlaughterOrder.objects.create(
            client=self.client_profile,
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.service_package.delete()
        order.refresh_from_db()
        self.assertIsNone(order.service_package)

    def test_create_order_with_no_client_info(self):
        # This might be a valid scenario for some internal processes
        order = SlaughterOrder.objects.create(
            order_datetime=timezone.now(),                                                          
            service_package=self.service_package
        )
        self.assertIsNone(order.client)
        self.assertEqual(order.client_name, '')
        self.assertEqual(SlaughterOrder.objects.count(), 1)

class BatchAnimalFormTest(TestCase):
    """Test cases for the BatchAnimalForm"""

    def test_batch_animal_form_valid_data(self):
        """Test form with valid data"""
        form_data = {
            'animal_type': 'cattle',
            'quantity': 10,
            'tag_prefix': 'FARM-001',
            'received_date': timezone.now(),
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_batch_animal_form_minimum_quantity(self):
        """Test form with minimum valid quantity"""
        form_data = {
            'animal_type': 'sheep',
            'quantity': 1,
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_batch_animal_form_maximum_quantity(self):
        """Test form with maximum valid quantity"""
        form_data = {
            'animal_type': 'goat',
            'quantity': 100,
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())

    @override_settings(LANGUAGE_CODE='en')
    def test_batch_animal_form_invalid_quantity_too_high(self):
        """Test form with quantity exceeding maximum"""
        form_data = {
            'animal_type': 'cattle',
            'quantity': 101,  # Exceeds maximum
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)
        # Check for either custom validation message or Django's built-in message
        error_message = str(form.errors['quantity'])
        self.assertTrue(
            'Maximum 100 animals' in error_message or 
            'less than or equal to 100' in error_message
        )

    def test_batch_animal_form_invalid_quantity_zero(self):
        """Test form with zero quantity"""
        form_data = {
            'animal_type': 'lamb',
            'quantity': 0,  # Invalid
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_batch_animal_form_invalid_quantity_negative(self):
        """Test form with negative quantity"""
        form_data = {
            'animal_type': 'oglak',
            'quantity': -5,  # Invalid
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_batch_animal_form_missing_required_fields(self):
        """Test form with missing required fields"""
        form_data = {
            'tag_prefix': 'TEST',
            # Missing animal_type and quantity
        }
        form = BatchAnimalForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('animal_type', form.errors)
        self.assertIn('quantity', form.errors)

    def test_batch_animal_form_optional_fields(self):
        """Test form with only required fields"""
        form_data = {
            'animal_type': 'cattle',
            'quantity': 5,
            # tag_prefix, received_date, and skip_photos are optional
        }
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())
        
        # Check default values
        self.assertEqual(form.cleaned_data.get('tag_prefix'), '')  # Empty string, not None
        self.assertIsNone(form.cleaned_data.get('received_date'))
        self.assertFalse(form.cleaned_data.get('skip_photos'))

    def test_batch_animal_form_tag_prefix_validation(self):
        """Test tag prefix validation"""
        # Test with valid tag prefix
        form_data = {
            'animal_type': 'sheep',
            'quantity': 3,
            'tag_prefix': 'VALID-PREFIX',
            'skip_photos': True
        }
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())

        # Test with empty tag prefix (should be valid)
        form_data['tag_prefix'] = ''
        form = BatchAnimalForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_batch_animal_form_all_animal_types(self):
        """Test form with all available animal types"""
        from processing.models import Animal
        
        for animal_type, _ in Animal.ANIMAL_TYPES:
            form_data = {
                'animal_type': animal_type,
                'quantity': 2,
                'skip_photos': True
            }
            form = BatchAnimalForm(data=form_data)
            self.assertTrue(form.is_valid(), f"Form should be valid for animal type: {animal_type}")

    def test_batch_animal_form_widget_attributes(self):
        """Test that form widgets have correct CSS classes"""
        form = BatchAnimalForm()
        
        # Test animal_type widget
        self.assertIn('modern-select-full', form.fields['animal_type'].widget.attrs.get('class', ''))
        
        # Test quantity widget
        quantity_attrs = form.fields['quantity'].widget.attrs
        self.assertIn('w-full', quantity_attrs.get('class', ''))
        self.assertIn('px-3', quantity_attrs.get('class', ''))
        
        # Test tag_prefix widget
        tag_prefix_attrs = form.fields['tag_prefix'].widget.attrs
        self.assertIn('w-full', tag_prefix_attrs.get('class', ''))
        
        # Test skip_photos widget
        skip_photos_attrs = form.fields['skip_photos'].widget.attrs
        self.assertIn('h-4', skip_photos_attrs.get('class', ''))

    @override_settings(LANGUAGE_CODE='en')
    def test_batch_animal_form_field_labels(self):
        """Test that form fields have correct labels"""
        form = BatchAnimalForm()
        
        self.assertEqual(form.fields['animal_type'].label, 'Animal Type')
        self.assertEqual(form.fields['quantity'].label, 'Number of Animals')
        self.assertEqual(form.fields['tag_prefix'].label, 'Tag Prefix (Optional)')
        self.assertEqual(form.fields['received_date'].label, 'Received Date & Time')
        self.assertEqual(form.fields['skip_photos'].label, 'Skip Photos for Batch')

    @override_settings(LANGUAGE_CODE='en')
    def test_batch_animal_form_help_text(self):
        """Test that form fields have appropriate help text"""
        form = BatchAnimalForm()
        
        self.assertIn('Custom prefix for identification tags', form.fields['tag_prefix'].help_text)
        self.assertIn('Leave empty to use current date/time', form.fields['received_date'].help_text)
        self.assertIn('photos can be added later', form.fields['skip_photos'].help_text)