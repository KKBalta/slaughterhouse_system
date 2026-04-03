import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError

from .models import ClientProfile
from .policies import can_create_role, can_edit_user, creatable_roles_for

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_create_user_requires_explicit_role():
    with pytest.raises(ValueError, match="explicit role"):
        User.objects.create_user(username="testuser", password="password123")


def test_create_user_with_specific_role():
    user = User.objects.create_user(username="clientuser", password="password123", role=User.Role.CLIENT)
    assert user.role == User.Role.CLIENT


def test_create_individual_client_profile():
    user = User.objects.create_user(username="individual_client", password="password123", role=User.Role.CLIENT)
    profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="111-222-3333",
        address="1 Individual Lane",
    )
    assert profile.user == user
    assert user.client_profile == profile
    assert profile.account_type == "INDIVIDUAL"
    assert str(profile) == f"{user.get_full_name()} (Individual)"


def test_create_enterprise_client_profile():
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
    assert profile.company_name == "Big Farm Inc."
    assert profile.tax_id == "ENT-12345"
    assert str(profile) == "Big Farm Inc. (Enterprise)"


def test_user_deletion_cascades_to_client_profile():
    user = User.objects.create_user(username="todelete", password="password123", role=User.Role.CLIENT)
    ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        phone_number="999-999-9999",
        address="Delete Street",
    )
    assert ClientProfile.objects.count() == 1
    user.delete()
    assert ClientProfile.objects.count() == 0


def test_username_uniqueness():
    User.objects.create_user(username="unique_user", password="password123", role=User.Role.CLIENT)
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="unique_user", password="password456", role=User.Role.CLIENT)


def test_owner_cannot_create_admin_role():
    owner = User.objects.create_user(username="owner-user", password="password123", role=User.Role.OWNER)

    assert can_create_role(owner, User.Role.ADMIN) is False
    assert creatable_roles_for(owner) == (
        User.Role.MANAGER,
        User.Role.OPERATOR,
        User.Role.CLIENT,
    )


def test_admin_can_edit_all_roles():
    admin = User.objects.create_user(username="admin-actor", password="password123", role=User.Role.ADMIN)
    owner = User.objects.create_user(username="owner-target", password="password123", role=User.Role.OWNER)
    admin_target = User.objects.create_user(username="admin-target", password="password123", role=User.Role.ADMIN)
    manager = User.objects.create_user(username="manager-target", password="password123", role=User.Role.MANAGER)

    assert can_edit_user(admin, owner) is True
    assert can_edit_user(admin, admin_target) is True
    assert can_edit_user(admin, manager) is True
    assert can_create_role(admin, User.Role.OWNER) is True
    assert can_create_role(admin, User.Role.ADMIN) is True
    assert creatable_roles_for(admin) == (
        User.Role.OWNER,
        User.Role.ADMIN,
        User.Role.MANAGER,
        User.Role.OPERATOR,
        User.Role.CLIENT,
    )


def test_owner_cannot_edit_admin_user():
    owner = User.objects.create_user(username="owner-user", password="password123", role=User.Role.OWNER)
    admin = User.objects.create_user(username="admin-user", password="password123", role=User.Role.ADMIN)

    assert can_edit_user(owner, admin) is False
