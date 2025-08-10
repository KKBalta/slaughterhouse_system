
from django.db import transaction
from django.contrib.auth import get_user_model
from .models import ClientProfile
from reception.models import SlaughterOrder

User = get_user_model()

@transaction.atomic
def create_user_with_profile(username, password, role, **profile_data) -> User:
    """
    Creates a new User and their associated ClientProfile in a single transaction.
    """
    # The create_user method handles password hashing.
    user = User.objects.create_user(
        username=username,
        password=password,
        role=role
    )

    if profile_data:
        ClientProfile.objects.create(user=user, **profile_data)
    
    return user

@transaction.atomic
def update_user_profile(user: User, **profile_data) -> ClientProfile:
    """
    Updates the ClientProfile for a given user.
    """
    # Using update_or_create is robust, handling cases where a profile might not exist yet.
    profile, created = ClientProfile.objects.update_or_create(
        user=user,
        defaults=profile_data
    )
    return profile

@transaction.atomic
def assign_role_to_user(user: User, new_role: str) -> User:
    """
    Assigns a new role to a user.
    """
    # In the future, add permission checks here to see if the requesting user
    # is allowed to perform this action.
    user.role = new_role
    user.save(update_fields=['role'])
    return user

@transaction.atomic
def convert_walk_in_to_profile(phone_number: str, user_data: dict, profile_data: dict) -> ClientProfile:
    """
    Converts a walk-in customer into a registered client with a profile.
    - Creates a new User and ClientProfile.
    - Finds past orders matching the phone number and associates them with the new profile.
    """
    user = User.objects.create_user(**user_data)
    profile_data['user'] = user
    profile = ClientProfile.objects.create(**profile_data)

    orders_to_update = SlaughterOrder.objects.filter(
        client__isnull=True,
        client_phone=phone_number
    )
    
    # Perform a bulk update for efficiency.
    orders_to_update.update(
        client=profile,
        client_name='',
        client_phone=''
    )
        
    return profile

# --- Lifecycle & Security Services ---

def deactivate_user(user: User) -> User:
    """Safely deactivates a user's account."""
    user.is_active = False
    user.save(update_fields=['is_active'])
    return user

def reactivate_user(user: User) -> User:
    """Reactivates a user's account."""
    user.is_active = True
    user.save(update_fields=['is_active'])
    return user

def change_user_password(user: User, old_password: str, new_password: str) -> bool:
    """Allows a user to change their own password."""
    if user.check_password(old_password):
        user.set_password(new_password)
        user.save(update_fields=['password'])
        return True
    return False

def admin_reset_user_password(user: User, new_password: str) -> User:
    """Allows an admin to reset a user's password."""
    user.set_password(new_password)
    user.save(update_fields=['password'])
    return user

def archive_client_profile(client_profile: ClientProfile) -> ClientProfile:
    """Archives a client's profile by using the soft-delete method."""
    client_profile.soft_delete() # This uses the method from BaseModel
    return client_profile
