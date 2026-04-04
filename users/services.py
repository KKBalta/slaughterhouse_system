from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.crypto import get_random_string

from reception.models import SlaughterOrder
from tenants.email_index import normalize_phone

from .models import CLIENT_MANAGEMENT_ROLES, ClientProfile

User = get_user_model()

# Staff-created accounts: long enough for Django validators; cryptographically random.
_RANDOM_PASSWORD_LENGTH = 20


def _client_management_role_for(user: User | None) -> bool:
    return bool(user is not None and getattr(user, "role", "") in CLIENT_MANAGEMENT_ROLES)


def phone_lookup_candidates(phone_number: str | None) -> tuple[str, ...]:
    """Return exact-match candidates for legacy/raw and normalized phone storage."""
    raw = (phone_number or "").strip()
    if not raw:
        return ()

    candidates: list[str] = []

    def _add(value: str | None) -> None:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    _add(raw)

    normalized = normalize_phone(raw)
    _add(normalized)
    _add(normalized.lstrip("+"))

    if normalized.startswith("+90"):
        _add(normalized[3:])
    elif normalized.startswith("+1"):
        _add(normalized[2:])

    digits = "".join(char for char in raw if char.isdigit())
    _add(digits)

    return tuple(candidates)


def generate_random_password(length: int = _RANDOM_PASSWORD_LENGTH) -> str:
    """Return a one-time password suitable for create_user() when staff skip the password fields."""
    return get_random_string(length)


def generate_walk_in_username(phone_number: str | None = None) -> str:
    normalized_phone = normalize_phone(phone_number)
    digits = normalized_phone.lstrip("+")
    base = f"walkin-{digits}" if digits else f"walkin-{get_random_string(8).lower()}"
    username = base[:150]
    suffix = 2
    while User.objects.filter(username__iexact=username).exists():
        candidate = f"{base}-{suffix}"
        username = candidate[:150]
        suffix += 1
    return username


@transaction.atomic
def backfill_legacy_walk_in_profiles_from_orders() -> dict[str, int]:
    """
    Backfill WALKIN users / profiles for legacy walk-in orders.

    Legacy orders may contain only `client_name` + `client_phone` with no linked
    `client` profile because they were created before walk-in prospects were
    auto-created. This routine creates or reuses one manageable profile per
    normalized phone number, then links all matching historical orders.
    """
    unlinked_orders = SlaughterOrder.objects.filter(client__isnull=True)
    ordered_unlinked_orders = list(unlinked_orders.order_by("-order_datetime", "-created_at", "-pk"))

    stats = {
        "unlinked_orders": unlinked_orders.count(),
        "eligible_orders": 0,
        "skipped_missing_name_or_phone": 0,
        "processed_phone_groups": 0,
        "skipped_invalid_phone_groups": 0,
        "skipped_unmanageable_phone_groups": 0,
        "created_users": 0,
        "created_profiles": 0,
        "reused_profiles": 0,
        "linked_orders": 0,
    }

    representative_orders: dict[str, SlaughterOrder] = {}
    grouped_order_ids: dict[str, set[str]] = {}
    for order in ordered_unlinked_orders:
        normalized_phone = normalize_phone(order.client_phone)
        if normalized_phone:
            grouped_order_ids.setdefault(normalized_phone, set()).add(str(order.pk))

        if not (order.client_name or "").strip() or not (order.client_phone or "").strip():
            stats["skipped_missing_name_or_phone"] += 1
            continue

        stats["eligible_orders"] += 1
        if not normalized_phone:
            stats["skipped_invalid_phone_groups"] += 1
            continue
        representative_orders.setdefault(normalized_phone, order)

    stats["processed_phone_groups"] = len(representative_orders)

    for normalized_phone, order in representative_orders.items():
        existing_profile = find_manageable_client_profile_by_phone(normalized_phone)
        existing_user = User.objects.filter(phone_number=normalized_phone).first()

        profile = get_or_create_walk_in_profile(
            contact_name=(order.client_name or "").strip(),
            phone_number=normalized_phone,
            destination=order.destination,
        )
        if profile is None:
            stats["skipped_unmanageable_phone_groups"] += 1
            continue

        if existing_profile is None:
            stats["created_profiles"] += 1
        else:
            stats["reused_profiles"] += 1

        if existing_user is None and profile.user_id:
            stats["created_users"] += 1

        stats["linked_orders"] += SlaughterOrder.objects.filter(
            client__isnull=True,
            pk__in=grouped_order_ids.get(normalized_phone, set()),
        ).update(
            client=profile,
        )

    return stats


def _apply_walk_in_profile_defaults(
    profile: ClientProfile,
    *,
    contact_name: str,
    destination: str | None,
) -> ClientProfile:
    update_fields: list[str] = []
    if not (profile.contact_person or "").strip() and (contact_name or "").strip():
        profile.contact_person = contact_name.strip()
        update_fields.append("contact_person")
    if not (profile.default_destination or "").strip() and (destination or "").strip():
        profile.default_destination = destination.strip()
        update_fields.append("default_destination")
    if update_fields:
        update_fields.append("updated_at")
        profile.save(update_fields=update_fields)
    return profile


@transaction.atomic
def link_walk_in_orders_to_client_profile(*, profile: ClientProfile, phone_number: str | None = None) -> int:
    """
    Attach historical walk-in orders to a profile by phone number.

    Walk-in name/phone fields are intentionally preserved for audit/history.
    """
    candidates = phone_lookup_candidates(phone_number or profile.phone_number)
    if not candidates:
        return 0

    return SlaughterOrder.objects.filter(client__isnull=True, client_phone__in=candidates).update(client=profile)


def find_manageable_client_profile_by_phone(phone_number: str | None) -> ClientProfile | None:
    candidates = phone_lookup_candidates(phone_number)
    if not candidates:
        return None

    profiles = list(
        ClientProfile.objects.select_related("user").filter(phone_number__in=candidates)
    )
    if not profiles:
        return None

    def _priority(profile: ClientProfile) -> int:
        linked_user = profile.user
        if linked_user is None:
            return 2
        if linked_user.role == User.Role.CLIENT:
            return 0
        if linked_user.role == User.Role.WALKIN:
            return 1
        return 3

    manageable = [profile for profile in profiles if profile.user is None or _client_management_role_for(profile.user)]
    if not manageable:
        return None
    manageable.sort(key=_priority)
    return manageable[0]


@transaction.atomic
def get_or_create_walk_in_profile(
    *,
    contact_name: str,
    phone_number: str | None,
    destination: str | None = None,
) -> ClientProfile | None:
    normalized_phone = normalize_phone(phone_number)
    if not normalized_phone:
        return None

    default_destination = (destination or "").strip() or None
    for _attempt in range(3):
        profile = find_manageable_client_profile_by_phone(normalized_phone)
        if profile is not None:
            return _apply_walk_in_profile_defaults(
                profile,
                contact_name=contact_name,
                destination=default_destination,
            )

        existing_user = User.objects.filter(phone_number=normalized_phone).first()
        if existing_user is not None:
            if not _client_management_role_for(existing_user):
                return None
            try:
                profile = existing_user.client_profile
            except ClientProfile.DoesNotExist:
                try:
                    with transaction.atomic():
                        profile = ClientProfile.objects.create(
                            user=existing_user,
                            account_type=ClientProfile.AccountType.UNCLASSIFIED,
                            contact_person=(contact_name or "").strip(),
                            phone_number=normalized_phone,
                            address="",
                            default_destination=default_destination,
                        )
                except IntegrityError:
                    continue
            return _apply_walk_in_profile_defaults(
                profile,
                contact_name=contact_name,
                destination=default_destination,
            )

        try:
            with transaction.atomic():
                walk_in_user = User.objects.create_user(
                    username=generate_walk_in_username(normalized_phone),
                    password=None,
                    role=User.Role.WALKIN,
                    phone_number=normalized_phone,
                )
                walk_in_user.set_unusable_password()
                walk_in_user.save(update_fields=["password"])
                profile = ClientProfile.objects.create(
                    user=walk_in_user,
                    account_type=ClientProfile.AccountType.UNCLASSIFIED,
                    contact_person=(contact_name or "").strip(),
                    phone_number=normalized_phone,
                    address="",
                    default_destination=default_destination,
                )
        except IntegrityError:
            continue
        return profile

    profile = find_manageable_client_profile_by_phone(normalized_phone)
    if profile is not None:
        return _apply_walk_in_profile_defaults(
            profile,
            contact_name=contact_name,
            destination=default_destination,
        )
    return None


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

    if getattr(user, "role", "") in CLIENT_MANAGEMENT_ROLES:
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
    link_walk_in_orders_to_client_profile(profile=profile, phone_number=phone_number)

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
