"""Authentication backends for multi-tenant mode."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import connection
from django_tenants.utils import get_public_schema_name

from tenants.email_index import normalize_phone


def _looks_like_phone(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    if any(not (ch.isdigit() or ch in "+-() .") for ch in raw):
        return False
    return sum(ch.isdigit() for ch in raw) >= 6


class PlatformAdminBackend:
    """
    Authenticates `PlatformAdmin` rows stored only in the public schema.
    Must be listed before ModelBackend so public-schema sessions resolve correctly.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if connection.schema_name != get_public_schema_name():
            return None
        if not username or not password:
            return None

        from tenants.models import PlatformAdmin

        email = kwargs.get("email", username)
        try:
            user = PlatformAdmin.objects.get(email__iexact=email)
        except PlatformAdmin.DoesNotExist:
            return None
        if not user.check_password(password):
            return None
        if not user.is_active:
            return None
        return user

    def get_user(self, user_id):
        if connection.schema_name != get_public_schema_name():
            return None
        from tenants.models import PlatformAdmin

        try:
            return PlatformAdmin.objects.get(pk=user_id)
        except PlatformAdmin.DoesNotExist:
            return None


class PublicSchemaSafeModelBackend(ModelBackend):
    """
    Tenant `User` lives only in tenant schemas. On the public schema there is no
    `users_user` table, so the stock ModelBackend must not run there.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if connection.schema_name == get_public_schema_name():
            return None
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            return user
        # ModelBackend matches USERNAME_FIELD with exact case; add fallbacks.
        if not username or not password:
            return None
        User = get_user_model()
        # Case-insensitive username (e.g. email local part differs only by case).
        try:
            by_username_ci = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            by_username_ci = None
        except User.MultipleObjectsReturned:
            by_username_ci = None
        if by_username_ci and by_username_ci.check_password(password) and self.user_can_authenticate(by_username_ci):
            return by_username_ci
        # SPA often sends email in the "username" field.
        try:
            by_email = User.objects.get(email__iexact=username)
        except User.DoesNotExist:
            by_email = None
        except User.MultipleObjectsReturned:
            by_email = None
        if by_email and by_email.check_password(password) and self.user_can_authenticate(by_email):
            return by_email
        if _looks_like_phone(username):
            phone_candidates = []
            raw_phone = (username or "").strip()
            if raw_phone:
                phone_candidates.append(raw_phone)
            normalized_phone = normalize_phone(username)
            if normalized_phone and normalized_phone not in phone_candidates:
                phone_candidates.append(normalized_phone)
            try:
                by_phone = User.objects.get(phone_number__in=phone_candidates)
            except User.DoesNotExist:
                return None
            except User.MultipleObjectsReturned:
                return None
            if by_phone.check_password(password) and self.user_can_authenticate(by_phone):
                return by_phone
        return None

    def get_user(self, user_id):
        if connection.schema_name == get_public_schema_name():
            return None
        return super().get_user(user_id)
