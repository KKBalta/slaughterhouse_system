import uuid
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from processing.models import Animal  # Add Animal import
from processing.services import create_animal
from users.models import ClientProfile

from .models import ServicePackage, SlaughterOrder

# Maximum retry attempts for order creation under race conditions
MAX_ORDER_CREATION_RETRIES = 10


def generate_order_number(order_datetime=None) -> str:
    """
    Generates a unique order number for a given date.

    IMPORTANT: This function must be called within a transaction.atomic() context
    that also includes the order creation. The caller is responsible for ensuring
    proper transaction boundaries to prevent race conditions.

    The function uses select_for_update() to lock existing orders for the date.
    This prevents race conditions when there are existing orders, but when no
    orders exist for the date, the caller must handle potential IntegrityError
    with retry logic.

    Args:
        order_datetime: The datetime for the order. If None, uses current time.

    Returns:
        A unique order number string in format: ORD-YYYYMMDD-NNNN

    Raises:
        ValidationError: If order number generation fails
    """
    if order_datetime:
        # Handle both datetime (has .date()) and date (use as-is)
        order_date = order_datetime.date() if hasattr(order_datetime, "date") else order_datetime
        date_str = order_date.strftime("%Y%m%d")
    else:
        order_date = timezone.now().date()
        date_str = order_date.strftime("%Y%m%d")

    # Use select_for_update() to lock all orders for this date.
    # This prevents race conditions when multiple threads try to generate
    # order numbers simultaneously. The lock is held until the transaction
    # commits (which should include the order creation in the caller).
    # NOTE: When no orders exist for the date, select_for_update() locks nothing,
    # so the caller must handle IntegrityError with retry logic.
    last_order = (
        SlaughterOrder.objects.filter(slaughter_order_no__startswith=f"ORD-{date_str}")
        .select_for_update()
        .order_by("-slaughter_order_no")
        .first()
    )

    if last_order:
        # Extract the number from the last order
        try:
            last_num = int(last_order.slaughter_order_no.split("-")[-1])
            count = last_num + 1
        except (ValueError, IndexError):
            # Fallback if order number format is unexpected
            # Count existing orders for this date
            count = SlaughterOrder.objects.filter(order_datetime__date=order_date).count() + 1
    else:
        count = 1

    order_number = f"ORD-{date_str}-{count:04d}"

    # Double-check uniqueness (defense in depth)
    if SlaughterOrder.objects.filter(slaughter_order_no=order_number).exists():
        # If somehow a duplicate exists, increment and try again
        count += 1
        order_number = f"ORD-{date_str}-{count:04d}"

    return order_number


def create_slaughter_order(
    client_id: str,
    service_package_id: str,
    order_datetime: datetime,
    animals_data: list,
    client_name: str = None,
    client_phone: str = None,
    destination: str = None,
) -> SlaughterOrder:
    """
    Creates a new SlaughterOrder and all its associated animals.
    Handles both registered and walk-in clients.
    Generates order number atomically to prevent race conditions.

    Uses retry logic to handle the edge case where multiple threads try to create
    the first order of the day simultaneously (when select_for_update has no rows
    to lock).
    """
    client_profile = None
    if client_id:
        client_profile = ClientProfile.objects.get(id=client_id)

    service_package = ServicePackage.objects.get(id=service_package_id)

    # Retry loop to handle race conditions when creating orders
    # This is necessary because select_for_update() cannot lock rows that don't exist yet
    last_exception = None
    for _attempt in range(MAX_ORDER_CREATION_RETRIES):
        try:
            with transaction.atomic():
                # Generate order number within the transaction
                # select_for_update() will lock existing orders for this date
                order_number = generate_order_number(order_datetime)

                order = SlaughterOrder.objects.create(
                    client=client_profile,
                    service_package=service_package,
                    order_datetime=order_datetime,
                    client_name=client_name if not client_profile else "",
                    client_phone=client_phone if not client_profile else "",
                    destination=destination,
                    slaughter_order_no=order_number,
                )

                for animal_data in animals_data:
                    create_animal(order=order, **animal_data)

                order.refresh_from_db()
                return order

        except IntegrityError as e:
            # Duplicate key error - another thread created an order with this number
            # Retry with a fresh transaction and new order number
            last_exception = e
            continue

    # If we exhausted all retries, raise the last exception
    raise ValidationError(
        f"Failed to create order after {MAX_ORDER_CREATION_RETRIES} attempts due to high concurrency. "
        f"Last error: {last_exception}"
    )


@transaction.atomic
def update_slaughter_order(order: SlaughterOrder, **data) -> SlaughterOrder:
    """
    Updates a slaughter order with given data.
    Prevents updates if the order is no longer pending.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError("Cannot update an order that is already in progress, completed, or cancelled.")

    allowed_fields = ["service_package", "destination", "order_datetime"]
    for field, value in data.items():
        if field in allowed_fields:
            setattr(order, field, value)

    order.save()
    return order


@transaction.atomic
def cancel_slaughter_order(order: SlaughterOrder) -> SlaughterOrder:
    """
    Cancels a slaughter order if it's still pending.
    Associated animals are also marked as disposed.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError("Cannot cancel an order that is already in progress or completed.")

    order.status = SlaughterOrder.Status.CANCELLED
    order.save()

    for animal in order.animals.all():
        animal.dispose_animal()
        animal.save()

    return order


@transaction.atomic
def update_order_status_from_animals(order: SlaughterOrder) -> SlaughterOrder:
    """
    Updates the order status based on the collective status of its animals.
    """
    animal_statuses = {animal.status for animal in order.animals.all()}

    if not animal_statuses:
        return order  # No animals, no status change

    if all(status in ["delivered", "returned", "disposed"] for status in animal_statuses):
        order.status = SlaughterOrder.Status.COMPLETED
    elif animal_statuses.intersection(["slaughtered", "carcass_ready", "disassembled", "packaged"]):
        order.status = SlaughterOrder.Status.IN_PROGRESS

    order.save()
    return order


@transaction.atomic
def bill_order(order: SlaughterOrder) -> SlaughterOrder:
    """
    Marks an order as billed if it is complete.
    """
    if order.status != SlaughterOrder.Status.COMPLETED:
        raise ValidationError("Cannot bill an order that is not yet completed.")

    order.status = SlaughterOrder.Status.BILLED
    order.save()
    return order


@transaction.atomic
def add_animal_to_order(order: SlaughterOrder, animal_data: dict) -> Animal:
    """
    Adds a new animal to a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError("Can only add animals to a PENDING order.")

    animal = create_animal(order=order, **animal_data)
    return animal


@transaction.atomic
def remove_animal_from_order(order: SlaughterOrder, animal: Animal):
    """
    Removes an animal from a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError("Can only remove animals from a PENDING order.")

    if animal.slaughter_order != order:
        raise ValidationError("Animal does not belong to the specified order.")

    animal.delete()


@transaction.atomic
def create_batch_animals(
    order: SlaughterOrder,
    animal_type: str,
    quantity: int,
    tag_prefix: str = None,
    received_date: datetime = None,
    skip_photos: bool = False,
) -> list:
    """
    Creates multiple animals at once for a PENDING order with auto-generated tags.

    Args:
        order: The SlaughterOrder to add animals to
        animal_type: Type of animals to create
        quantity: Number of animals to create
        tag_prefix: Optional custom prefix for tags
        received_date: Optional custom received date, defaults to now
        skip_photos: Whether to skip photo requirements for batch creation

    Returns:
        List of created Animal objects
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError("Can only add animals to a PENDING order.")

    if quantity > 100:
        raise ValidationError("Maximum 100 animals can be created in a single batch.")

    created_animals = []
    current_time = received_date or timezone.now()

    # Generate unique tags for the batch
    for i in range(1, quantity + 1):
        if tag_prefix:
            # Use custom prefix with sequential numbering
            identification_tag = f"{tag_prefix}-{i:03d}"
        else:
            # Use auto-generated tags with batch identifier
            batch_id = uuid.uuid4().hex[:6].upper()
            identification_tag = f"{animal_type.upper()}-BATCH-{batch_id}-{i:02d}"

        animal_data = {
            "animal_type": animal_type,
            "identification_tag": identification_tag,
            "received_date": current_time,
        }

        # Create animal without photos if skip_photos is True
        # Photos can be added later via edit functionality
        animal = create_animal(order=order, **animal_data)
        created_animals.append(animal)

    return created_animals
