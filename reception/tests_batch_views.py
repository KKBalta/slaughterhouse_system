from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from core.models import ServicePackage
from users.models import ClientProfile
from reception.models import SlaughterOrder
from reception.services import create_slaughter_order
import json

User = get_user_model()

class BatchAnimalViewTest(TestCase):
    """Test cases for BatchAddAnimalsToOrderView"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role=User.Role.STAFF
        )
        self.client_profile = ClientProfile.objects.create(
            user=self.user,
            account_type='INDIVIDUAL',
            phone_number='1234567890',
            address='123 Test St'
        )
        self.service_package = ServicePackage.objects.create(
            name='Test Service',
            includes_slaughter=True
        )
        self.order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )

    def test_batch_add_animals_get_requires_login(self):
        """Test that GET request requires authentication"""
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_batch_add_animals_get_authenticated(self):
        """Test GET request with authenticated user"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch Add Animals')
        self.assertContains(response, self.order.slaughter_order_no)
        self.assertContains(response, 'form')

    def test_batch_add_animals_post_valid_data(self):
        """Test POST request with valid data"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        post_data = {
            'animal_type': 'cattle',
            'quantity': 5,
            'tag_prefix': 'TEST',
            'skip_photos': True
        }
        
        response = self.client.post(url, data=post_data)
        
        # Should redirect to order detail page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('reception:slaughter_order_detail', kwargs={'pk': self.order.pk}))
        
        # Check that animals were created
        self.order.refresh_from_db()
        self.assertEqual(self.order.animals.count(), 5)
        
        # Check tags
        tags = [animal.identification_tag for animal in self.order.animals.all()]
        expected_tags = ['TEST-001', 'TEST-002', 'TEST-003', 'TEST-004', 'TEST-005']
        self.assertEqual(sorted(tags), sorted(expected_tags))

    def test_batch_add_animals_post_invalid_data(self):
        """Test POST request with invalid data"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        post_data = {
            'animal_type': 'cattle',
            'quantity': 101,  # Invalid - exceeds maximum
            'skip_photos': True
        }
        
        response = self.client.post(url, data=post_data)
        
        # Should return form with errors
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maximum 100 animals')
        
        # No animals should be created
        self.assertEqual(self.order.animals.count(), 0)

    def test_batch_add_animals_post_missing_required_fields(self):
        """Test POST request with missing required fields"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        post_data = {
            'tag_prefix': 'TEST',
            # Missing animal_type and quantity
        }
        
        response = self.client.post(url, data=post_data)
        
        # Should return form with errors
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'animal_type', 'This field is required.')
        self.assertFormError(response, 'form', 'quantity', 'This field is required.')

    def test_batch_add_animals_invalid_order_status(self):
        """Test batch add with non-pending order"""
        self.client.login(username='testuser', password='testpass123')
        
        # Change order status to IN_PROGRESS
        self.order.status = SlaughterOrder.Status.IN_PROGRESS
        self.order.save()
        
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        post_data = {
            'animal_type': 'cattle',
            'quantity': 3,
            'skip_photos': True
        }
        
        response = self.client.post(url, data=post_data)
        
        # Should return form with error message
        self.assertEqual(response.status_code, 200)
        # Check for error message in response
        messages = list(response.context['messages'])
        self.assertTrue(any('Can only add animals to a PENDING order' in str(message) for message in messages))

    def test_batch_add_animals_nonexistent_order(self):
        """Test batch add with nonexistent order"""
        self.client.login(username='testuser', password='testpass123')
        
        from uuid import uuid4
        fake_uuid = uuid4()
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': fake_uuid})
        
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_batch_add_animals_different_animal_types(self):
        """Test batch creation with different animal types"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        animal_types = ['cattle', 'sheep', 'goat', 'lamb']
        
        for animal_type in animal_types:
            post_data = {
                'animal_type': animal_type,
                'quantity': 2,
                'tag_prefix': f'{animal_type.upper()}',
                'skip_photos': True
            }
            
            response = self.client.post(url, data=post_data)
            self.assertEqual(response.status_code, 302)
        
        # Should have 8 animals total
        self.order.refresh_from_db()
        self.assertEqual(self.order.animals.count(), 8)
        
        # Check distribution by type
        for animal_type in animal_types:
            count = self.order.animals.filter(animal_type=animal_type).count()
            self.assertEqual(count, 2)

    def test_batch_add_animals_with_custom_date(self):
        """Test batch creation with custom received date"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        custom_date = timezone.now() - timezone.timedelta(days=2)
        
        post_data = {
            'animal_type': 'cattle',
            'quantity': 3,
            'received_date': custom_date.strftime('%Y-%m-%dT%H:%M'),
            'skip_photos': True
        }
        
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        
        # Check that all animals have the custom date
        self.order.refresh_from_db()
        for animal in self.order.animals.all():
            self.assertEqual(animal.received_date.date(), custom_date.date())

    def test_batch_add_animals_success_message(self):
        """Test that success message is displayed after batch creation"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        post_data = {
            'animal_type': 'sheep',
            'quantity': 7,
            'tag_prefix': 'FARM',
            'skip_photos': True
        }
        
        response = self.client.post(url, data=post_data, follow=True)
        
        # Check success message
        messages = list(response.context['messages'])
        success_messages = [msg for msg in messages if msg.tags == 'success']
        self.assertTrue(len(success_messages) > 0)
        self.assertIn('Successfully created 7 sheep animals', str(success_messages[0]))
        self.assertIn(self.order.slaughter_order_no, str(success_messages[0]))

    def test_batch_add_animals_template_context(self):
        """Test that template receives correct context"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': self.order.pk})
        
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)
        self.assertIn('order', response.context)
        self.assertEqual(response.context['order'], self.order)
        
        # Check that form is an instance of BatchAnimalForm
        from reception.forms import BatchAnimalForm
        self.assertIsInstance(response.context['form'], BatchAnimalForm)

class BatchAnimalIntegrationTest(TestCase):
    """Integration tests for batch animal functionality"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            role=User.Role.STAFF
        )
        self.client_profile = ClientProfile.objects.create(
            user=self.user,
            account_type='INDIVIDUAL',
            phone_number='1234567890',
            address='123 Test St'
        )
        self.service_package = ServicePackage.objects.create(
            name='Test Service',
            includes_slaughter=True
        )

    def test_batch_add_button_appears_on_order_detail(self):
        """Test that batch add button appears on order detail page"""
        self.client.login(username='testuser', password='testpass123')
        
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )
        
        url = reverse('reception:slaughter_order_detail', kwargs={'pk': order.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch Add')
        
        # Check that the link is correct
        batch_url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': order.pk})
        self.assertContains(response, batch_url)

    def test_batch_add_button_not_shown_for_non_pending_orders(self):
        """Test that batch add button is not shown for non-pending orders"""
        self.client.login(username='testuser', password='testpass123')
        
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )
        
        # Change order status
        order.status = SlaughterOrder.Status.COMPLETED
        order.save()
        
        url = reverse('reception:slaughter_order_detail', kwargs={'pk': order.pk})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Batch Add')

    def test_end_to_end_batch_creation_workflow(self):
        """Test complete workflow from order detail to batch creation"""
        self.client.login(username='testuser', password='testpass123')
        
        # Create order
        order = create_slaughter_order(
            client_id=self.client_profile.id,
            service_package_id=self.service_package.id,
            order_datetime=timezone.now(),
            animals_data=[]
        )
        
        # 1. Visit order detail page
        detail_url = reverse('reception:slaughter_order_detail', kwargs={'pk': order.pk})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No animals in this order yet')
        
        # 2. Click batch add button (simulate by going to batch add page)
        batch_url = reverse('reception:batch_add_animals_to_order', kwargs={'order_pk': order.pk})
        response = self.client.get(batch_url)
        self.assertEqual(response.status_code, 200)
        
        # 3. Submit batch creation form
        post_data = {
            'animal_type': 'cattle',
            'quantity': 10,
            'tag_prefix': 'BATCH-TEST',
            'skip_photos': True
        }
        response = self.client.post(batch_url, data=post_data)
        self.assertEqual(response.status_code, 302)
        
        # 4. Verify redirect back to order detail
        self.assertRedirects(response, detail_url)
        
        # 5. Check order detail page now shows animals
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'No animals in this order yet')
        self.assertContains(response, 'BATCH-TEST-001')
        self.assertContains(response, 'BATCH-TEST-010')
        
        # 6. Verify animals were actually created
        order.refresh_from_db()
        self.assertEqual(order.animals.count(), 10)
