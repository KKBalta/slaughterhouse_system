
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import ClientProfile
from .services import (
    create_user_with_profile, update_user_profile, assign_role_to_user, 
    convert_walk_in_to_profile, deactivate_user, reactivate_user,
    change_user_password, admin_reset_user_password, archive_client_profile
)
from reception.models import SlaughterOrder
from core.models import ServicePackage
from datetime import date

User = get_user_model()

class UsersServiceTest(TestCase):

    def setUp(self):
        self.service_package = ServicePackage.objects.create(name='Test Package')
        self.user = User.objects.create_user(username='baseuser', password='password123', role=User.Role.CLIENT)
        self.profile = ClientProfile.objects.create(user=self.user, account_type='INDIVIDUAL', phone_number='123', address='abc')

    def test_create_user_with_profile_service(self):
        profile_data = {
            'account_type': ClientProfile.AccountType.ENTERPRISE,
            'company_name': 'Test Farm',
            'phone_number': '555-555-5555',
            'address': '123 Farm Rd'
        }
        user = create_user_with_profile(
            username='testfarm',
            password='password123',
            role=User.Role.CLIENT,
            **profile_data
        )

        self.assertIsInstance(user, User)
        self.assertEqual(User.objects.count(), 2) # Including setUp user
        self.assertEqual(ClientProfile.objects.count(), 2)
        self.assertTrue(hasattr(user, 'client_profile'))
        self.assertEqual(user.client_profile.company_name, 'Test Farm')

    def test_create_user_without_profile_service(self):
        user = create_user_with_profile(
            username='testoperator',
            password='password123',
            role=User.Role.OPERATOR
        )
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(ClientProfile.objects.count(), 1)
        self.assertFalse(hasattr(user, 'client_profile'))

    def test_update_user_profile_service(self):
        profile = update_user_profile(user=self.user, address='Updated Address', phone_number='222')

        self.assertEqual(profile.address, 'Updated Address')
        self.assertEqual(profile.phone_number, '222')
        self.assertEqual(profile.account_type, 'INDIVIDUAL')

    def test_assign_role_to_user_service(self):
        self.assertEqual(self.user.role, User.Role.CLIENT)
        updated_user = assign_role_to_user(user=self.user, new_role=User.Role.MANAGER)
        self.assertEqual(updated_user.role, User.Role.MANAGER)

    def test_convert_walk_in_to_profile_service(self):
        from django.utils import timezone
        walk_in_phone = '888-777-6666'
        SlaughterOrder.objects.create(
            client_name='Walk-in Joe', client_phone=walk_in_phone, 
            order_datetime=timezone.now(), service_package=self.service_package
        )
        user_data = {'username': 'walkinjoe', 'password': 'newpassword', 'role': User.Role.CLIENT}
        profile_data = {'account_type': 'INDIVIDUAL', 'phone_number': walk_in_phone, 'address': '123 Converted St'}

        new_profile = convert_walk_in_to_profile(
            phone_number=walk_in_phone, user_data=user_data, profile_data=profile_data
        )

        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(ClientProfile.objects.count(), 2)
        self.assertEqual(SlaughterOrder.objects.filter(client=new_profile).count(), 1)

    def test_deactivate_and_reactivate_user_service(self):
        self.assertTrue(self.user.is_active)
        deactivated_user = deactivate_user(user=self.user)
        self.assertFalse(deactivated_user.is_active)

        reactivated_user = reactivate_user(user=self.user)
        self.assertTrue(reactivated_user.is_active)

    def test_change_user_password_service(self):
        # Test successful password change
        success = change_user_password(user=self.user, old_password='password123', new_password='new_secure_password')
        self.assertTrue(success)
        # Verify the new password works
        self.assertTrue(self.user.check_password('new_secure_password'))

        # Test unsuccessful password change
        success = change_user_password(user=self.user, old_password='wrong_password', new_password='another_password')
        self.assertFalse(success)
        self.assertTrue(self.user.check_password('new_secure_password')) # Ensure password didn't change

    def test_admin_reset_user_password_service(self):
        admin_reset_user_password(user=self.user, new_password='admin_reset')
        self.assertTrue(self.user.check_password('admin_reset'))

    def test_archive_client_profile_service(self):
        self.assertTrue(self.profile.is_active)
        archived_profile = archive_client_profile(client_profile=self.profile)
        self.assertFalse(archived_profile.is_active)

    # --- Edge Case Tests ---

    def test_create_user_with_duplicate_username(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            create_user_with_profile(
                username='baseuser', # This username already exists from setUp
                password='password123',
                role=User.Role.CLIENT
            )

    def test_update_user_profile_creates_new_profile(self):
        # Create a user without a profile
        no_profile_user = User.objects.create_user(username='noprofile', password='password123')
        self.assertFalse(hasattr(no_profile_user, 'client_profile'))
        
        # Run the update service
        profile = update_user_profile(user=no_profile_user, address='A New Address')

        self.assertIsInstance(profile, ClientProfile)
        self.assertEqual(profile.address, 'A New Address')
        self.assertEqual(ClientProfile.objects.count(), 2) # Initial profile + this new one
        no_profile_user.refresh_from_db()
        self.assertTrue(hasattr(no_profile_user, 'client_profile'))

    def test_convert_walk_in_with_no_matching_orders(self):
        walk_in_phone = '111-222-3333'
        user_data = {'username': 'newuser', 'password': 'password', 'role': User.Role.CLIENT}
        profile_data = {'account_type': 'INDIVIDUAL', 'phone_number': walk_in_phone, 'address': '123 Empty St'}

        # Ensure no orders exist for this number
        self.assertEqual(SlaughterOrder.objects.filter(client_phone=walk_in_phone).count(), 0)

        new_profile = convert_walk_in_to_profile(
            phone_number=walk_in_phone, user_data=user_data, profile_data=profile_data
        )

        self.assertIsInstance(new_profile, ClientProfile)
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(ClientProfile.objects.count(), 2)
        # Check that no orders were associated
        self.assertEqual(SlaughterOrder.objects.filter(client=new_profile).count(), 0)

    def test_deactivate_already_inactive_user(self):
        # Deactivate once
        deactivated_user = deactivate_user(user=self.user)
        self.assertFalse(deactivated_user.is_active)
        
        # Deactivate again
        deactivated_user_again = deactivate_user(user=self.user)
        self.assertFalse(deactivated_user_again.is_active)

    def test_archive_already_archived_profile(self):
        # Archive once
        archived_profile = archive_client_profile(client_profile=self.profile)
        self.assertFalse(archived_profile.is_active)

        # Archive again
        archived_profile_again = archive_client_profile(client_profile=self.profile)
        self.assertFalse(archived_profile_again.is_active)
