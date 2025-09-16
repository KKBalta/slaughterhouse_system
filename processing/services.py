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
    Transitions the animal's status to 'slaughtered' and updates the order status.
    """
    animal.perform_slaughter()
    animal.save()
    
    # Import locally to avoid circular imports
    from reception.services import update_order_status_from_animals
    # Update the slaughter order status based on animal statuses
    update_order_status_from_animals(animal.slaughter_order)
    
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
    Automatically transitions animal to 'carcass_ready' when hot carcass weight is logged.
    
    Weight type restrictions:
    - live_weight: Can be logged for animals in any status
    - hot_carcass_weight: Only for slaughtered animals
    - cold_carcass_weight: Only for carcass_ready animals
    - final_weight: Only for disassembled animals
    - leather_weight: Can be logged for animals in any status after received
    """
    # Validate weight type based on animal status
    weight_type_lower = weight_type.lower()
    
    if weight_type_lower in ['hot_carcass_weight', 'hot carcass weight', 'hot_carcass']:
        if animal.status not in ['slaughtered', 'carcass_ready']:
            raise ValidationError(
                f"Hot carcass weight can only be logged for slaughtered animals. "
                f"Animal {animal.identification_tag} is currently {animal.get_status_display()}."
            )
    elif weight_type_lower in ['cold_carcass_weight', 'cold carcass weight', 'cold_carcass']:
        if animal.status not in ['carcass_ready', 'disassembled', 'packaged', 'delivered']:
            raise ValidationError(
                f"Cold carcass weight can only be logged for animals with carcass ready or later status. "
                f"Animal {animal.identification_tag} is currently {animal.get_status_display()}."
            )
    elif weight_type_lower in ['final_weight', 'final weight']:
        if animal.status not in ['disassembled', 'packaged', 'delivered']:
            raise ValidationError(
                f"Final weight can only be logged for disassembled animals. "
                f"Animal {animal.identification_tag} is currently {animal.get_status_display()}."
            )
    elif weight_type_lower in ['leather_weight', 'leather weight']:
        if animal.status == 'received':
            raise ValidationError(
                f"Leather weight should be logged after slaughter. "
                f"Animal {animal.identification_tag} is currently {animal.get_status_display()}."
            )
    # live_weight can be logged for any status - no validation needed
    
    # Check if a weight log already exists for this weight type
    existing_log = WeightLog.objects.filter(
        animal=animal,
        weight_type=weight_type
    ).first()
    
    if existing_log:
        # Update existing log
        existing_log.weight = weight
        existing_log.save()
        weight_log = existing_log
    else:
        # Create new log
        weight_log = WeightLog.objects.create(
            animal=animal,
            weight=weight,
            weight_type=weight_type
        )
    
    # Auto-transition to carcass_ready when hot carcass weight is logged
    if weight_type_lower in ['hot_carcass_weight', 'hot carcass weight', 'hot_carcass'] and animal.status == 'slaughtered':
        animal.prepare_carcass()
        animal.save()
        
        # Update order status
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(animal.slaughter_order)
    
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
    
    This function supports real-time slaughterhouse workflow:
    1. Live weight: Weigh all animals at once when truck arrives
    2. Post-slaughter: Weigh animals in smaller batches (5-6 at a time)
    3. Auto-completion: When all animals are weighed, create individual weight logs
    
    Args:
        slaughter_order: The order containing the animals
        weight: Average weight per animal (calculated from total/quantity)
        weight_type: Type of weight being logged (e.g., 'Live Weight Group')
        group_quantity: Number of animals in the batch
        group_total_weight: Total combined weight of all animals in the batch
        
    Returns:
        WeightLog: The created weight log entry
    """
    # Basic validation: ensure this batch doesn't exceed total available animals
    # For different weight types, count appropriate animal statuses
    individual_weight_type = weight_type.replace(' Group', '')
    is_hot_carcass_weight = individual_weight_type.lower() in ['hot_carcass_weight', 'hot carcass weight', 'hot_carcass']
    is_live_weight = individual_weight_type.lower() in ['live_weight', 'live weight']
    is_cold_carcass_weight = individual_weight_type.lower() in ['cold_carcass_weight', 'cold carcass weight', 'cold_carcass']
    is_final_weight = individual_weight_type.lower() in ['final_weight', 'final weight']
    
    if is_live_weight:
        # For live weight, count all relevant statuses
        available_count = slaughter_order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
    elif is_hot_carcass_weight:
        # For hot carcass weight, count slaughtered/carcass_ready+ animals
        available_count = slaughter_order.animals.filter(status__in=['slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
    elif is_cold_carcass_weight:
        # For cold carcass weight, count carcass_ready+ animals
        available_count = slaughter_order.animals.filter(status__in=['carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
    elif is_final_weight:
        # For final weight, count disassembled+ animals
        available_count = slaughter_order.animals.filter(status__in=['disassembled', 'packaged', 'delivered']).count()
    else:
        # Default fallback for any other weight types
        available_count = slaughter_order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
    
    if group_quantity > available_count:
        raise ValueError(
            f"Cannot log weight for {group_quantity} animals. "
            f"Only {available_count} animals are available for weighing in this order."
        )
    
    # CUMULATIVE VALIDATION: Check existing batch logs for this weight type
    existing_logs = WeightLog.objects.filter(
        slaughter_order=slaughter_order,
        weight_type=weight_type,
        is_group_weight=True
    )
    
    # Calculate total animals already weighed for this weight type
    total_animals_already_weighed = sum(log.group_quantity for log in existing_logs)
    
    # Check if adding this batch would exceed available animals
    total_after_this_batch = total_animals_already_weighed + group_quantity
    
    if total_after_this_batch > available_count:
        remaining_available = available_count - total_animals_already_weighed
        raise ValueError(
            f"Cannot log weight for {group_quantity} animals. "
            f"Only {remaining_available} animals remain available for {weight_type} weighing "
            f"({total_animals_already_weighed} already weighed out of {available_count} total)."
        )
    
    # Create the batch weight log
    weight_log = WeightLog.objects.create(
        slaughter_order=slaughter_order,
        weight=weight,
        weight_type=weight_type,
        is_group_weight=True,
        group_quantity=group_quantity,
        group_total_weight=group_total_weight
    )
    
    # BATCH STATUS TRANSITION: Handle immediate status transitions for hot carcass weight
    # Check if this is hot carcass weight logging for immediate status transition  
    individual_weight_type = weight_type.replace(' Group', '')
    is_hot_carcass_weight = individual_weight_type.lower() in ['hot_carcass_weight', 'hot carcass weight', 'hot_carcass']
    
    if is_hot_carcass_weight:
        # Transition a batch of slaughtered animals to carcass_ready based on the group_quantity
        animals_to_transition = slaughter_order.animals.filter(status='slaughtered')[:group_quantity]
        animals_transitioned = 0
        
        for animal in animals_to_transition:
            animal.prepare_carcass()
            animal.save()
            animals_transitioned += 1
        
        # Update order status if any animals were transitioned
        if animals_transitioned > 0:
            from reception.services import update_order_status_from_animals
            update_order_status_from_animals(slaughter_order)
    
    # Check if we've now weighed all animals for this weight type
    # We can reuse the existing_logs and add the new log
    all_logs = list(existing_logs) + [weight_log]
    total_animals_weighed = sum(log.group_quantity for log in all_logs)
    
    # If all animals are now weighed, create individual weight logs automatically
    if total_animals_weighed >= available_count:
        _create_individual_weight_logs_from_batches(slaughter_order, weight_type, all_logs)
    
    return weight_log


def _create_individual_weight_logs_from_batches(slaughter_order: SlaughterOrder, weight_type: str, batch_logs):
    """
    Internal function to create individual weight logs when all animals are weighed.
    Calculates the overall average weight and assigns it to each animal.
    Automatically transitions animals to 'carcass_ready' when hot carcass weight is logged.
    """
    from decimal import Decimal
    
    # Calculate overall statistics
    total_weight = sum(Decimal(str(log.group_total_weight)) for log in batch_logs)
    total_animals = sum(log.group_quantity for log in batch_logs)
    overall_average_weight = total_weight / total_animals if total_animals > 0 else Decimal('0')
    
    # Get the base weight type (remove " Group" suffix)
    individual_weight_type = weight_type.replace(' Group', '')
    
    # Check if this is hot carcass weight logging for status transition
    is_hot_carcass_weight = individual_weight_type.lower() in ['hot_carcass_weight', 'hot carcass weight', 'hot_carcass']
    
    # Create individual weight logs for all animals that were part of the batch weights
    # Select animals based on weight type requirements
    if is_hot_carcass_weight:
        # For hot carcass weight, get animals that are either slaughtered or carcass_ready
        animals = slaughter_order.animals.filter(status__in=['slaughtered', 'carcass_ready'])
    else:
        # For other weight types, get animals based on the weight type requirements
        is_cold_carcass_weight = individual_weight_type.lower() in ['cold_carcass_weight', 'cold carcass weight', 'cold_carcass']
        is_final_weight = individual_weight_type.lower() in ['final_weight', 'final weight']
        is_live_weight = individual_weight_type.lower() in ['live_weight', 'live weight']
        
        if is_live_weight:
            # For live weight, include all relevant statuses
            animals = slaughter_order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered'])
        elif is_cold_carcass_weight:
            # For cold carcass weight, include carcass_ready+ animals
            animals = slaughter_order.animals.filter(status__in=['carcass_ready', 'disassembled', 'packaged', 'delivered'])
        elif is_final_weight:
            # For final weight, include disassembled+ animals
            animals = slaughter_order.animals.filter(status__in=['disassembled', 'packaged', 'delivered'])
        else:
            # Default fallback - include all relevant statuses
            animals = slaughter_order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered'])
    
    animals_transitioned = 0
    
    for animal in animals:
        # Check if individual weight log already exists
        existing_individual_log = WeightLog.objects.filter(
            animal=animal,
            weight_type=individual_weight_type
        ).first()
        
        if not existing_individual_log:
            WeightLog.objects.create(
                animal=animal,
                weight=overall_average_weight,
                weight_type=individual_weight_type,
                is_group_weight=False
            )
            
            # Auto-transition to carcass_ready when hot carcass weight is logged
            if is_hot_carcass_weight and animal.status == 'slaughtered':
                animal.prepare_carcass()
                animal.save()
                animals_transitioned += 1
    
    # Update order status if any animals were transitioned
    if animals_transitioned > 0:
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(slaughter_order)
    
    return {
        'total_weight': float(total_weight),
        'total_animals': total_animals,
        'average_weight': float(overall_average_weight),
        'individual_logs_created': animals.count(),
        'animals_transitioned_to_carcass_ready': animals_transitioned
    }

@transaction.atomic
def get_batch_weight_summary(slaughter_order: SlaughterOrder) -> dict:
    """
    Get a summary of all batch weights logged for a specific order.
    
    Args:
        slaughter_order: The order to get batch weight summary for
        
    Returns:
        dict: Summary containing weight logs and calculated statistics
    """
    batch_logs = WeightLog.objects.filter(
        slaughter_order=slaughter_order,
        is_group_weight=True
    ).order_by('log_date')
    
    summary = {
        'order': slaughter_order,
        'total_animals': slaughter_order.animals.exclude(status__in=['pending', 'received']).count(),
        'weight_logs': list(batch_logs),
        'weight_types_logged': list(batch_logs.values_list('weight_type', flat=True)),
        'total_logs_count': batch_logs.count(),
        'weight_progression': []
    }
    
    # Calculate weight progression if multiple weight types exist
    for log in batch_logs:
        summary['weight_progression'].append({
            'weight_type': log.weight_type,
            'total_weight': log.group_total_weight,
            'average_weight': log.weight,
            'animal_count': log.group_quantity,
            'log_date': log.log_date
        })
    
    return summary

def get_batch_weight_reports(date_from=None, date_to=None, order_id=None) -> dict:
    """
    Generate comprehensive batch weight reports with filtering options.
    
    Args:
        date_from: Start date for filtering (optional)
        date_to: End date for filtering (optional)
        order_id: Specific order ID to filter by (optional)
        
    Returns:
        dict: Comprehensive report data for batch weights
    """
    from django.db.models import Avg, Sum, Count
    from datetime import datetime, timedelta
    
    # Base queryset
    queryset = WeightLog.objects.filter(is_group_weight=True)
    
    # Apply filters
    if date_from:
        queryset = queryset.filter(log_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(log_date__lte=date_to)
    if order_id:
        queryset = queryset.filter(slaughter_order_id=order_id)
    
    # Get logs with related data
    logs = queryset.select_related('slaughter_order').order_by('-log_date')
    
    # Calculate statistics
    stats = queryset.aggregate(
        total_logs=Count('id'),
        total_animals_weighed=Sum('group_quantity'),
        total_weight_logged=Sum('group_total_weight'),
        average_weight_per_animal=Avg('weight'),
        average_animals_per_batch=Avg('group_quantity')
    )
    
    # Group by weight type
    weight_type_stats = {}
    for weight_type in queryset.values_list('weight_type', flat=True).distinct():
        type_logs = queryset.filter(weight_type=weight_type)
        weight_type_stats[weight_type] = {
            'count': type_logs.count(),
            'total_animals': type_logs.aggregate(Sum('group_quantity'))['group_quantity__sum'] or 0,
            'total_weight': type_logs.aggregate(Sum('group_total_weight'))['group_total_weight__sum'] or 0,
            'avg_weight_per_animal': type_logs.aggregate(Avg('weight'))['weight__avg'] or 0,
        }
    
    # Recent activity (last 7 days)
    seven_days_ago = datetime.now() - timedelta(days=7)
    recent_activity = queryset.filter(log_date__gte=seven_days_ago).count()
    
    return {
        'logs': logs,
        'stats': stats,
        'weight_type_stats': weight_type_stats,
        'recent_activity': recent_activity,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'order_id': order_id
        }
    }

@transaction.atomic
def package_animal_products(animal: Animal) -> Animal:
    """
    To mark an animal's products as packaged and updates order status.
    """
    animal.perform_packaging()
    animal.save()
    
    # Import locally to avoid circular imports
    from reception.services import update_order_status_from_animals
    # Update the slaughter order status based on animal statuses
    update_order_status_from_animals(animal.slaughter_order)
    
    return animal

@transaction.atomic
def deliver_animal_products(animal: Animal) -> Animal:
    """
    To mark an animal's products as delivered to the client and updates order status.
    """
    animal.deliver_product()
    animal.save()
    
    # Import locally to avoid circular imports
    from reception.services import update_order_status_from_animals
    # Update the slaughter order status based on animal statuses
    update_order_status_from_animals(animal.slaughter_order)
    
    return animal

@transaction.atomic
def return_animal_to_owner(animal: Animal) -> Animal:
    """
    To mark an animal or its products as returned to the owner and updates order status.
    """
    animal.return_to_owner()
    animal.save()
    
    # Import locally to avoid circular imports
    from reception.services import update_order_status_from_animals
    # Update the slaughter order status based on animal statuses
    update_order_status_from_animals(animal.slaughter_order)
    
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

@transaction.atomic
def prepare_animal_carcass(animal: Animal) -> Animal:
    """
    Transitions the animal's status from 'slaughtered' to 'carcass_ready' and updates order status.
    """
    animal.prepare_carcass()
    animal.save()
    
    # Import locally to avoid circular imports
    from reception.services import update_order_status_from_animals
    # Update the slaughter order status based on animal statuses
    update_order_status_from_animals(animal.slaughter_order)
    
    return animal

@transaction.atomic
def batch_transition_animals_to_carcass_ready(slaughter_order: SlaughterOrder, animal_count: int) -> dict:
    """
    Transitions a specified number of 'slaughtered' animals to 'carcass_ready' status in batch.
    
    Args:
        slaughter_order: The order containing the animals
        animal_count: Number of animals to transition
        
    Returns:
        dict: Summary of the batch transition operation
    """
    # Get animals in slaughtered status
    animals_to_transition = slaughter_order.animals.filter(status='slaughtered')[:animal_count]
    animals_transitioned = 0
    
    for animal in animals_to_transition:
        animal.prepare_carcass()
        animal.save()
        animals_transitioned += 1
    
    # Update order status
    if animals_transitioned > 0:
        from reception.services import update_order_status_from_animals
        update_order_status_from_animals(slaughter_order)
    
    return {
        'animals_transitioned': animals_transitioned,
        'order_id': str(slaughter_order.id),
        'order_status_updated': animals_transitioned > 0
    }

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
