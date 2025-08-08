from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import ClientProfile

User = get_user_model()

class UserModelTest(TestCase):
    def test_create_user(self):
        """Test creating a new user."""
        user = User.objects.create_user(
            username='testuser',
            password='password123',
            email='test@example.com',
            first_name='Test',
            last_name='User'
        )
        self.assertEqual(user.username, 'testuser')
        self.assertEqual(user.email, 'test@example.com')
        self.assertEqual(user.first_name, 'Test')
        self.assertEqual(user.last_name, 'User')
        self.assertTrue(user.check_password('password123'))
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_create_superuser(self):
        """Test creating a new superuser."""
        superuser = User.objects.create_superuser(
            username='superuser',
            password='password123',
            email='superuser@example.com'
        )
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_staff)
        self.assertEqual(superuser.role, User.Role.ADMIN)

class ClientProfileModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='clientuser',
            password='password123',
            email='client@example.com',
            first_name='Client',
            last_name='User',
            role=User.Role.CLIENT
        )

    def test_create_individual_client_profile(self):
        """Test creating a client profile for an individual."""
        profile = ClientProfile.objects.create(
            user=self.user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number='1234567890',
            address='123 Main St'
        )
        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.account_type, ClientProfile.AccountType.INDIVIDUAL)
        self.assertEqual(str(profile), f"{self.user.get_full_name()} (Individual)")

    def test_create_enterprise_client_profile(self):
        """Test creating a client profile for an enterprise."""
        profile = ClientProfile.objects.create(
            user=self.user,
            account_type=ClientProfile.AccountType.ENTERPRISE,
            company_name='Test Corp',
            phone_number='0987654321',
            address='456 Business Ave'
        )
        self.assertEqual(profile.account_type, ClientProfile.AccountType.ENTERPRISE)
        self.assertEqual(profile.company_name, 'Test Corp')
        self.assertEqual(str(profile), "Test Corp (Enterprise)")

    def test_client_profile_user_relationship(self):
        """Test the one-to-one relationship between User and ClientProfile."""
        profile = ClientProfile.objects.create(
            user=self.user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number='1234567890',
            address='123 Main St'
        )
        self.assertEqual(self.user.client_profile, profile)