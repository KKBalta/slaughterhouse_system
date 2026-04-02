import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError

from .models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


def test_create_user_with_default_role():
    user = User.objects.create_user(username="testuser", password="password123")
    assert user.role == User.Role.ADMIN


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
    User.objects.create_user(username="unique_user", password="password123")
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="unique_user", password="password456")
