import logging
import re
import uuid
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from processing.models import Animal  # Add Animal import
from processing.services import create_animal
from users.models import ClientProfile
from users.services import get_or_create_walk_in_profile

from .models import ServicePackage, SlaughterOrder

logger = logging.getLogger(__name__)

# Maximum retry attempts for order creation under race conditions
MAX_ORDER_CREATION_RETRIES = 10


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _resolve_destination_client(destination_client_id: str | None) -> ClientProfile | None:
    if not destination_client_id:
        return None
    return ClientProfile.objects.get(id=destination_client_id)


def _destination_display_name(destination_client: ClientProfile | None, destination: str | None) -> str:
    if destination_client is not None:
        return destination_client.get_full_name()
    return _clean_text(destination) or None


def _sequence_date_for_received_at(received_at: datetime | None):
    if received_at is None:
        return timezone.localdate()
    if timezone.is_naive(received_at):
        received_at = timezone.make_aware(received_at, timezone.get_current_timezone())
    return timezone.localdate(received_at)


def _next_same_day_tag_number(tag_prefix: str, received_at: datetime | None) -> int:
    prefix = _clean_text(tag_prefix)
    if not prefix:
        return 1

    sequence_date = _sequence_date_for_received_at(received_at)
    prefix_with_dash = f"{prefix}-"
    suffix_pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    max_suffix = 0

    existing_tags = Animal.objects.filter(
        received_date__date=sequence_date,
        identification_tag__istartswith=prefix_with_dash,
    ).values_list("identification_tag", flat=True)

    for tag in existing_tags:
        match = suffix_pattern.match((tag or "").strip())
        if match:
            max_suffix = max(max_suffix, int(match.group(1)))

    return max_suffix + 1


def _order_has_animals(order: SlaughterOrder) -> bool:
    if not getattr(order, "pk", None):
        return False
    return order.animals.exists()


def _order_has_terminal_animals(order: SlaughterOrder) -> bool:
    if not getattr(order, "pk", None):
        return False
    return order.animals.filter(status__in=["delivered", "returned", "disposed"]).exists()


def _order_has_disassembly_outputs(order: SlaughterOrder) -> bool:
    if not getattr(order, "pk", None):
        return False
    if order.animals.filter(status__in=["disassembled", "packaged", "delivered"]).exists():
        return True
    return order.animals.filter(disassembly_cuts__isnull=False).exists()


def _service_package_disassembly_mode(service_package: ServicePackage | None) -> str:
    if service_package is None or not service_package.includes_disassembly:
        return "none"

    package_name = (service_package.name or "").lower()
    if "boneless" in package_name or "kemikli" in package_name or "kemiksiz" in package_name:
        return "boneless"
    return "standard"


def can_reassign_order_client(order: SlaughterOrder) -> bool:
    return order.status == SlaughterOrder.Status.PENDING and not _order_has_animals(order)


def can_edit_order_datetime(order: SlaughterOrder) -> bool:
    return order.status == SlaughterOrder.Status.PENDING and not _order_has_animals(order)


def can_edit_order_details(order: SlaughterOrder) -> bool:
    # Legacy alias retained for callers that still treat "details" as order date edits.
    return can_edit_order_datetime(order)


def can_edit_order_service_package(order: SlaughterOrder) -> bool:
    if order.status not in {SlaughterOrder.Status.PENDING, SlaughterOrder.Status.IN_PROGRESS}:
        return False
    return not _order_has_terminal_animals(order)


def can_edit_order_destination(order: SlaughterOrder) -> bool:
    return order.status not in {SlaughterOrder.Status.CANCELLED, SlaughterOrder.Status.BILLED}


def _sync_preferred_destination_client(
    *,
    client_profile: ClientProfile | None,
    destination_client: ClientProfile | None,
) -> ClientProfile | None:
    if client_profile is None or destination_client is None:
        return client_profile

    destination_name = destination_client.get_full_name()
    update_fields: list[str] = []
    if client_profile.default_destination_client_id != destination_client.id:
        client_profile.default_destination_client = destination_client
        update_fields.append("default_destination_client")
    if (client_profile.default_destination or "").strip() != destination_name:
        client_profile.default_destination = destination_name
        update_fields.append("default_destination")
    if update_fields:
        update_fields.append("updated_at")
        client_profile.save(update_fields=update_fields)
    return client_profile


def _resolve_order_client_reference(
    *,
    client_id: str | None,
    client_name: str | None,
    client_phone: str | None,
    destination: str | None,
) -> tuple[ClientProfile | None, str, str]:
    if client_id:
        return ClientProfile.objects.get(id=client_id), "", ""

    raw_client_name = _clean_text(client_name)
    raw_client_phone = _clean_text(client_phone)
    if raw_client_name and raw_client_phone:
        profile = get_or_create_walk_in_profile(
            contact_name=raw_client_name,
            phone_number=raw_client_phone,
            destination=destination,
        )
        if profile is not None:
            return profile, raw_client_name, raw_client_phone
        logger.warning(
            "Walk-in profile could not be created or linked for order (phone may be reserved for a staff account). "
            "name=%s phone=%s",
            raw_client_name,
            raw_client_phone,
        )
        raise ValidationError(
            _(
                "This phone number cannot be used for a walk-in client because it is already assigned to "
                "another account type. Use a different number, or pick the client from search if they already exist."
            )
        )
    return None, raw_client_name, raw_client_phone


def _is_slaughter_order_no_unique_violation(exc: IntegrityError) -> bool:
    """Return True if the IntegrityError is due to slaughter_order_no unique constraint."""
    msg = str(exc).lower()
    return "slaughter_order_no" in msg or ("unique" in msg and "order" in msg)


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
        RuntimeError: If called outside an atomic transaction block
    """
    from django.db import connection

    if not connection.in_atomic_block:
        raise RuntimeError(
            "generate_order_number() must be called within a transaction.atomic() context. "
            "Use create_slaughter_order() service function for proper atomic order creation."
        )

    if order_datetime:
        # Handle both datetime (has .date()) and date (use as-is)
        order_date = order_datetime.date() if hasattr(order_datetime, "date") else order_datetime
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
    destination_client_id: str | None = None,
) -> SlaughterOrder:
    """
    Creates a new SlaughterOrder and all its associated animals.
    Handles both registered and walk-in clients.
    Generates order number atomically to prevent race conditions.

    Uses retry logic to handle the edge case where multiple threads try to create
    the first order of the day simultaneously (when select_for_update has no rows
    to lock).
    """
    client_profile, raw_client_name, raw_client_phone = _resolve_order_client_reference(
        client_id=client_id,
        client_name=client_name,
        client_phone=client_phone,
        destination=destination,
    )
    destination_client = _resolve_destination_client(destination_client_id)
    destination_display = _destination_display_name(destination_client, destination)

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
                    destination_client=destination_client,
                    service_package=service_package,
                    order_datetime=order_datetime,
                    client_name=raw_client_name,
                    client_phone=raw_client_phone,
                    destination=destination_display,
                    slaughter_order_no=order_number,
                )

                for animal_data in animals_data:
                    create_animal(order=order, **animal_data)

                _sync_preferred_destination_client(
                    client_profile=client_profile,
                    destination_client=destination_client,
                )
                order.refresh_from_db()
                return order

        except IntegrityError as e:
            # Only retry on slaughter_order_no unique constraint violation (first-order-of-day race).
            # Re-raise other IntegrityErrors (FK, null, other constraints) so they are not masked.
            if not _is_slaughter_order_no_unique_violation(e):
                raise
            last_exception = e
            continue

    # Exhausted retries; log full exception server-side, raise user-safe message
    logger.error(
        "Order creation failed after %d attempts (concurrency race on slaughter_order_no)",
        MAX_ORDER_CREATION_RETRIES,
        exc_info=(type(last_exception), last_exception, last_exception.__traceback__),
    )
    raise ValidationError(
        _("Failed to create order after multiple attempts due to high concurrency. Please try again.")
    )


@transaction.atomic
def assign_client_to_order(
    order: SlaughterOrder,
    *,
    client_id: str | None,
    client_name: str | None = None,
    client_phone: str | None = None,
    destination: str | None = None,
    destination_client_id: str | None = None,
) -> SlaughterOrder:
    if not can_reassign_order_client(order):
        raise ValidationError(_("Cannot change the client once animals have been added or processing has started."))

    client_profile, raw_client_name, raw_client_phone = _resolve_order_client_reference(
        client_id=client_id,
        client_name=client_name,
        client_phone=client_phone,
        destination=destination,
    )
    destination_client = _resolve_destination_client(destination_client_id)
    order.client = client_profile
    order.destination_client = destination_client
    order.client_name = raw_client_name
    order.client_phone = raw_client_phone
    order.destination = _destination_display_name(destination_client, destination)
    order.save(update_fields=["client", "destination_client", "client_name", "client_phone", "destination"])
    _sync_preferred_destination_client(
        client_profile=client_profile,
        destination_client=destination_client,
    )
    return order


@transaction.atomic
def update_order_datetime(order: SlaughterOrder, *, order_datetime: datetime) -> SlaughterOrder:
    if not can_edit_order_datetime(order):
        raise ValidationError(_("Cannot update the order date once animals have been added or processing has started."))

    order.order_datetime = order_datetime
    order.save(update_fields=["order_datetime"])
    return order


@transaction.atomic
def update_order_destination(
    order: SlaughterOrder,
    *,
    destination: str | None,
    destination_client_id: str | None = None,
) -> SlaughterOrder:
    """
    Updates destination fields while keeping the order owner/client unchanged.

    This is intentionally looser than full-order edits so reception staff can
    correct the destination after animals exist or processing has started,
    without rewriting ownership or service metadata.
    """
    if not can_edit_order_destination(order):
        raise ValidationError(_("Cannot update destination for an order that is already billed or cancelled."))

    destination_client = _resolve_destination_client(destination_client_id)
    order.destination_client = destination_client
    order.destination = _destination_display_name(destination_client, destination)
    order.save(update_fields=["destination_client", "destination"])
    return order


@transaction.atomic
def update_order_service_package(order: SlaughterOrder, *, service_package: ServicePackage) -> SlaughterOrder:
    """
    Guarded service-package updates.

    The service package may change while the order is still active, but only if
    the new package does not conflict with processing data that already exists.
    """
    if not can_edit_order_service_package(order):
        raise ValidationError(
            _(
                "Cannot update the service package for an order that is completed, billed, cancelled, or has terminal animals."
            )
        )

    if service_package is None:
        raise ValidationError(_("A service package is required."))

    if order.service_package_id == service_package.id:
        return order

    if _order_has_terminal_animals(order):
        raise ValidationError(
            _("Cannot change the service package after an animal has already been delivered, returned, or disposed.")
        )

    current_mode = _service_package_disassembly_mode(order.service_package)
    new_mode = _service_package_disassembly_mode(service_package)
    if current_mode != new_mode and _order_has_disassembly_outputs(order):
        raise ValidationError(
            _("Cannot change the disassembly service type after disassembly work or cut records already exist.")
        )

    order.service_package = service_package
    order.save(update_fields=["service_package"])
    return order


@transaction.atomic
def update_slaughter_order(order: SlaughterOrder, **data) -> SlaughterOrder:
    """
    Backward-compatible wrapper for older callers.
    """
    if "destination" in data or "destination_client_id" in data:
        update_order_destination(
            order=order,
            destination=data.get("destination"),
            destination_client_id=data.get("destination_client_id"),
        )
    if "service_package" in data and data.get("service_package") is not None:
        update_order_service_package(order=order, service_package=data["service_package"])
    if "order_datetime" in data and data.get("order_datetime") is not None:
        update_order_datetime(order=order, order_datetime=data["order_datetime"])
    order.refresh_from_db()
    return order


@transaction.atomic
def cancel_slaughter_order(order: SlaughterOrder) -> SlaughterOrder:
    """
    Cancels a slaughter order if it's still pending.
    Associated animals are also marked as disposed.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(_("Cannot cancel an order that is already in progress or completed."))

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
        raise ValidationError(_("Cannot bill an order that is not yet completed."))

    order.status = SlaughterOrder.Status.BILLED
    order.save()
    return order


@transaction.atomic
def add_animal_to_order(order: SlaughterOrder, animal_data: dict) -> Animal:
    """
    Adds a new animal to a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(_("Can only add animals to a PENDING order."))

    animal = create_animal(order=order, **animal_data)
    return animal


@transaction.atomic
def remove_animal_from_order(order: SlaughterOrder, animal: Animal):
    """
    Removes an animal from a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(_("Can only remove animals from a PENDING order."))

    if animal.slaughter_order != order:
        raise ValidationError(_("Animal does not belong to the specified order."))

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
        raise ValidationError(_("Can only add animals to a PENDING order."))

    if quantity > 100:
        raise ValidationError(_("Maximum 100 animals can be created in a single batch."))

    created_animals = []
    current_time = received_date or timezone.now()
    next_tag_number = _next_same_day_tag_number(tag_prefix, current_time) if tag_prefix else 1

    # Generate unique tags for the batch
    for i in range(quantity):
        if tag_prefix:
            # Continue same-day prefix numbering across batches; reset on the next day.
            identification_tag = f"{tag_prefix}-{next_tag_number + i:03d}"
        else:
            # Use auto-generated tags with batch identifier
            batch_id = uuid.uuid4().hex[:6].upper()
            identification_tag = f"{animal_type.upper()}-BATCH-{batch_id}-{i + 1:02d}"

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
