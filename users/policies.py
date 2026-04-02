from __future__ import annotations

from users.models import User


TENANT_USER_MANAGER_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN})
CLIENT_ACCOUNT_MANAGER_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR})
TENANT_SETTINGS_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN})
OPERATIONAL_ROLES = frozenset({User.Role.OWNER, User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR})
OWNER_LOCKED_ROLES = frozenset({User.Role.OWNER})
STAFF_MANAGED_ROLES = frozenset({User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR})
ADMIN_ONLY_ROLES = frozenset({User.Role.ADMIN})
OWNER_CREATABLE_TENANT_ROLES = (User.Role.MANAGER, User.Role.OPERATOR, User.Role.CLIENT)
ADMIN_CREATABLE_TENANT_ROLES = (User.Role.ADMIN, User.Role.MANAGER, User.Role.OPERATOR, User.Role.CLIENT)


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


def can_access_reception(user) -> bool:
    return _role_of(user) in OPERATIONAL_ROLES


def can_create_role(actor, role: str) -> bool:
    if role == User.Role.CLIENT:
        return can_manage_client_accounts(actor)
    actor_role = _role_of(actor)
    if role in ADMIN_ONLY_ROLES:
        return actor_role == User.Role.ADMIN
    if role in STAFF_MANAGED_ROLES:
        return can_manage_tenant_users(actor)
    return False


def creatable_roles_for(actor) -> tuple[str, ...]:
    actor_role = _role_of(actor)
    if actor_role == User.Role.ADMIN:
        return ADMIN_CREATABLE_TENANT_ROLES
    if actor_role == User.Role.OWNER:
        return OWNER_CREATABLE_TENANT_ROLES
    if can_manage_client_accounts(actor):
        return (User.Role.CLIENT,)
    return ()


def can_edit_user(actor, target) -> bool:
    target_role = getattr(target, "role", "") or ""
    if not getattr(actor, "is_authenticated", False) or not target_role:
        return False
    if target_role in OWNER_LOCKED_ROLES:
        return False
    if target_role in ADMIN_ONLY_ROLES:
        return _role_of(actor) == User.Role.ADMIN
    if target_role == User.Role.CLIENT:
        return can_manage_client_accounts(actor)
    return can_manage_tenant_users(actor)


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
        "can_access_django_admin": can_access_django_admin(user),
    }
