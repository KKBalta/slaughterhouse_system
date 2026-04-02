from __future__ import annotations

import pytest

from tenants import email_index
from users.models import User
from users.signals import remove_email_membership_on_user_delete, sync_email_membership_on_user_save

pytestmark = pytest.mark.django_db


def test_sync_email_membership_signal_noops_without_multitenant(monkeypatch, settings):
    user = User.objects.create_user(username="signal-user", password="password123")
    settings.USE_MULTITENANT = False

    def _boom(_user):
        raise AssertionError("sync_user_membership should not be called")

    monkeypatch.setattr(email_index, "sync_user_membership", _boom)

    sync_email_membership_on_user_save(User, user)


def test_sync_email_membership_signal_calls_helper(monkeypatch, settings):
    user = User.objects.create_user(username="signal-user-2", password="password123")
    settings.USE_MULTITENANT = True
    calls = []

    monkeypatch.setattr(email_index, "sync_user_membership", lambda instance: calls.append(instance))

    sync_email_membership_on_user_save(User, user)

    assert calls == [user]


def test_remove_email_membership_signal_noops_without_multitenant(monkeypatch, settings):
    user = User.objects.create_user(username="signal-user-3", password="password123")
    settings.USE_MULTITENANT = False

    def _boom(_user):
        raise AssertionError("remove_user_membership should not be called")

    monkeypatch.setattr(email_index, "remove_user_membership", _boom)

    remove_email_membership_on_user_delete(User, user)


def test_remove_email_membership_signal_calls_helper(monkeypatch, settings):
    user = User.objects.create_user(username="signal-user-4", password="password123")
    settings.USE_MULTITENANT = True
    calls = []

    monkeypatch.setattr(email_index, "remove_user_membership", lambda instance: calls.append(instance))

    remove_email_membership_on_user_delete(User, user)

    assert calls == [user]
