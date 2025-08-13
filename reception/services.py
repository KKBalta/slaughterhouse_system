
from django.db import transaction
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal # Add Animal import
from processing.services import create_animal
from datetime import date, datetime
from django.core.exceptions import ValidationError

@transaction.atomic
def create_slaughter_order(client_id: str, service_package_id: str, order_datetime: datetime, animals_data: list, client_name: str = None, client_phone: str = None, destination: str = None) -> SlaughterOrder:
    """
    Creates a new SlaughterOrder and all its associated animals.
    Handles both registered and walk-in clients.
    """
    client_profile = None
    if client_id:
        client_profile = ClientProfile.objects.get(id=client_id)

    service_package = ServicePackage.objects.get(id=service_package_id)

    order = SlaughterOrder.objects.create(
        client=client_profile,
        service_package=service_package,
        order_datetime=order_datetime,
        client_name=client_name if not client_profile else '',
        client_phone=client_phone if not client_profile else '',
        destination=destination
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
