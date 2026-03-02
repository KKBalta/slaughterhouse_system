from typing import Any

from django.db import models

from processing.models import Animal  # Keep for get_inventory_for_animal

from .models import ByProduct, Carcass, MeatCut, Offal, StorageLocation


def move_inventory_item(item: Any, new_storage_location: StorageLocation) -> Any:
    """
    Moves an inventory item (Carcass, MeatCut, etc.) to a new storage location.

    Args:
        item: The inventory item instance to move.
        new_storage_location: The new StorageLocation instance.

    Returns:
        The updated item instance.
    """
    if not hasattr(item, "storage_location"):
        raise TypeError(f"Object of type {type(item).__name__} does not have a storage_location.")

    item.storage_location = new_storage_location
    item.save(update_fields=["storage_location"])
    return item


def update_inventory_disposition(item: Any, new_disposition: str) -> Any:
    """
    Updates the disposition of an inventory item.

    Args:
        item: The inventory item instance.
        new_disposition: The new disposition string.

    Returns:
        The updated item instance.
    """
    if not hasattr(item, "disposition"):
        raise TypeError(f"Object of type {type(item).__name__} does not have a disposition.")

    item.disposition = new_disposition
    item.save(update_fields=["disposition"])
    return item


def assign_label_to_inventory_item(item: Any, label_id: str) -> Any:
    """
    Assigns a physical label ID to an inventory item.

    Args:
        item: The inventory item instance.
        label_id: The unique ID from the printed label.

    Returns:
        The updated item instance.
    """
    if not hasattr(item, "label_id"):
        raise TypeError(f"Object of type {type(item).__name__} does not have a label_id.")

    item.label_id = label_id
    item.save(update_fields=["label_id"])
    return item


def get_inventory_by_location(storage_location: StorageLocation) -> dict[str, models.QuerySet]:
    """
    Retrieves all inventory items currently in a specific storage location.

    Args:
        storage_location: The StorageLocation to query.

    Returns:
        A dictionary containing querysets for each type of item in that location.
    """
    return {
        "carcasses": Carcass.objects.filter(storage_location=storage_location),
        "meat_cuts": MeatCut.objects.filter(storage_location=storage_location),
        "offal": Offal.objects.filter(storage_location=storage_location),
        "byproducts": ByProduct.objects.filter(storage_location=storage_location),
    }


def get_inventory_for_animal(animal: Animal) -> dict[str, Any]:
    """
    Retrieves all inventory items derived from a single animal for full traceability.

    Args:
        animal: The source Animal instance.

    Returns:
        A dictionary containing the carcass and querysets for all related items.
    """
    carcass = Carcass.objects.filter(animal=animal).first()
    return {
        "carcass": carcass,
        "meat_cuts": MeatCut.objects.filter(carcass=carcass) if carcass else MeatCut.objects.none(),
        "offal": Offal.objects.filter(animal=animal),
        "byproducts": ByProduct.objects.filter(animal=animal),
    }
