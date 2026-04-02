from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.crypto import get_random_string

from reception.models import SlaughterOrder

from .models import ClientProfile

User = get_user_model()

# Staff-created accounts: long enough for Django validators; cryptographically random.
_RANDOM_PASSWORD_LENGTH = 20


def generate_random_password(length: int = _RANDOM_PASSWORD_LENGTH) -> str:
    """Return a one-time password suitable for create_user() when staff skip the password fields."""
    return get_random_string(length)


@transaction.atomic
def create_user_with_profile(
    username,
    password,
    role,
    email="",
    phone_number="",
    profile_phone_number=None,
    **profile_data,
) -> User:
    """
    Creates a new User and their associated ClientProfile in a single transaction.
    """
    # The create_user method handles password hashing.
    user = User.objects.create_user(
        username=username, password=password, role=role, email=email, phone_number=phone_number
    )

    if profile_phone_number is not None:
        profile_data["phone_number"] = profile_phone_number

    if profile_data:
        ClientProfile.objects.create(user=user, **profile_data)

    return user


@transaction.atomic
def update_user_credentials(
    user: User,
    *,
    username: str,
    email: str = "",
    phone_number: str = "",
    password: str = "",
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    user.username = username
    user.email = email or ""
    user.phone_number = phone_number or ""
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password:
        user.set_password(password)
        user.save()
        return user

    update_fields = ["username", "email", "phone_number"]
    if role is not None:
        update_fields.append("role")
    if is_active is not None:
        update_fields.append("is_active")
    user.save(update_fields=update_fields)
    return user


@transaction.atomic
def sync_client_contact_channels(
    *,
    user: User | None,
    profile: ClientProfile,
    email: str = "",
    phone_number: str = "",
) -> ClientProfile:
    profile.phone_number = phone_number or ""
    profile.save(update_fields=["phone_number", "updated_at"])
    if user is not None:
        user.email = email or ""
        user.phone_number = phone_number or ""
        user.save(update_fields=["email", "phone_number"])
    return profile


@transaction.atomic
def update_self_service_contact_channels(
    user: User,
    *,
    email: str = "",
    phone_number: str = "",
) -> User:
    user.email = email or ""
    user.phone_number = phone_number or ""
    user.save(update_fields=["email", "phone_number"])

    if getattr(user, "role", "") == User.Role.CLIENT:
        try:
            profile = user.client_profile
        except ClientProfile.DoesNotExist:
            profile = None
        if profile is not None:
            profile.phone_number = user.phone_number or ""
            profile.save(update_fields=["phone_number", "updated_at"])
    return user


@transaction.atomic
def update_user_profile(user: User, **profile_data) -> ClientProfile:
    """
    Updates the ClientProfile for a given user.
    """
    # Using update_or_create is robust, handling cases where a profile might not exist yet.
    profile, created = ClientProfile.objects.update_or_create(user=user, defaults=profile_data)
    return profile


@transaction.atomic
def assign_role_to_user(user: User, new_role: str) -> User:
    """
    Assigns a new role to a user.
    """
    # In the future, add permission checks here to see if the requesting user
    # is allowed to perform this action.
    user.role = new_role
    user.save(update_fields=["role"])
    return user


@transaction.atomic
def convert_walk_in_to_profile(phone_number: str, user_data: dict, profile_data: dict) -> ClientProfile:
    """
    Converts a walk-in customer into a registered client with a profile.
    - Creates a new User and ClientProfile.
    - Finds past orders matching the phone number and associates them with the new profile.
    """
    user = User.objects.create_user(**user_data)
    profile_data["user"] = user
    profile = ClientProfile.objects.create(**profile_data)

    orders_to_update = SlaughterOrder.objects.filter(client__isnull=True, client_phone=phone_number)

    # Perform a bulk update for efficiency.
    orders_to_update.update(client=profile, client_name="", client_phone="")

    return profile


# --- Lifecycle & Security Services ---


def deactivate_user(user: User) -> User:
    """Safely deactivates a user's account."""
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


def reactivate_user(user: User) -> User:
    """Reactivates a user's account."""
    user.is_active = True
    user.save(update_fields=["is_active"])
    return user


def change_user_password(user: User, old_password: str, new_password: str) -> bool:
    """Allows a user to change their own password."""
    if user.check_password(old_password):
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return True
    return False


def admin_reset_user_password(user: User, new_password: str) -> User:
    """Allows an admin to reset a user's password."""
    user.set_password(new_password)
    user.save(update_fields=["password"])
    return user


def archive_client_profile(client_profile: ClientProfile) -> ClientProfile:
    """Archives a client's profile by using the soft-delete method."""
    client_profile.soft_delete()  # This uses the method from BaseModel
    return client_profile


@transaction.atomic
def activate_client_profile(client_profile: ClientProfile) -> ClientProfile:
    """Restores an archived profile and re-enables login for the linked user, if any."""
    client_profile.restore()
    u = client_profile.user
    if u is not None:
        reactivate_user(u)
    return client_profile
