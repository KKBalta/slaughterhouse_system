import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from core.models import ServicePackage
from reception.models import SlaughterOrder

from .models import ClientProfile
from .services import (
    activate_client_profile,
    admin_reset_user_password,
    archive_client_profile,
    assign_role_to_user,
    change_user_password,
    convert_walk_in_to_profile,
    create_user_with_profile,
    deactivate_user,
    reactivate_user,
    update_user_profile,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def users_service_state():
    service_package = ServicePackage.objects.create(name="Test Package")
    user = User.objects.create_user(username="baseuser", password="password123", role=User.Role.CLIENT)
    profile = ClientProfile.objects.create(user=user, account_type="INDIVIDUAL", phone_number="123", address="abc")
    return {
        "service_package": service_package,
        "user": user,
        "profile": profile,
    }


def test_create_user_with_profile_service():
    profile_data = {
        "account_type": ClientProfile.AccountType.ENTERPRISE,
        "company_name": "Test Farm",
        "address": "123 Farm Rd",
    }
    user = create_user_with_profile(
        username="testfarm",
        password="password123",
        role=User.Role.CLIENT,
        email="farm@example.com",
        phone_number="+15555555555",
        profile_phone_number="555-555-5555",
        **profile_data,
    )

    assert isinstance(user, User)
    assert User.objects.count() == 1
    assert ClientProfile.objects.count() == 1
    assert hasattr(user, "client_profile")
    assert user.email == "farm@example.com"
    assert user.phone_number == "+15555555555"
    assert user.client_profile.company_name == "Test Farm"


def test_create_user_without_profile_service(users_service_state):
    user = create_user_with_profile(username="testoperator", password="password123", role=User.Role.OPERATOR)
    assert User.objects.count() == 2
    assert ClientProfile.objects.count() == 1
    assert not hasattr(user, "client_profile")


def test_update_user_profile_service(users_service_state):
    profile = update_user_profile(user=users_service_state["user"], address="Updated Address", phone_number="222")

    assert profile.address == "Updated Address"
    assert profile.phone_number == "222"
    assert profile.account_type == "INDIVIDUAL"


def test_assign_role_to_user_service(users_service_state):
    assert users_service_state["user"].role == User.Role.CLIENT
    updated_user = assign_role_to_user(user=users_service_state["user"], new_role=User.Role.MANAGER)
    assert updated_user.role == User.Role.MANAGER


def test_convert_walk_in_to_profile_service(users_service_state):
    walk_in_phone = "888-777-6666"
    SlaughterOrder.objects.create(
        client_name="Walk-in Joe",
        client_phone=walk_in_phone,
        order_datetime=timezone.now(),
        service_package=users_service_state["service_package"],
    )
    user_data = {"username": "walkinjoe", "password": "newpassword", "role": User.Role.CLIENT}
    profile_data = {"account_type": "INDIVIDUAL", "phone_number": walk_in_phone, "address": "123 Converted St"}

    new_profile = convert_walk_in_to_profile(phone_number=walk_in_phone, user_data=user_data, profile_data=profile_data)

    assert User.objects.count() == 2
    assert ClientProfile.objects.count() == 2
    assert SlaughterOrder.objects.filter(client=new_profile).count() == 1


def test_deactivate_and_reactivate_user_service(users_service_state):
    assert users_service_state["user"].is_active
    deactivated_user = deactivate_user(user=users_service_state["user"])
    assert not deactivated_user.is_active

    reactivated_user = reactivate_user(user=users_service_state["user"])
    assert reactivated_user.is_active


def test_change_user_password_service(users_service_state):
    success = change_user_password(
        user=users_service_state["user"], old_password="password123", new_password="new_secure_password"
    )
    assert success
    assert users_service_state["user"].check_password("new_secure_password")

    success = change_user_password(
        user=users_service_state["user"], old_password="wrong_password", new_password="another_password"
    )
    assert not success
    assert users_service_state["user"].check_password("new_secure_password")


def test_admin_reset_user_password_service(users_service_state):
    admin_reset_user_password(user=users_service_state["user"], new_password="admin_reset")
    assert users_service_state["user"].check_password("admin_reset")


def test_archive_client_profile_service(users_service_state):
    assert users_service_state["profile"].is_active
    archived_profile = archive_client_profile(client_profile=users_service_state["profile"])
    assert not archived_profile.is_active


def test_activate_client_profile_service(users_service_state):
    archive_client_profile(client_profile=users_service_state["profile"])
    deactivate_user(users_service_state["user"])
    users_service_state["profile"].refresh_from_db()
    users_service_state["user"].refresh_from_db()
    assert not users_service_state["profile"].is_active
    assert not users_service_state["user"].is_active

    activate_client_profile(users_service_state["profile"])
    users_service_state["profile"].refresh_from_db()
    users_service_state["user"].refresh_from_db()
    assert users_service_state["profile"].is_active
    assert users_service_state["user"].is_active


def test_create_user_with_duplicate_username(users_service_state):
    with pytest.raises(IntegrityError):
        create_user_with_profile(
            username="baseuser",
            password="password123",
            role=User.Role.CLIENT,
        )


def test_update_user_profile_creates_new_profile(users_service_state):
    no_profile_user = User.objects.create_user(username="noprofile", password="password123")
    assert not hasattr(no_profile_user, "client_profile")

    profile = update_user_profile(user=no_profile_user, address="A New Address")

    assert isinstance(profile, ClientProfile)
    assert profile.address == "A New Address"
    assert ClientProfile.objects.count() == 2
    no_profile_user.refresh_from_db()
    assert hasattr(no_profile_user, "client_profile")


def test_convert_walk_in_with_no_matching_orders(users_service_state):
    walk_in_phone = "111-222-3333"
    user_data = {"username": "newuser", "password": "password", "role": User.Role.CLIENT}
    profile_data = {"account_type": "INDIVIDUAL", "phone_number": walk_in_phone, "address": "123 Empty St"}

    assert SlaughterOrder.objects.filter(client_phone=walk_in_phone).count() == 0

    new_profile = convert_walk_in_to_profile(phone_number=walk_in_phone, user_data=user_data, profile_data=profile_data)

    assert isinstance(new_profile, ClientProfile)
    assert User.objects.count() == 2
    assert ClientProfile.objects.count() == 2
    assert SlaughterOrder.objects.filter(client=new_profile).count() == 0


def test_deactivate_already_inactive_user(users_service_state):
    deactivated_user = deactivate_user(user=users_service_state["user"])
    assert not deactivated_user.is_active

    deactivated_user_again = deactivate_user(user=users_service_state["user"])
    assert not deactivated_user_again.is_active


def test_archive_already_archived_profile(users_service_state):
    archived_profile = archive_client_profile(client_profile=users_service_state["profile"])
    assert not archived_profile.is_active

    archived_profile_again = archive_client_profile(client_profile=users_service_state["profile"])
    assert not archived_profile_again.is_active
