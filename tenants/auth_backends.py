"""Authentication backends for multi-tenant mode."""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend
from django.db import connection
from django_tenants.utils import get_public_schema_name


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
        return super().authenticate(request, username=username, password=password, **kwargs)

    def get_user(self, user_id):
        if connection.schema_name == get_public_schema_name():
            return None
        return super().get_user(user_id)
