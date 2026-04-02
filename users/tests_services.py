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
    generate_random_password,
    reactivate_user,
    update_self_service_contact_channels,
    update_user_profile,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_generate_random_password_length_and_uniqueness():
    a = generate_random_password()
    b = generate_random_password()
    assert len(a) == 20
    assert len(b) == 20
    assert a != b


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


def test_update_self_service_contact_channels_syncs_client_profile(users_service_state):
    updated_user = update_self_service_contact_channels(
        users_service_state["user"],
        email="updated@example.com",
        phone_number="+905551112233",
    )

    users_service_state["profile"].refresh_from_db()
    assert updated_user.email == "updated@example.com"
    assert updated_user.phone_number == "+905551112233"
    assert users_service_state["profile"].phone_number == "+905551112233"


def test_update_self_service_contact_channels_only_updates_staff_user():
    user = User.objects.create_user(
        username="staff-user",
        password="password123",
        email="staff@example.com",
        role=User.Role.MANAGER,
    )

    updated_user = update_self_service_contact_channels(
        user,
        email="staff-updated@example.com",
        phone_number="+15556667777",
    )

    assert updated_user.email == "staff-updated@example.com"
    assert updated_user.phone_number == "+15556667777"


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
    no_profile_user = User.objects.create_user(username="noprofile", password="password123", role=User.Role.CLIENT)
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


# ---------------------------------------------------------------------------
# Phone number DB-level uniqueness constraint
# ---------------------------------------------------------------------------

def test_duplicate_phone_number_raises_integrity_error():
    """DB constraint rejects two users with the same non-empty phone number."""
    User.objects.create_user(username="phone-a", password="pass", role=User.Role.CLIENT, phone_number="+905550001111")
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="phone-b", password="pass", role=User.Role.CLIENT, phone_number="+905550001111")


def test_multiple_users_without_phone_allowed():
    """Empty phone strings are exempt from the uniqueness constraint."""
    User.objects.create_user(username="no-phone-a", password="pass", role=User.Role.CLIENT, phone_number="")
    User.objects.create_user(username="no-phone-b", password="pass", role=User.Role.OPERATOR, phone_number="")
    User.objects.create_user(username="no-phone-c", password="pass", role=User.Role.MANAGER, phone_number="")
    assert User.objects.filter(phone_number="").count() == 3


def test_phone_uniqueness_enforced_across_roles():
    """The constraint applies regardless of role — OPERATOR cannot take CLIENT's phone."""
    User.objects.create_user(username="client-a", password="pass", role=User.Role.CLIENT, phone_number="+15550001111")
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="operator-b", password="pass", role=User.Role.OPERATOR, phone_number="+15550001111")


def test_update_user_credentials_raises_on_duplicate_phone():
    """update_user_credentials raises IntegrityError when phone is already taken."""
    User.objects.create_user(username="owner-phone", password="pass", role=User.Role.CLIENT, phone_number="+905559998888")
    other = User.objects.create_user(username="other-user", password="pass", role=User.Role.CLIENT, phone_number="")

    from .services import update_user_credentials

    with pytest.raises(IntegrityError):
        update_user_credentials(other, username="other-user", phone_number="+905559998888")


def test_user_can_keep_own_phone_on_update():
    """A user updating their own credentials with the same phone number should not raise."""
    user = User.objects.create_user(username="self-update", password="pass", role=User.Role.CLIENT, phone_number="+905551234567")

    from .services import update_user_credentials

    updated = update_user_credentials(user, username="self-update", phone_number="+905551234567")
    assert updated.phone_number == "+905551234567"
