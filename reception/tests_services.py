from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal, WeightLog
from reception.models import SlaughterOrder
from reception.services import (
    add_animal_to_order,
    bill_order,
    cancel_slaughter_order,
    create_batch_animals,
    create_slaughter_order,
    generate_order_number,
    remove_animal_from_order,
    update_order_status_from_animals,
    update_slaughter_order,
)
from users.models import ClientProfile

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def reception_state():
    user = User.objects.create_user(username="testclient", role=User.Role.CLIENT)
    client_profile = ClientProfile.objects.create(
        user=user,
        account_type="INDIVIDUAL",
        phone_number="1234567890",
        address="123 Test St",
    )
    service_package = ServicePackage.objects.create(
        name="Full Service", includes_disassembly=True, includes_delivery=True
    )
    service_package_simple = ServicePackage.objects.create(name="Simple Service")
    return {
        "user": user,
        "client_profile": client_profile,
        "service_package": service_package,
        "service_package_simple": service_package_simple,
    }


@pytest.fixture
def make_order(reception_state):
    def _make_order(**kwargs):
        defaults = {
            "client_id": reception_state["client_profile"].id,
            "service_package_id": reception_state["service_package"].id,
            "order_datetime": timezone.now(),
            "animals_data": [],
        }
        defaults.update(kwargs)
        return create_slaughter_order(**defaults)

    return _make_order


class TestReceptionServices:
    def test_create_slaughter_order_service(self, reception_state):
        animals_data = [
            {"animal_type": "cattle", "identification_tag": "CATTLE-001", "details_data": {"breed": "Angus"}},
            {"animal_type": "sheep", "identification_tag": "SHEEP-001", "details_data": {"breed": "Merino"}},
        ]
        order = create_slaughter_order(
            client_id=reception_state["client_profile"].id,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=animals_data,
        )
        assert SlaughterOrder.objects.count() == 1
        assert order.animals.count() == 2

    def test_update_slaughter_order_service(self, reception_state, make_order):
        order = make_order()
        assert order.destination is None

        updated_order = update_slaughter_order(
            order=order,
            destination="New Market",
            service_package=reception_state["service_package_simple"],
        )
        assert updated_order.destination == "New Market"
        assert updated_order.service_package == reception_state["service_package_simple"]

        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with pytest.raises(ValidationError):
            update_slaughter_order(order=order, destination="Another Market")

    def test_create_slaughter_order_creates_walkin_prospect(self, reception_state):
        order = create_slaughter_order(
            client_id=None,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=[],
            client_name="Potential Client",
            client_phone="+905551234999",
            destination="Prospect Depot",
        )

        assert order.client is not None
        assert order.client.account_type == ClientProfile.AccountType.UNCLASSIFIED
        assert order.client.contact_person == "Potential Client"
        assert order.client.default_destination == "Prospect Depot"
        assert order.client.user is not None
        assert order.client.user.role == User.Role.WALKIN
        assert order.client_name == "Potential Client"
        assert order.client_phone == "+905551234999"

    def test_create_slaughter_order_reuses_existing_walkin_prospect(self, reception_state):
        walkin_user = User.objects.create_user(
            username="known-walkin",
            password=None,
            role=User.Role.WALKIN,
            phone_number="+905551234998",
        )
        walkin_user.set_unusable_password()
        walkin_user.save(update_fields=["password"])
        profile = ClientProfile.objects.create(
            user=walkin_user,
            account_type=ClientProfile.AccountType.UNCLASSIFIED,
            contact_person="Known Prospect",
            phone_number="+905551234998",
            address="",
            default_destination="",
        )

        order = create_slaughter_order(
            client_id=None,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=[],
            client_name="Known Prospect",
            client_phone="+905551234998",
            destination="Second Stop",
        )

        profile.refresh_from_db()
        assert order.client == profile
        assert profile.default_destination == "Second Stop"

    def test_cancel_slaughter_order_service(self, reception_state):
        order = create_slaughter_order(
            client_id=reception_state["client_profile"].id,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=[{"animal_type": "cattle"}],
        )
        assert order.status == SlaughterOrder.Status.PENDING

        cancelled_order = cancel_slaughter_order(order=order)
        assert cancelled_order.status == SlaughterOrder.Status.CANCELLED
        assert cancelled_order.animals.first().status == "disposed"

        order.status = SlaughterOrder.Status.COMPLETED
        order.save()
        with pytest.raises(ValidationError):
            cancel_slaughter_order(order=order)

    def test_update_order_status_from_animals_service(self, reception_state):
        order = create_slaughter_order(
            client_id=reception_state["client_profile"].id,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=[{"animal_type": "cattle"}, {"animal_type": "sheep"}],
        )

        animal_1 = order.animals.all()[0]
        animal_1.perform_slaughter()
        animal_1.save()

        update_order_status_from_animals(order=order)
        order.refresh_from_db()
        assert order.status == SlaughterOrder.Status.IN_PROGRESS

        for animal in order.animals.all():
            animal = Animal.objects.get(pk=animal.pk)

            if animal.status == "received":
                animal.perform_slaughter()
                animal.save()
                animal = Animal.objects.get(pk=animal.pk)

            if animal.status == "slaughtered":
                animal.prepare_carcass()
                animal.save()
                animal = Animal.objects.get(pk=animal.pk)

            if animal.status == "carcass_ready":
                WeightLog.objects.create(
                    animal=animal, weight=300.0, weight_type="hot_carcass_weight", is_group_weight=False
                )
                animal.perform_disassembly()
                animal.save()
                animal = Animal.objects.get(pk=animal.pk)

            if animal.status == "disassembled":
                animal.perform_packaging()
                animal.save()
                animal = Animal.objects.get(pk=animal.pk)

            if animal.status == "packaged":
                animal.deliver_product()
                animal.save()

        update_order_status_from_animals(order=order)
        order.refresh_from_db()
        assert order.status == SlaughterOrder.Status.COMPLETED

    def test_bill_order_service(self, reception_state, make_order):
        order = make_order()
        order.status = SlaughterOrder.Status.COMPLETED
        order.save()

        billed_order = bill_order(order=order)
        assert billed_order.status == SlaughterOrder.Status.BILLED

        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with pytest.raises(ValidationError):
            bill_order(order=order)

    def test_add_animal_to_order_service(self, reception_state, make_order):
        order = make_order()
        assert order.animals.count() == 0

        animal_data = {"animal_type": "goat", "identification_tag": "GOAT-001"}
        added_animal = add_animal_to_order(order=order, animal_data=animal_data)

        assert order.animals.count() == 1
        assert added_animal.animal_type == "goat"
        assert added_animal.identification_tag == "GOAT-001"

        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        with pytest.raises(ValidationError):
            add_animal_to_order(order=order, animal_data={"animal_type": "lamb"})

    def test_remove_animal_from_order_service(self, reception_state):
        order = create_slaughter_order(
            client_id=reception_state["client_profile"].id,
            service_package_id=reception_state["service_package"].id,
            order_datetime=timezone.now(),
            animals_data=[
                {"animal_type": "cattle", "identification_tag": "CATTLE-001"},
                {"animal_type": "sheep", "identification_tag": "SHEEP-001"},
            ],
        )
        assert order.animals.count() == 2

        animal_to_remove = order.animals.get(identification_tag="SHEEP-001")
        remove_animal_from_order(order=order, animal=animal_to_remove)

        assert order.animals.count() == 1
        assert not Animal.objects.filter(identification_tag="SHEEP-001").exists()

        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()
        animal_to_remove_2 = order.animals.get(identification_tag="CATTLE-001")
        with pytest.raises(ValidationError):
            remove_animal_from_order(order=order, animal=animal_to_remove_2)

    def test_create_batch_animals_service(self, reception_state, make_order):
        order = make_order()
        assert order.animals.count() == 0

        created_animals = create_batch_animals(
            order=order,
            animal_type="cattle",
            quantity=5,
            tag_prefix="FARM-A",
            received_date=timezone.now(),
            skip_photos=True,
        )

        assert len(created_animals) == 5
        assert order.animals.count() == 5

        tags = [animal.identification_tag for animal in created_animals]
        expected_tags = ["FARM-A-001", "FARM-A-002", "FARM-A-003", "FARM-A-004", "FARM-A-005"]
        assert sorted(tags) == sorted(expected_tags)

        for animal in created_animals:
            assert animal.animal_type == "cattle"
            assert animal.status == "received"
            assert animal.slaughter_order == order

    def test_create_batch_animals_auto_generated_tags(self, reception_state, make_order):
        order = make_order()

        created_animals = create_batch_animals(order=order, animal_type="sheep", quantity=3, skip_photos=True)

        assert len(created_animals) == 3

        for animal in created_animals:
            assert animal.identification_tag.startswith("SHEEP-BATCH-")
            assert animal.identification_tag.endswith(("-01", "-02", "-03"))

    def test_create_batch_animals_validation_errors(self, reception_state, make_order):
        order = make_order()

        with pytest.raises(ValidationError, match="Maximum 100 animals"):
            create_batch_animals(order=order, animal_type="cattle", quantity=101, skip_photos=True)

        order.status = SlaughterOrder.Status.IN_PROGRESS
        order.save()

        with pytest.raises(ValidationError, match="Can only add animals to a PENDING order"):
            create_batch_animals(order=order, animal_type="cattle", quantity=5, skip_photos=True)

    def test_create_batch_animals_different_types(self, reception_state, make_order):
        order = make_order()

        animal_types = ["cattle", "sheep", "goat", "lamb"]

        for animal_type in animal_types:
            created_animals = create_batch_animals(
                order=order,
                animal_type=animal_type,
                quantity=2,
                tag_prefix=f"TEST-{animal_type.upper()}",
                skip_photos=True,
            )

            for animal in created_animals:
                assert animal.animal_type == animal_type

        assert order.animals.count() == 8

    def test_create_batch_animals_with_received_date(self, reception_state, make_order):
        order = make_order()

        custom_date = timezone.now() - timedelta(days=1)

        created_animals = create_batch_animals(
            order=order,
            animal_type="cattle",
            quantity=3,
            received_date=custom_date,
            skip_photos=True,
        )

        for animal in created_animals:
            assert animal.received_date.date() == custom_date.date()

    def test_create_batch_animals_atomic_transaction(self, reception_state, make_order):
        order = make_order()
        initial_count = order.animals.count()

        with pytest.raises(ValidationError):
            create_batch_animals(order=order, animal_type="cattle", quantity=101, skip_photos=True)

        assert order.animals.count() == initial_count

    def test_create_batch_animals_edge_cases(self, reception_state, make_order):
        order = make_order()

        created_animals = create_batch_animals(
            order=order, animal_type="cattle", quantity=1, tag_prefix="SINGLE", skip_photos=True
        )

        assert len(created_animals) == 1
        assert created_animals[0].identification_tag == "SINGLE-001"

        order_2 = make_order()
        created_animals = create_batch_animals(
            order=order_2, animal_type="sheep", quantity=100, tag_prefix="MAX", skip_photos=True
        )

        assert len(created_animals) == 100
        assert order_2.animals.count() == 100

        tags = [animal.identification_tag for animal in created_animals]
        assert "MAX-001" in tags
        assert "MAX-100" in tags

    def test_generate_order_number_function(self):
        order_datetime = timezone.now()

        with transaction.atomic():
            order_no_1 = generate_order_number(order_datetime)
        assert order_no_1.startswith("ORD-")

        service_package = ServicePackage.objects.create(name="Order Number Service")
        order1 = create_slaughter_order(
            client_id=None,
            service_package_id=str(service_package.id),
            order_datetime=order_datetime,
            animals_data=[],
            client_name="Test Client 1",
            client_phone="5551234567",
        )
        assert order1.slaughter_order_no == order_no_1

        with transaction.atomic():
            order_no_2 = generate_order_number(order_datetime)
        assert order_no_2.startswith("ORD-")

        num_1 = int(order_no_1.split("-")[-1])
        num_2 = int(order_no_2.split("-")[-1])

        assert num_2 == num_1 + 1

        date_part_1 = order_no_1.split("-")[1]
        date_part_2 = order_no_2.split("-")[1]
        assert date_part_1 == date_part_2


@pytest.mark.skipif(
    "sqlite" in str(settings.DATABASES.get("default", {}).get("ENGINE", "")).lower(),
    reason="Concurrent tests not supported with SQLite (table locking)",
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_order_creation_race_condition():
    service_package = ServicePackage.objects.create(
        name="Full Service Concurrent", includes_disassembly=True, includes_delivery=True
    )
    order_datetime = timezone.now()
    orders = []
    errors = []

    def create_order():
        try:
            order = create_slaughter_order(
                client_id=None,
                service_package_id=str(service_package.id),
                order_datetime=order_datetime,
                animals_data=[],
                client_name="Test Client",
                client_phone="1234567890",
            )
            orders.append(order.slaughter_order_no)
        except Exception as exc:
            errors.append(str(exc))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(create_order) for _ in range(20)]
        [future.result() for future in futures]

    assert len(set(orders)) == len(orders), (
        f"All order numbers should be unique. Got duplicates: {[x for x in orders if orders.count(x) > 1]}"
    )

    for order_no in orders:
        assert order_no.startswith("ORD-"), f"Order number should start with 'ORD-': {order_no}"
        parts = order_no.split("-")
        assert len(parts) == 3, f"Order number should have 3 parts: {order_no}"
        assert len(parts[1]) == 8, f"Date part should be 8 digits: {order_no}"
        assert len(parts[2]) == 4, f"Sequence part should be 4 digits: {order_no}"

    numbers = [int(order_no.split("-")[-1]) for order_no in sorted(orders)]
    expected_numbers = list(range(1, len(orders) + 1))
    assert numbers == expected_numbers, f"Order numbers should be sequential: {numbers}"

    assert len(errors) == 0, f"No errors should occur during concurrent creation: {errors}"
