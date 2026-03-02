"""
Pytest configuration and fixtures for the slaughterhouse system.

This file provides shared fixtures and configuration for all test modules.
Updated to use factory-boy DjangoModelFactory pattern per official docs.
"""

import os
from datetime import date, datetime
from decimal import Decimal

import factory
import pytest
from django.utils import timezone
from faker import Faker

# Set the Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")

import django

django.setup()


# ============================================================================
# Model Factories (using factory-boy DjangoModelFactory pattern)
# See: https://factoryboy.readthedocs.io/en/stable/orms.html
# ============================================================================


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating User objects."""

    class Meta:
        model = "users.User"
        skip_postgeneration_save = True  # Optimization for Django 4.2+

    username = factory.Sequence(lambda n: f"user_{n}")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@example.com")
    is_active = True
    is_staff = False

    @factory.lazy_attribute
    def role(self):
        from users.models import User

        return User.Role.ADMIN


class ClientProfileFactory(factory.django.DjangoModelFactory):
    """Factory for creating ClientProfile objects."""

    class Meta:
        model = "users.ClientProfile"

    user = factory.SubFactory(
        UserFactory,
        role=factory.LazyAttribute(lambda obj: __import__("users.models", fromlist=["User"]).User.Role.CLIENT),
    )
    account_type = factory.LazyAttribute(
        lambda obj: __import__("users.models", fromlist=["ClientProfile"]).ClientProfile.AccountType.INDIVIDUAL
    )
    phone_number = factory.Sequence(lambda n: f"555-{n:04d}")
    address = factory.Faker("address")


class ServicePackageFactory(factory.django.DjangoModelFactory):
    """Factory for creating ServicePackage objects."""

    class Meta:
        model = "core.ServicePackage"

    name = factory.Sequence(lambda n: f"Test Package {n}")
    includes_disassembly = True
    includes_delivery = True


class SlaughterOrderFactory(factory.django.DjangoModelFactory):
    """Factory for creating SlaughterOrder objects."""

    class Meta:
        model = "reception.SlaughterOrder"

    service_package = factory.SubFactory(ServicePackageFactory)
    order_datetime = factory.LazyFunction(timezone.now)
    status = "PENDING"
    client_name = factory.Faker("name")
    client_phone = factory.Sequence(lambda n: f"555-{n:04d}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to handle client vs client_name logic."""
        client = kwargs.pop("client", None)
        if client is not None:
            kwargs["client"] = client
            kwargs.pop("client_name", None)
        return super()._create(model_class, *args, **kwargs)


class AnimalFactory(factory.django.DjangoModelFactory):
    """Factory for creating Animal objects."""

    class Meta:
        model = "processing.Animal"

    slaughter_order = factory.SubFactory(SlaughterOrderFactory)
    animal_type = "cattle"
    identification_tag = factory.Sequence(lambda n: f"TAG-{n:05d}")


class WeightLogFactory(factory.django.DjangoModelFactory):
    """Factory for creating WeightLog objects."""

    class Meta:
        model = "processing.WeightLog"

    animal = factory.SubFactory(AnimalFactory)
    weight = factory.LazyFunction(lambda: Decimal("100.00"))
    weight_type = "live_weight"
    is_group_weight = False


# ============================================================================
# Pytest Fixtures wrapping factories (for easier dependency injection)
# ============================================================================


@pytest.fixture
def user_factory_fixture(db):
    """
    Fixture that provides UserFactory.
    Usage: user_factory_fixture.create(username='custom')
    """
    return UserFactory


@pytest.fixture
def client_profile_factory_fixture(db):
    """Fixture that provides ClientProfileFactory."""
    return ClientProfileFactory


@pytest.fixture
def service_package_factory_fixture(db):
    """Fixture that provides ServicePackageFactory."""
    return ServicePackageFactory


@pytest.fixture
def slaughter_order_factory_fixture(db):
    """Fixture that provides SlaughterOrderFactory."""
    return SlaughterOrderFactory


@pytest.fixture
def animal_factory_fixture(db):
    """Fixture that provides AnimalFactory."""
    return AnimalFactory


@pytest.fixture
def weight_log_factory_fixture(db):
    """Fixture that provides WeightLogFactory."""
    return WeightLogFactory


# ============================================================================
# Legacy Factory Fixtures (backward compatibility)
# These match the original API for existing tests
# ============================================================================


@pytest.fixture
def user_factory(db):
    """Legacy factory for creating User objects."""
    from users.models import User

    def create_user(username=None, password="testpass123", role=None, is_staff=False, is_active=True, **kwargs):
        fake = Faker()

        if username is None:
            username = fake.user_name()
        if role is None:
            role = User.Role.ADMIN

        user = User.objects.create_user(
            username=username, password=password, role=role, is_staff=is_staff, is_active=is_active, **kwargs
        )
        return user

    return create_user


@pytest.fixture
def client_profile_factory(db, user_factory):
    """Legacy factory for creating ClientProfile objects."""
    from users.models import ClientProfile

    def create_profile(user=None, account_type=None, phone_number="1234567890", address="123 Test Street", **kwargs):
        from users.models import User

        if user is None:
            user = user_factory(role=User.Role.CLIENT)
        if account_type is None:
            account_type = ClientProfile.AccountType.INDIVIDUAL

        return ClientProfile.objects.create(
            user=user, account_type=account_type, phone_number=phone_number, address=address, **kwargs
        )

    return create_profile


@pytest.fixture
def service_package_factory(db):
    """Legacy factory for creating ServicePackage objects."""
    from core.models import ServicePackage

    fake = Faker()

    def create_package(name=None, includes_disassembly=True, includes_delivery=True, **kwargs):
        if name is None:
            name = f"Test Package {fake.random_int(1, 10000)}"

        return ServicePackage.objects.create(
            name=name, includes_disassembly=includes_disassembly, includes_delivery=includes_delivery, **kwargs
        )

    return create_package


@pytest.fixture
def slaughter_order_factory(db, client_profile_factory, service_package_factory):
    """Legacy factory for creating SlaughterOrder objects."""
    from reception.models import SlaughterOrder

    def create_order(
        client=None, client_name=None, service_package=None, order_datetime=None, status="PENDING", **kwargs
    ):
        if service_package is None:
            service_package = service_package_factory()
        if order_datetime is None:
            order_datetime = timezone.now()

        order_kwargs = {
            "service_package": service_package,
            "order_datetime": order_datetime,
            "status": status,
            **kwargs,
        }

        if client is not None:
            order_kwargs["client"] = client
        elif client_name is not None:
            order_kwargs["client_name"] = client_name
        else:
            order_kwargs["client_name"] = "Walk-in Customer"

        return SlaughterOrder.objects.create(**order_kwargs)

    return create_order


@pytest.fixture
def animal_factory(db, slaughter_order_factory):
    """Legacy factory for creating Animal objects."""
    from processing.models import Animal

    fake = Faker()

    def create_animal(slaughter_order=None, animal_type="cattle", identification_tag=None, status="received", **kwargs):
        if slaughter_order is None:
            slaughter_order = slaughter_order_factory()
        if identification_tag is None:
            identification_tag = f"TAG-{fake.random_int(10000, 99999)}"

        return Animal.objects.create(
            slaughter_order=slaughter_order, animal_type=animal_type, identification_tag=identification_tag, **kwargs
        )

    return create_animal


@pytest.fixture
def weight_log_factory(db, animal_factory):
    """Legacy factory for creating WeightLog objects."""
    from processing.models import WeightLog

    def create_weight_log(animal=None, weight=100.0, weight_type="live_weight", is_group_weight=False, **kwargs):
        if animal is None:
            animal = animal_factory()

        return WeightLog.objects.create(
            animal=animal,
            weight=Decimal(str(weight)),
            weight_type=weight_type,
            is_group_weight=is_group_weight,
            **kwargs,
        )

    return create_weight_log


# ============================================================================
# Common User Fixtures
# ============================================================================


@pytest.fixture
def admin_user(db):
    """Create an admin user for testing using DjangoModelFactory."""
    from users.models import User

    return UserFactory.create(username="admin", role=User.Role.ADMIN, is_staff=True)


@pytest.fixture
def client_user(db):
    """Create a client user with profile for testing."""
    profile = ClientProfileFactory.create()
    return profile.user


@pytest.fixture
def operator_user(db):
    """Create an operator user for testing."""
    from users.models import User

    return UserFactory.create(username="operator", role=User.Role.OPERATOR)


@pytest.fixture
def manager_user(db):
    """Create a manager user for testing."""
    from users.models import User

    return UserFactory.create(username="manager", role=User.Role.MANAGER)


@pytest.fixture
def authenticated_client(db, client, admin_user):
    """
    Provide an authenticated test client.
    Uses force_login() per pytest-django docs.
    """
    client.force_login(admin_user)
    return client


@pytest.fixture
def authenticated_api_client(db, admin_user):
    """Provide an authenticated API client."""
    from django.test import Client

    api_client = Client()
    api_client.force_login(admin_user)
    return api_client


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_order_with_animals(db):
    """Create a sample order with multiple animals using factories."""
    order = SlaughterOrderFactory.create()
    animals = []

    for i, animal_type in enumerate(["cattle", "sheep", "goat"]):
        animal = AnimalFactory.create(
            slaughter_order=order, animal_type=animal_type, identification_tag=f"TEST-{animal_type.upper()}-{i:03d}"
        )
        animals.append(animal)

    return {"order": order, "animals": animals}


@pytest.fixture
def slaughtered_animal(db):
    """Create an animal that has been slaughtered."""
    animal = AnimalFactory.create()
    animal.perform_slaughter()
    animal.save()
    return animal


@pytest.fixture
def carcass_ready_animal(db, slaughtered_animal):
    """Create an animal with carcass ready."""
    slaughtered_animal.prepare_carcass()
    slaughtered_animal.save()
    return slaughtered_animal


# ============================================================================
# Parallel Testing Support (pytest-xdist)
# See: https://pytest-xdist.readthedocs.io/
# ============================================================================


@pytest.fixture(scope="session")
def worker_db_suffix(worker_id):
    """
    Provide database suffix for parallel test workers.
    Per pytest-xdist docs: worker_id is 'master' for single-process
    or 'gw0', 'gw1', etc. for parallel workers.
    """
    if worker_id == "master":
        return ""
    return f"_{worker_id}"


# ============================================================================
# Time Freezing Fixtures (pytest-freezegun)
# See: https://github.com/ktosiek/pytest-freezegun
# ============================================================================


@pytest.fixture
def frozen_time():
    """
    Legacy fixture for freezing time.

    For new tests, prefer the built-in 'freezer' fixture from pytest-freezegun:

        @pytest.mark.freeze_time('2024-01-15')
        def test_something(freezer):
            freezer.move_to('2024-02-01')  # Can move time during test
    """
    from freezegun import freeze_time

    def freeze(time_str="2024-01-15 12:00:00"):
        return freeze_time(time_str)

    return freeze


# ============================================================================
# Cleanup Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clean_media_files(settings, tmp_path):
    """Clean up media files after each test."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    yield


@pytest.fixture
def temp_file():
    """Create a temporary file for testing file uploads."""
    import tempfile

    def create_temp_file(content=b"test content", suffix=".txt"):
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp.write(content)
        temp.close()
        return temp.name

    return create_temp_file


# ============================================================================
# Database Setup Fixtures
# ============================================================================


@pytest.fixture
def db_setup(db):
    """Set up common database objects needed for tests using factories."""
    from users.models import User

    # Create service packages
    full_service = ServicePackageFactory.create(name="Full Service", includes_disassembly=True, includes_delivery=True)
    basic_service = ServicePackageFactory.create(
        name="Basic Service", includes_disassembly=False, includes_delivery=False
    )

    # Create users with factories
    admin = UserFactory.create(username="setup_admin", role=User.Role.ADMIN, is_staff=True)
    operator = UserFactory.create(username="setup_operator", role=User.Role.OPERATOR)
    client_profile = ClientProfileFactory.create()

    return {
        "full_service": full_service,
        "basic_service": basic_service,
        "admin": admin,
        "operator": operator,
        "client": client_profile.user,
        "client_profile": client_profile,
    }


# ============================================================================
# Mocking Helpers (pytest-mock)
# See: https://pytest-mock.readthedocs.io/
#
# The 'mocker' fixture is auto-provided by pytest-mock. Usage:
#
#     def test_something(mocker):
#         mock_func = mocker.patch('mymodule.myfunction')
#         mock_func.return_value = 'mocked!'
#
#         # Also supports:
#         mocker.patch.object(obj, 'method', return_value='mocked')
#         mocker.spy(obj, 'method')  # Spy without replacing
# ============================================================================


@pytest.fixture
def mock_external_service(mocker):
    """
    Helper fixture for mocking common external services.

    Returns a dict of mock objects for common external integrations.
    """
    return {
        "email": mocker.patch("django.core.mail.send_mail"),
        "sms": mocker.patch("core.services.send_sms", create=True),
    }


# ============================================================================
# HTTP Response Mocking (responses library)
# See: https://github.com/getsentry/responses
# ============================================================================


@pytest.fixture
def mock_http_responses():
    """
    Fixture for mocking HTTP requests using responses library.

    Usage:
        def test_api_call(mock_http_responses):
            import responses

            mock_http_responses.add(
                responses.GET,
                'https://api.example.com/data',
                json={'key': 'value'},
                status=200
            )

            # Your code that makes HTTP request...
    """
    import responses

    with responses.RequestsMock() as rsps:
        yield rsps
