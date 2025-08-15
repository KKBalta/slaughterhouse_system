from django.db import transaction
from .models import Animal, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails, WeightLog
from inventory.models import Carcass, MeatCut, Offal, ByProduct
from reception.models import SlaughterOrder # Added for log_group_weight
from django.core.exceptions import ValidationError # Added for update_animal_details
import os
from django.core.files.storage import default_storage
from django.conf import settings

# Define animal types that track offal/byproducts
OFFAL_BYPRODUCT_TRACKING_ANIMAL_TYPES = ['cattle', 'calf', 'heifer']

# A mapping from animal_type to its detail model class
ANIMAL_DETAIL_MODELS = {
    'cattle': CattleDetails,
    'sheep': SheepDetails,
    'goat': GoatDetails,
    'lamb': LambDetails,
    'oglak': OglakDetails,
    'calf': CalfDetails,
    'heifer': HeiferDetails,
}

@transaction.atomic
def create_animal(order, animal_type: str, details_data: dict = None, **animal_fields) -> Animal:
    """
    Creates a new Animal and, if applicable, its associated detail model.

    :param order: The SlaughterOrder to associate the animal with.
    :param animal_type: The type of the animal (e.g., 'cattle').
    :param details_data: A dictionary of data for the animal's detail model.
    :param animal_fields: Other fields for the Animal model itself (e.g., identification_tag).
    """
    animal = Animal.objects.create(
        slaughter_order=order,
        animal_type=animal_type,
        **animal_fields
    )

    if details_data:
        DetailModel = ANIMAL_DETAIL_MODELS.get(animal_type)
        if DetailModel:
            DetailModel.objects.create(animal=animal, **details_data)
        else:
            raise ValidationError(f"Details provided for animal type '{animal_type}', but no detail model found.")

    return animal

@transaction.atomic
def mark_animal_slaughtered(animal: Animal) -> Animal:
    """
    Transitions the animal's status to 'slaughtered'.
    """
    animal.perform_slaughter()
    animal.save()
    return animal

@transaction.atomic
def create_carcass_from_slaughter(animal: Animal, hot_carcass_weight: float, disposition: str) -> Carcass:
    """
    Creates a Carcass record in the inventory after an animal has been slaughtered.
    This service should be called after mark_animal_slaughtered.
    """
    carcass = Carcass.objects.create(
        animal=animal,
        hot_carcass_weight=hot_carcass_weight,
        disposition=disposition
    )
    return carcass

@transaction.atomic
def log_individual_weight(animal: Animal, weight_type: str, weight: float) -> WeightLog:
    """
    Logs an individual weight measurement for an animal.
    """
    weight_log = WeightLog.objects.create(
        animal=animal,
        weight=weight,
        weight_type=weight_type
    )
    return weight_log

@transaction.atomic
def disassemble_carcass(animal: Animal, meat_cuts_data: list, offal_data: list, by_products_data: list):
    """
    Handles the disassembly of a carcass, creating all resulting inventory items.
    Creates MeatCut records. For cattle, calf, and heifer types, it also creates
    Offal and ByProduct records based on provided data. Raises ValidationError
    if offal/byproduct data is provided for animal types that do not track them.
    """
    if animal.status != 'carcass_ready':
         raise ValidationError(f"Animal {animal.identification_tag} is not ready for disassembly.")

    animal.perform_disassembly()
    animal.save()

    carcass = animal.carcass
    carcass.mark_disassembly_ready()
    carcass.save()

    for cut_data in meat_cuts_data:
        MeatCut.objects.create(carcass=carcass, **cut_data)

    # Conditional creation of Offal and ByProduct
    if animal.animal_type in OFFAL_BYPRODUCT_TRACKING_ANIMAL_TYPES:
        for offal_item in offal_data:
            Offal.objects.create(animal=animal, **offal_item)

        for by_product_item in by_products_data:
            ByProduct.objects.create(animal=animal, **by_product_item)
    else:
        if offal_data or by_products_data:
            raise ValidationError(f"Offal/Byproduct tracking is not applicable for animal type: {animal.animal_type} during disassembly.")

    return {
        "meat_cuts_count": carcass.meat_cuts.count(),
        "offal_count": animal.offals.count(),
        "by_products_count": animal.by_products.count()
    }

@transaction.atomic
def update_animal_details(animal: Animal, details_data: dict) -> Animal:
    """
    Updates the specific details (e.g., breed, horn status) of an animal.
    """
    DetailModel = ANIMAL_DETAIL_MODELS.get(animal.animal_type)
    if not DetailModel:
        raise ValidationError(f"No detail model found for animal type: {animal.animal_type}")

    detail_instance = DetailModel.objects.get(animal=animal)
    for field, value in details_data.items():
        setattr(detail_instance, field, value)
    detail_instance.save()
    
    # Re-fetch the animal instance to ensure its related objects cache is updated
    # This avoids the django-fsm refresh_from_db issue
    updated_animal = Animal.objects.get(pk=animal.pk) 
    return updated_animal

@transaction.atomic
def log_group_weight(slaughter_order: SlaughterOrder, weight: float, weight_type: str, group_quantity: int, group_total_weight: float) -> WeightLog:
    """
    To record weight measurements for a batch of animals associated with a `SlaughterOrder`.
    """
    weight_log = WeightLog.objects.create(
        slaughter_order=slaughter_order,
        weight=weight,
        weight_type=weight_type,
        is_group_weight=True,
        group_quantity=group_quantity,
        group_total_weight=group_total_weight
    )
    return weight_log

@transaction.atomic
def package_animal_products(animal: Animal) -> Animal:
    """
    To mark an animal's products as packaged.
    """
    animal.perform_packaging()
    animal.save()
    return animal

@transaction.atomic
def deliver_animal_products(animal: Animal) -> Animal:
    """
    To mark an animal's products as delivered to the client.
    """
    animal.deliver_product()
    animal.save()
    return animal

@transaction.atomic
def return_animal_to_owner(animal: Animal) -> Animal:
    """
    To mark an animal or its products as returned to the owner.
    """
    animal.return_to_owner()
    animal.save()
    return animal

@transaction.atomic
def update_animal_metadata(animal: Animal, **metadata_to_update) -> Animal:
    """
    Updates general, non-workflow-related fields directly on the Animal model.
    """
    for field, value in metadata_to_update.items():
        setattr(animal, field, value)
    animal.save(update_fields=metadata_to_update.keys())
    return animal

@transaction.atomic
def record_cold_carcass_weight(carcass: Carcass, cold_carcass_weight: float) -> Carcass:
    """
    Records the weight of the carcass after chilling and marks it ready for disassembly.
    """
    carcass.cold_carcass_weight = cold_carcass_weight
    carcass.save(update_fields=['cold_carcass_weight'])
    carcass.mark_disassembly_ready()
    carcass.save()
    return carcass

@transaction.atomic
def record_initial_byproducts(animal: Animal, offal_data: list, by_products_data: list) -> dict:
    """
    Records the initial removal of offal and by-products that occur immediately after slaughter,
    before the main carcass disassembly.
    For cattle, calf, and heifer types, it creates Offal and ByProduct records.
    It does NOT change the Animal's status to 'disassembled' or the Carcass's status to 'disassembly_ready'.
    Raises ValidationError if offal/byproduct data is provided for animal types that do not track them.
    """
    if animal.animal_type in OFFAL_BYPRODUCT_TRACKING_ANIMAL_TYPES:
        offal_count = 0
        by_products_count = 0
        for offal_item in offal_data:
            Offal.objects.create(animal=animal, **offal_item)
            offal_count += 1

        for by_product_item in by_products_data:
            ByProduct.objects.create(animal=animal, **by_product_item)
            by_products_count += 1
    else:
        if offal_data or by_products_data:
            raise ValidationError(f"Offal/Byproduct tracking is not applicable for animal type: {animal.animal_type} for initial recording.")
        offal_count = 0
        by_products_count = 0

    return {
        "offal_count": offal_count,
        "by_products_count": by_products_count
    }

@transaction.atomic
def log_leather_weight(animal: Animal, leather_weight_kg: float) -> Animal:
    """
    Logs leather weight directly to the Animal model and creates a WeightLog entry.
    """
    # Update the animal's leather weight
    animal.leather_weight_kg = leather_weight_kg
    animal.save()
    
    # Also create a weight log entry for consistency
    weight_log = WeightLog.objects.create(
        animal=animal,
        weight=leather_weight_kg,
        weight_type='leather_weight'
    )
    
    return animal

def delete_animal_files(animal):
    """
    Delete all files associated with an animal when it's removed.
    """
    files_to_delete = []
    
    if animal.picture:
        files_to_delete.append(animal.picture.name)
    
    if animal.passport_picture:
        files_to_delete.append(animal.passport_picture.name)
    
    for file_path in files_to_delete:
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

def get_animal_file_urls(animal):
    """
    Get URLs for all animal files for display purposes.
    """
    urls = {}
    
    if animal.picture:
        urls['picture'] = animal.picture.url
    
    if animal.passport_picture:
        urls['passport_picture'] = animal.passport_picture.url
    
    return urls

def validate_animal_images(animal):
    """
    Validate that required images exist and are accessible.
    """
    issues = []
    
    if not animal.picture:
        issues.append("Animal photo is missing")
    elif not default_storage.exists(animal.picture.name):
        issues.append("Animal photo file not found on disk")
    
    if not animal.passport_picture:
        issues.append("Passport photo is missing")
    elif not default_storage.exists(animal.passport_picture.name):
        issues.append("Passport photo file not found on disk")
    
    return issues
