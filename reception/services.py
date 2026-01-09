from django.db import transaction
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal # Add Animal import
from processing.services import create_animal
from datetime import date, datetime
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid


def generate_order_number(order_datetime=None) -> str:
    """
    Generates a unique order number for a given date.
    Uses database-level locking with select_for_update() to prevent race conditions.
    
    This function should be called within a transaction.atomic() context to ensure
    proper locking behavior.
    
    Args:
        order_datetime: The datetime for the order. If None, uses current time.
        
    Returns:
        A unique order number string in format: ORD-YYYYMMDD-NNNN
        
    Raises:
        ValidationError: If order number generation fails
    """
    if order_datetime:
        order_date = order_datetime.date()
        date_str = order_date.strftime('%Y%m%d')
    else:
        order_date = timezone.now().date()
        date_str = order_date.strftime('%Y%m%d')
    
    # Use select_for_update() to lock the last order for this date
    # This prevents race conditions in high-concurrency scenarios
    last_order = SlaughterOrder.objects.filter(
        slaughter_order_no__startswith=f"ORD-{date_str}"
    ).select_for_update().order_by('-slaughter_order_no').first()
    
    if last_order:
        # Extract the number from the last order
        try:
            last_num = int(last_order.slaughter_order_no.split('-')[-1])
            count = last_num + 1
        except (ValueError, IndexError):
            # Fallback if order number format is unexpected
            # Count existing orders for this date
            count = SlaughterOrder.objects.filter(
                order_datetime__date=order_date
            ).count() + 1
    else:
        count = 1
    
    order_number = f"ORD-{date_str}-{count:04d}"
    
    # Double-check uniqueness (defense in depth)
    if SlaughterOrder.objects.filter(slaughter_order_no=order_number).exists():
        # If somehow a duplicate exists, increment and try again
        count += 1
        order_number = f"ORD-{date_str}-{count:04d}"
    
    return order_number


@transaction.atomic
def create_slaughter_order(client_id: str, service_package_id: str, order_datetime: datetime, animals_data: list, client_name: str = None, client_phone: str = None, destination: str = None) -> SlaughterOrder:
    """
    Creates a new SlaughterOrder and all its associated animals.
    Handles both registered and walk-in clients.
    Generates order number atomically to prevent race conditions.
    """
    client_profile = None
    if client_id:
        client_profile = ClientProfile.objects.get(id=client_id)

    service_package = ServicePackage.objects.get(id=service_package_id)

    # Generate order number in service layer (not in model save())
    # This ensures atomic generation with proper database locking
    order_number = generate_order_number(order_datetime)

    order = SlaughterOrder.objects.create(
        client=client_profile,
        service_package=service_package,
        order_datetime=order_datetime,
        client_name=client_name if not client_profile else '',
        client_phone=client_phone if not client_profile else '',
        destination=destination,
        slaughter_order_no=order_number  # Set explicitly to avoid save() method generation
    )

    for animal_data in animals_data:
        create_animal(order=order, **animal_data)

    order.refresh_from_db()
    return order

@transaction.atomic
def update_slaughter_order(order: SlaughterOrder, **data) -> SlaughterOrder:
    """
    Updates a slaughter order with given data.
    Prevents updates if the order is no longer pending.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(f"Cannot update an order that is already in progress, completed, or cancelled.")

    allowed_fields = ['service_package', 'destination', 'order_datetime']
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
        raise ValidationError(f"Cannot cancel an order that is already in progress or completed.")

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
        return order # No animals, no status change

    if all(status in ['delivered', 'returned', 'disposed'] for status in animal_statuses):
        order.status = SlaughterOrder.Status.COMPLETED
    elif animal_statuses.intersection(['slaughtered', 'carcass_ready', 'disassembled', 'packaged']):
        order.status = SlaughterOrder.Status.IN_PROGRESS
    
    order.save()
    return order

@transaction.atomic
def bill_order(order: SlaughterOrder) -> SlaughterOrder:
    """
    Marks an order as billed if it is complete.
    """
    if order.status != SlaughterOrder.Status.COMPLETED:
        raise ValidationError(f"Cannot bill an order that is not yet completed.")
    
    order.status = SlaughterOrder.Status.BILLED
    order.save()
    return order

@transaction.atomic
def add_animal_to_order(order: SlaughterOrder, animal_data: dict) -> Animal:
    """
    Adds a new animal to a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(f"Can only add animals to a PENDING order.")
    
    animal = create_animal(order=order, **animal_data)
    return animal

@transaction.atomic
def remove_animal_from_order(order: SlaughterOrder, animal: Animal):
    """
    Removes an animal from a PENDING order.
    """
    if order.status != SlaughterOrder.Status.PENDING:
        raise ValidationError(f"Can only remove animals from a PENDING order.")
    
    if animal.slaughter_order != order:
        raise ValidationError(f"Animal does not belong to the specified order.")

    animal.delete()

@transaction.atomic
def create_batch_animals(order: SlaughterOrder, animal_type: str, quantity: int, tag_prefix: str = None, received_date: datetime = None, skip_photos: bool = False) -> list:
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
        raise ValidationError(f"Can only add animals to a PENDING order.")
    
    if quantity > 100:
        raise ValidationError(f"Maximum 100 animals can be created in a single batch.")
    
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
            'animal_type': animal_type,
            'identification_tag': identification_tag,
            'received_date': current_time,
        }
        
        # Create animal without photos if skip_photos is True
        # Photos can be added later via edit functionality
        animal = create_animal(order=order, **animal_data)
        created_animals.append(animal)
    
    return created_animals
