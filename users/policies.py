from __future__ import annotations

from users.models import CLIENT_MANAGEMENT_ROLES, User

TENANT_USER_MANAGER_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN})
CLIENT_ACCOUNT_MANAGER_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR})
TENANT_SETTINGS_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN})
REPORTING_ACCESS_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER})
OPERATIONAL_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR})
STAFF_MANAGED_ROLES = frozenset({User.Role.ADMIN, User.Role.OWNER, User.Role.MANAGER, User.Role.OPERATOR})
FULL_USER_MANAGEMENT_VISIBLE_ROLES = (
    User.Role.OWNER,
    User.Role.ADMIN,
    User.Role.MANAGER,
    User.Role.OPERATOR,
    User.Role.CLIENT,
    User.Role.WALKIN,
)
MANAGER_USER_MANAGEMENT_VISIBLE_ROLES = (
    User.Role.OPERATOR,
    User.Role.CLIENT,
    User.Role.WALKIN,
)
CLIENT_USER_MANAGEMENT_VISIBLE_ROLES = (
    User.Role.CLIENT,
    User.Role.WALKIN,
)
OWNER_CREATABLE_TENANT_ROLES = (User.Role.MANAGER, User.Role.OPERATOR, User.Role.CLIENT)
ADMIN_CREATABLE_TENANT_ROLES = (
    User.Role.OWNER,
    User.Role.ADMIN,
    User.Role.MANAGER,
    User.Role.OPERATOR,
    User.Role.CLIENT,
)


def _role_of(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return ""
    return getattr(user, "role", "") or ""


def has_any_role(user, *roles: str) -> bool:
    return _role_of(user) in roles


def can_manage_tenant_users(user) -> bool:
    return _role_of(user) in TENANT_USER_MANAGER_ROLES


def can_manage_client_accounts(user) -> bool:
    return _role_of(user) in CLIENT_ACCOUNT_MANAGER_ROLES


def can_access_user_management(user) -> bool:
    return can_manage_tenant_users(user) or can_manage_client_accounts(user)


def can_manage_company_settings(user) -> bool:
    return _role_of(user) in TENANT_SETTINGS_ROLES


def can_access_reporting(user) -> bool:
    return _role_of(user) in REPORTING_ACCESS_ROLES


def can_access_reception(user) -> bool:
    return _role_of(user) in OPERATIONAL_ROLES


def visible_user_management_roles_for(user) -> tuple[str, ...]:
    actor_role = _role_of(user)
    if actor_role in TENANT_USER_MANAGER_ROLES:
        return FULL_USER_MANAGEMENT_VISIBLE_ROLES
    if actor_role == User.Role.MANAGER:
        return MANAGER_USER_MANAGEMENT_VISIBLE_ROLES
    if can_manage_client_accounts(user):
        return CLIENT_USER_MANAGEMENT_VISIBLE_ROLES
    return ()


def can_create_role(actor, role: str) -> bool:
    actor_role = _role_of(actor)
    # ADMIN can create/assign any role (top of hierarchy)
    if actor_role == User.Role.ADMIN:
        return True
    # OWNER can create everything below ADMIN
    if actor_role == User.Role.OWNER:
        return role in OWNER_CREATABLE_TENANT_ROLES or role == User.Role.CLIENT
    # MANAGER can create OPERATOR and CLIENT
    if actor_role == User.Role.MANAGER:
        return role in (User.Role.OPERATOR, User.Role.CLIENT)
    if role in CLIENT_MANAGEMENT_ROLES:
        return can_manage_client_accounts(actor)
    return False


MANAGER_CREATABLE_TENANT_ROLES = (User.Role.OPERATOR, User.Role.CLIENT)


def creatable_roles_for(actor) -> tuple[str, ...]:
    actor_role = _role_of(actor)
    if actor_role == User.Role.ADMIN:
        return ADMIN_CREATABLE_TENANT_ROLES
    if actor_role == User.Role.OWNER:
        return OWNER_CREATABLE_TENANT_ROLES
    if actor_role == User.Role.MANAGER:
        return MANAGER_CREATABLE_TENANT_ROLES
    if can_manage_client_accounts(actor):
        return (User.Role.CLIENT,)
    return ()


def can_edit_user(actor, target) -> bool:
    target_role = getattr(target, "role", "") or ""
    if not getattr(actor, "is_authenticated", False) or not target_role:
        return False
    actor_role = _role_of(actor)
    # ADMIN can edit everyone (top of hierarchy)
    if actor_role == User.Role.ADMIN:
        return True
    # OWNER can edit everyone except ADMIN
    if actor_role == User.Role.OWNER:
        return target_role != User.Role.ADMIN
    # MANAGER can edit OPERATOR and client-facing roles
    if actor_role == User.Role.MANAGER:
        return target_role in (User.Role.OPERATOR, *CLIENT_MANAGEMENT_ROLES)
    if target_role in CLIENT_MANAGEMENT_ROLES:
        return can_manage_client_accounts(actor)
    return False


def can_edit_client_role(actor, target) -> bool:
    return False


def can_access_django_admin(user) -> bool:
    return bool(has_any_role(user, User.Role.ADMIN) and getattr(user, "is_staff", False))


def dashboard_capabilities(user) -> dict[str, bool]:
    return {
        "is_client": has_any_role(user, User.Role.CLIENT),
        "can_access_reception": can_access_reception(user),
        "can_manage_tenant_users": can_manage_tenant_users(user),
        "can_manage_client_accounts": can_manage_client_accounts(user),
        "can_access_user_management": can_access_user_management(user),
        "can_manage_company_settings": can_manage_company_settings(user),
        "can_access_reporting": can_access_reporting(user),
        "can_access_django_admin": can_access_django_admin(user),
    }
