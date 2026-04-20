from __future__ import annotations

import pytest

from users.forms import (
    ClientProfileRegisterForm,
    ClientUserCredentialsForm,
    SelfServiceContactForm,
    SelfServicePasswordForm,
    UserRegistrationForm,
)
from users.models import ClientProfile, User

pytestmark = pytest.mark.django_db


def test_client_user_credentials_form_require_password_updates_fields():
    form = ClientUserCredentialsForm(require_password=True)

    assert form.fields["new_password1"].required is False
    assert form.fields["new_password2"].required is False
    assert "random" in str(form.fields["new_password1"].help_text).lower()
    assert form.fields["new_password1"].widget.attrs["autocomplete"] == "new-password"


def test_client_user_credentials_form_require_password_allows_empty_when_creating():
    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "",
            "phone_number": "+15550001111",
            "new_password1": "",
            "new_password2": "",
        },
        require_password=True,
        user_instance=None,
    )
    assert form.is_valid(), form.errors


def test_client_user_credentials_form_rejects_duplicate_username():
    User.objects.create_user(username="taken", password="password123", role=User.Role.CLIENT)

    form = ClientUserCredentialsForm(
        data={
            "username": " taken ",
            "email": "",
            "phone_number": "+15550001111",
            "new_password1": "",
            "new_password2": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["username"] == ["A user with that username already exists."]


def test_client_user_credentials_form_allows_current_user_username():
    user = User.objects.create_user(username="current", password="password123", role=User.Role.CLIENT)

    form = ClientUserCredentialsForm(
        data={
            "username": " current ",
            "email": "",
            "phone_number": "+15550001111",
            "new_password1": "",
            "new_password2": "",
        },
        user_instance=user,
    )

    assert form.is_valid()
    assert form.cleaned_data["username"] == "current"


@pytest.mark.parametrize(
    ("require_password", "password1", "password2", "expected_field", "expected_message"),
    [
        (True, "abcdefgh", "abcdwxyz", "new_password2", "The two password fields don't match."),
        (True, "short", "short", "new_password1", "Password must be at least 8 characters."),
        (False, "abcdefgh", "abcdwxyz", "new_password2", "The two password fields don't match."),
        (False, "short", "short", "new_password1", "Password must be at least 8 characters."),
    ],
)
def test_client_user_credentials_form_password_validation(
    require_password, password1, password2, expected_field, expected_message
):
    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "",
            "phone_number": "+15550001111",
            "new_password1": password1,
            "new_password2": password2,
        },
        require_password=require_password,
    )

    assert not form.is_valid()
    assert form.errors[expected_field] == [expected_message]


def test_client_user_credentials_form_allows_optional_blank_password():
    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "",
            "phone_number": "+15550001111",
            "new_password1": "",
            "new_password2": "",
        }
    )

    assert form.is_valid()


def test_client_user_credentials_form_requires_email_or_phone():
    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "",
            "phone_number": "",
            "new_password1": "",
            "new_password2": "",
        }
    )

    assert not form.is_valid()
    assert form.non_field_errors() == ["At least one of email or phone number is required."]


def test_client_user_credentials_form_initializes_email_and_phone_from_user_instance():
    user = User.objects.create_user(
        username="contact-user",
        password="password123",
        email="contact@example.com",
        phone_number="+15551234567",
        role=User.Role.CLIENT,
    )

    form = ClientUserCredentialsForm(user_instance=user)

    assert form.fields["username"].initial == "contact-user"
    assert form.fields["email"].initial == "contact@example.com"
    assert form.fields["phone_area_code"].initial == "+1"
    assert form.fields["phone_number"].initial == "5551234567"


def test_client_user_credentials_form_rejects_duplicate_email():
    User.objects.create_user(
        username="existing-email",
        password="password123",
        email="taken@example.com",
        role=User.Role.CLIENT,
    )

    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "TAKEN@example.com",
            "phone_number": "",
            "new_password1": "",
            "new_password2": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["email"] == ["A user with that email already exists in this tenant."]


def test_client_user_credentials_form_rejects_duplicate_phone_number():
    User.objects.create_user(
        username="existing-phone",
        password="password123",
        phone_number="+15550001111",
        role=User.Role.CLIENT,
    )

    form = ClientUserCredentialsForm(
        data={
            "username": "fresh-user",
            "email": "",
            "phone_area_code": "+1",
            "phone_number": "5550001111",
            "new_password1": "",
            "new_password2": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["phone_number"] == ["A user with that phone number already exists in this tenant."]


def test_self_service_contact_form_initializes_from_user():
    user = User.objects.create_user(
        username="self-service-user",
        password="password123",
        email="self@example.com",
        phone_number="+15551234567",
        role=User.Role.CLIENT,
    )

    form = SelfServiceContactForm(user_instance=user)

    assert form.fields["email"].initial == "self@example.com"
    assert form.fields["phone_area_code"].initial == "+1"
    assert form.fields["phone_number"].initial == "5551234567"


def test_self_service_contact_form_requires_email_or_phone():
    form = SelfServiceContactForm(
        data={
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "",
        }
    )

    assert not form.is_valid()
    assert form.non_field_errors() == ["At least one of email or phone number is required."]


def test_self_service_password_form_validates_current_password_and_new_password():
    user = User.objects.create_user(username="password-user", password="StrongPass123!", role=User.Role.CLIENT)
    form = SelfServicePasswordForm(
        data={
            "current_password": "StrongPass123!",
            "new_password1": "NewStrongPass456!",
            "new_password2": "NewStrongPass456!",
        },
        user_instance=user,
    )

    assert form.is_valid(), form.errors


def test_self_service_password_form_rejects_wrong_current_password():
    user = User.objects.create_user(username="wrong-password-user", password="StrongPass123!", role=User.Role.CLIENT)
    form = SelfServicePasswordForm(
        data={
            "current_password": "wrong",
            "new_password1": "NewStrongPass456!",
            "new_password2": "NewStrongPass456!",
        },
        user_instance=user,
    )

    assert not form.is_valid()
    assert form.errors["current_password"] == ["Your current password was entered incorrectly."]


def test_user_registration_form_role_choices_for_privileged_user():
    acting_user = User.objects.create_user(username="admin", password="password123", role=User.Role.ADMIN)

    form = UserRegistrationForm(user=acting_user)

    assert form.fields["role"].choices == list(User.Role.choices)


def test_user_registration_form_role_choices_for_non_privileged_user():
    acting_user = User.objects.create_user(username="client", password="password123", role=User.Role.CLIENT)

    form = UserRegistrationForm(user=acting_user)

    assert form.fields["role"].choices == [
        (User.Role.CLIENT, "Client"),
        (User.Role.OPERATOR, "Operator"),
    ]


def test_user_registration_form_requires_email_or_phone():
    form = UserRegistrationForm(
        data={
            "username": "new-user",
            "email": "",
            "phone_number": "",
            "role": User.Role.CLIENT,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
    )

    assert not form.is_valid()
    assert form.non_field_errors() == ["At least one of email or phone number is required."]


def test_user_registration_form_normalizes_phone_number():
    form = UserRegistrationForm(
        data={
            "username": "new-user",
            "email": "",
            "phone_number": "+1 (202) 555-1234",
            "role": User.Role.CLIENT,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone_number"] == "+12025551234"


def test_user_registration_form_rejects_phone_without_supported_country():
    form = UserRegistrationForm(
        data={
            "username": "new-user",
            "email": "",
            "phone_number": "(555) 123-4567",
            "role": User.Role.CLIENT,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
    )

    assert not form.is_valid()
    assert "phone_number" in form.errors


def test_user_registration_form_rejects_short_us_phone():
    form = UserRegistrationForm(
        data={
            "username": "new-user",
            "email": "",
            "phone_number": "+12025551",
            "role": User.Role.CLIENT,
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }
    )

    assert not form.is_valid()
    assert "phone_number" in form.errors


@pytest.mark.parametrize(
    ("phone_number", "expected_area", "expected_local"),
    [
        ("+905551112233", "+90", "5551112233"),
        ("+15551234567", "+1", "5551234567"),
        ("5551234", "+90", "5551234"),
    ],
)
def test_client_profile_register_form_initializes_phone_fields(phone_number, expected_area, expected_local):
    user = User.objects.create_user(username=f"user-{expected_local}", password="password123", role=User.Role.CLIENT)
    profile = ClientProfile.objects.create(
        user=user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        contact_person="Alice",
        phone_number=phone_number,
        address="Addr",
    )

    form = ClientProfileRegisterForm(instance=profile)

    assert form.fields["phone_area_code"].initial == expected_area
    assert form.fields["phone_number"].initial == expected_local


def test_client_profile_register_form_combines_area_code_and_strips_fields():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": " Alice ",
            "email": " alice@example.com ",
            "phone_area_code": "+1",
            "phone_number": " 2025551234 ",
            "address": "123 Test St",
            "default_destination": " Main Delivery Hub ",
            "company_name": " ",
            "tax_id": " ",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["contact_person"] == "Alice"
    assert form.cleaned_data["phone_number"] == "+12025551234"
    assert form.cleaned_data["default_destination"] == "Main Delivery Hub"
    assert form.cleaned_data["company_name"] is None
    assert form.cleaned_data["tax_id"] is None


def test_client_profile_register_form_preserves_prefixed_phone_number():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "+12025551234",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["phone_number"] == "+12025551234"


def test_client_profile_register_form_allows_email_only_registration():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "alice@example.com",
            "phone_area_code": "+90",
            "phone_number": "",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert form.is_valid()
    assert form.cleaned_data["email"] == "alice@example.com"
    assert form.cleaned_data["phone_number"] == ""


def test_client_profile_register_form_requires_email_or_phone():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.non_field_errors() == ["At least one of email or phone number is required."]


def test_client_profile_register_form_rejects_duplicate_email():
    User.objects.create_user(
        username="existing",
        password="password123",
        email="alice@example.com",
        role=User.Role.CLIENT,
    )

    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "Alice@example.com",
            "phone_area_code": "+90",
            "phone_number": "",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["email"] == ["A user with that email already exists in this tenant."]


def test_client_profile_register_form_rejects_duplicate_phone_number():
    existing_user = User.objects.create_user(
        username="existing-phone-client",
        password="password123",
        phone_number="+905551112233",
        role=User.Role.CLIENT,
    )
    ClientProfile.objects.create(
        user=existing_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        contact_person="Existing",
        phone_number="+905551112233",
        address="123 Existing St",
    )

    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551112233",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["phone_number"] == ["A user with that phone number already exists in this tenant."]


def test_client_profile_register_form_allows_registered_phone_when_configured():
    existing_user = User.objects.create_user(
        username="existing-registered-phone",
        password="password123",
        phone_number="+905551112244",
        role=User.Role.CLIENT,
    )

    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551112244",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        },
        allow_existing_phone_user=True,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone_number"] == "+905551112244"
    assert form.registered_phone_user == existing_user


def test_client_profile_register_form_rejects_short_turkish_phone():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551234",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert "phone_number" in form.errors


def test_client_profile_register_form_rejects_duplicate_profile_phone_without_user():
    ClientProfile.objects.create(
        user=None,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        contact_person="Existing Walk-in",
        phone_number="+905551112255",
        address="123 Existing St",
    )

    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": "Alice",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551112255",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["phone_number"] == ["A client profile with that phone number already exists."]


def test_client_profile_register_form_requires_enterprise_fields():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.ENTERPRISE,
            "contact_person": " ",
            "email": "enterprise@example.com",
            "phone_area_code": "+90",
            "phone_number": "5551112233",
            "address": "123 Test St",
            "company_name": " ",
            "tax_id": " ",
        }
    )

    assert not form.is_valid()
    assert form.errors["company_name"] == ["Company name is required for enterprise accounts."]
    assert form.errors["tax_id"] == ["Tax ID is required for enterprise accounts."]
    assert form.errors["contact_person"] == ["Contact person is required for enterprise accounts."]


def test_client_profile_register_form_requires_contact_person_for_individual():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.INDIVIDUAL,
            "contact_person": " ",
            "email": "individual@example.com",
            "phone_area_code": "+90",
            "phone_number": "5551112233",
            "address": "123 Test St",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["contact_person"] == ["Contact person is required for individual accounts."]


def test_client_profile_register_form_allows_unclassified_without_address():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.UNCLASSIFIED,
            "contact_person": "Walk-in Prospect",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551234567",
            "address": " ",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["address"] == ""


def test_client_profile_register_form_requires_name_for_unclassified():
    form = ClientProfileRegisterForm(
        data={
            "account_type": ClientProfile.AccountType.UNCLASSIFIED,
            "contact_person": " ",
            "email": "",
            "phone_area_code": "+90",
            "phone_number": "5551234567",
            "address": "",
            "company_name": "",
            "tax_id": "",
        }
    )

    assert not form.is_valid()
    assert form.errors["contact_person"] == ["Name is required for walk-in accounts."]
