from contextlib import nullcontext
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import ProgrammingError
from django.utils import timezone

from core.models import ServicePackage
from reception.models import SlaughterOrder

from .models import ClientProfile, User

pytestmark = pytest.mark.django_db


def test_backfill_walkin_profiles_command_creates_users_profiles_and_links_orders():
    service_package = ServicePackage.objects.create(name="Legacy Backfill Package")
    first = SlaughterOrder.objects.create(
        client_name="Legacy Walker",
        client_phone="(555) 123-4000",
        order_datetime=timezone.now(),
        service_package=service_package,
        destination="North Gate",
    )
    second = SlaughterOrder.objects.create(
        client_name="Legacy Walker",
        client_phone="5551234000",
        order_datetime=timezone.now() + timedelta(days=1),
        service_package=service_package,
        destination="South Gate",
    )
    SlaughterOrder.objects.create(
        client_name="No Phone Legacy",
        client_phone="",
        order_datetime=timezone.now() + timedelta(days=2),
        service_package=service_package,
    )

    stdout = StringIO()
    call_command("backfill_walkin_profiles", stdout=stdout)

    profile = ClientProfile.objects.get(phone_number="+5551234000")
    profile.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()

    assert profile.account_type == ClientProfile.AccountType.UNCLASSIFIED
    assert profile.contact_person == "Legacy Walker"
    assert profile.default_destination == "South Gate"
    assert profile.user is not None
    assert profile.user.role == User.Role.WALKIN
    assert profile.user.phone_number == "+5551234000"
    assert profile.user.has_usable_password() is False
    assert first.client == profile
    assert second.client == profile
    assert first.client_name == "Legacy Walker"
    assert second.client_phone == "5551234000"

    output = stdout.getvalue()
    assert "created_users=1" in output
    assert "created_profiles=1" in output
    assert "linked_orders=2" in output


def test_backfill_walkin_profiles_normalizes_reused_walkin_profile_to_unclassified():
    """Reused WALKIN prospect profiles should stay UNCLASSIFIED for user management."""
    service_package = ServicePackage.objects.create(name="Reuse Package")
    walkin_user = User.objects.create_user(
        username="reuse-walkin",
        password=None,
        role=User.Role.WALKIN,
        phone_number="+905551234500",
    )
    walkin_user.set_unusable_password()
    walkin_user.save(update_fields=["password"])
    profile = ClientProfile.objects.create(
        user=walkin_user,
        account_type=ClientProfile.AccountType.INDIVIDUAL,
        contact_person="Wrong Type",
        phone_number="+905551234500",
        address="",
    )
    order = SlaughterOrder.objects.create(
        client_name="Reuse Name",
        client_phone="+905551234500",
        order_datetime=timezone.now(),
        service_package=service_package,
    )

    call_command("backfill_walkin_profiles", stdout=StringIO())

    profile.refresh_from_db()
    order.refresh_from_db()
    assert profile.account_type == ClientProfile.AccountType.UNCLASSIFIED
    assert order.client == profile


def test_backfill_walkin_profiles_command_dry_run_rolls_back_changes():
    service_package = ServicePackage.objects.create(name="Legacy Backfill Package")
    order = SlaughterOrder.objects.create(
        client_name="Dry Run Walker",
        client_phone="555-222-1000",
        order_datetime=timezone.now(),
        service_package=service_package,
        destination="Dry Dock",
    )

    stdout = StringIO()
    call_command("backfill_walkin_profiles", "--dry-run", stdout=stdout)
    order.refresh_from_db()

    assert User.objects.count() == 0
    assert ClientProfile.objects.count() == 0
    assert order.client is None
    assert "Dry run complete. Database changes were rolled back." in stdout.getvalue()


def test_backfill_walkin_profiles_command_reports_missing_default_destination_column(mocker):
    mocker.patch(
        "users.management.commands.backfill_walkin_profiles.backfill_legacy_walk_in_profiles_from_orders",
        side_effect=ProgrammingError("column users_clientprofile.default_destination does not exist"),
    )

    with pytest.raises(CommandError, match="missing users.0007"):
        call_command("backfill_walkin_profiles")


def test_backfill_walkin_profiles_command_runs_per_tenant_schema_in_multitenant_mode(mocker, settings):
    settings.USE_MULTITENANT = True
    stats = {
        "unlinked_orders": 2,
        "eligible_orders": 2,
        "skipped_missing_name_or_phone": 0,
        "processed_phone_groups": 1,
        "skipped_invalid_phone_groups": 0,
        "skipped_unmanageable_phone_groups": 0,
        "created_users": 1,
        "created_profiles": 1,
        "reused_profiles": 0,
        "linked_orders": 2,
    }

    tenant_qs = mocker.MagicMock()
    tenant_qs.exclude.return_value = tenant_qs
    tenant_qs.order_by.return_value = tenant_qs
    tenant_qs.filter.return_value = tenant_qs
    tenant_qs.__iter__.return_value = iter([SimpleNamespace(schema_name="tenant_a")])

    mocker.patch(
        "users.management.commands.backfill_walkin_profiles.Client.objects.filter",
        return_value=tenant_qs,
    )
    mocker.patch(
        "users.management.commands.backfill_walkin_profiles.get_public_schema_name",
        return_value="public",
    )
    mocker.patch(
        "users.management.commands.backfill_walkin_profiles.schema_context",
        side_effect=lambda _schema: nullcontext(),
    )
    service_mock = mocker.patch(
        "users.management.commands.backfill_walkin_profiles.backfill_legacy_walk_in_profiles_from_orders",
        return_value=stats,
    )

    stdout = StringIO()
    call_command("backfill_walkin_profiles", stdout=stdout)

    service_mock.assert_called_once()
    assert "[tenant_a] Walk-in profile backfill:" in stdout.getvalue()
