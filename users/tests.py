from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase

from .models import ClientProfile

User = get_user_model()


class UsersModelTest(TestCase):
    def test_create_user_with_default_role(self):
        user = User.objects.create_user(username="testuser", password="password123")
        self.assertEqual(user.role, User.Role.ADMIN)

    def test_create_user_with_specific_role(self):
        user = User.objects.create_user(username="clientuser", password="password123", role=User.Role.CLIENT)
        self.assertEqual(user.role, User.Role.CLIENT)

    def test_create_individual_client_profile(self):
        user = User.objects.create_user(username="individual_client", password="password123", role=User.Role.CLIENT)
        profile = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="111-222-3333",
            address="1 Individual Lane",
        )
        self.assertEqual(profile.user, user)
        self.assertEqual(user.client_profile, profile)
        self.assertEqual(profile.account_type, "INDIVIDUAL")
        self.assertEqual(str(profile), f"{user.get_full_name()} (Individual)")

    def test_create_enterprise_client_profile(self):
        user = User.objects.create_user(username="enterprise_client", password="password123", role=User.Role.CLIENT)
        profile = ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.ENTERPRISE,
            company_name="Big Farm Inc.",
            contact_person="John Farmer",
            phone_number="444-555-6666",
            address="2 Enterprise Drive",
            tax_id="ENT-12345",
        )
        self.assertEqual(profile.company_name, "Big Farm Inc.")
        self.assertEqual(profile.tax_id, "ENT-12345")
        self.assertEqual(str(profile), "Big Farm Inc. (Enterprise)")

    def test_user_deletion_cascades_to_client_profile(self):
        user = User.objects.create_user(username="todelete", password="password123", role=User.Role.CLIENT)
        ClientProfile.objects.create(
            user=user,
            account_type=ClientProfile.AccountType.INDIVIDUAL,
            phone_number="999-999-9999",
            address="Delete Street",
        )
        self.assertEqual(ClientProfile.objects.count(), 1)
        user.delete()
        self.assertEqual(ClientProfile.objects.count(), 0)

    def test_username_uniqueness(self):
        User.objects.create_user(username="unique_user", password="password123")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(username="unique_user", password="password456")
