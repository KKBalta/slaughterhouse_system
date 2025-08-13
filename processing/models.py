from django.db import models
from core.models import BaseModel
from reception.models import SlaughterOrder
from django_fsm import FSMField, transition
from django.utils import timezone
import uuid # Import uuid for unique tag generation
import os

def animal_picture_upload_path(instance, filename):
    """
    Generate upload path for animal pictures using identification tag.
    """
    # Get file extension
    ext = filename.split('.')[-1] if '.' in filename else 'jpg'
    
    # Use identification_tag if available, otherwise generate one
    if instance.identification_tag:
        tag = instance.identification_tag
    else:
        # Generate a temporary tag based on animal type if not set yet
        tag = f"{instance.animal_type.upper()}-{uuid.uuid4().hex[:10].upper()}"
    
    # Clean the tag for filename (remove special characters)
    clean_tag = "".join(c for c in tag if c.isalnum() or c in ('-', '_')).rstrip()
    
    return f'animal_pictures/{clean_tag}_photo.{ext}'

def animal_passport_upload_path(instance, filename):
    """
    Generate upload path for animal passport pictures using identification tag.
    """
    # Get file extension
    ext = filename.split('.')[-1] if '.' in filename else 'jpg'
    
    # Use identification_tag if available, otherwise generate one
    if instance.identification_tag:
        tag = instance.identification_tag
    else:
        # Generate a temporary tag based on animal type if not set yet
        tag = f"{instance.animal_type.upper()}-{uuid.uuid4().hex[:10].upper()}"
    
    # Clean the tag for filename (remove special characters)
    clean_tag = "".join(c for c in tag if c.isalnum() or c in ('-', '_')).rstrip()
    
    return f'animal_passports/{clean_tag}_passport.{ext}'

class Animal(BaseModel):
    ANIMAL_TYPES = (
        ('cattle', 'Cattle'),
        ('sheep', 'Sheep'),
        ('goat', 'Goat'),
        ('lamb', 'Lamb'),
        ('oglak', 'Oglak'), # Child of Goat
        ('calf', 'Calf'), # Dana
        ('heifer', 'Heifer'), # Duve
        ('beef', 'Beef'), # Sigir
    )

    # FSM Statuses for Animal Workflow
    STATUS_CHOICES = (
        ('received', 'Received'),
        ('slaughtered', 'Slaughtered'),
        ('carcass_ready', 'Carcass Ready'),
        ('disassembled', 'Disassembled'),
        ('packaged', 'Packaged'),
        ('delivered', 'Delivered'),
        ('returned', 'Returned to Owner'),
        ('disposed', 'Disposed'),
    )

    slaughter_order = models.ForeignKey(
        SlaughterOrder,
        on_delete=models.CASCADE,
        related_name='animals',
        help_text="The slaughter order this animal belongs to."
    )
    animal_type = models.CharField(
        max_length=50,
        choices=ANIMAL_TYPES,
        help_text="Type of animal (e.g., cattle, sheep, goat, lamb, oglak, calf, heifer, beef)."
    )
    identification_tag = models.CharField(
        max_length=100,
        unique=False, # Not unique at DB level to allow system-generated tags
        blank=True, null=True,
        help_text="Unique identification tag for the animal. System generates if not provided."
    )
    received_date = models.DateTimeField(
        default=timezone.now, # Set default to now, but allow editing
        help_text="Date and time the animal was received."
    )
    slaughter_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date and time the animal was slaughtered."
    )
    status = FSMField(
        default='received',
        choices=STATUS_CHOICES,
        protected=True,
        help_text="Current status of the animal in the processing workflow."
    )
    picture = models.ImageField(
        upload_to=animal_picture_upload_path,
        blank=True, null=True,
        help_text="Picture of the animal."
    )
    passport_picture = models.ImageField(
        upload_to=animal_passport_upload_path,
        blank=True, null=True,
        help_text="Picture of the animal's passport/documentation."
    )
    leather_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=2,
        null=True, blank=True,
        help_text="The weight of the leather in kilograms."
    )

    # FSM Transitions
    @transition(field=status, source='received', target='slaughtered')
    def perform_slaughter(self):
        """Transition from received to slaughtered."""
        self.slaughter_date = timezone.now()

    @transition(field=status, source='slaughtered', target='carcass_ready')
    def prepare_carcass(self):
        """Transition from slaughtered to carcass ready."""
        pass

    @transition(field=status, source='carcass_ready', target='disassembled', 
                conditions=[lambda instance: instance.slaughter_order.service_package.includes_disassembly])
    def perform_disassembly(self):
        """Transition from carcass ready to disassembled, if disassembly is included in service package."""
        pass

    @transition(field=status, source=['carcass_ready', 'disassembled'], target='packaged')
    def perform_packaging(self):
        """Transition from carcass ready or disassembled to packaged."""
        pass

    @transition(field=status, source=['packaged', 'carcass_ready'], target='delivered',
                conditions=[lambda instance: instance.slaughter_order.service_package.includes_delivery])
    def deliver_product(self):
        """Transition to delivered, if delivery is included in service package."""
        pass

    @transition(field=status, source='*', target='returned')
    def return_to_owner(self):
        """Transition to returned to owner."""
        pass

    @transition(field=status, source='*', target='disposed')
    def dispose_animal(self):
        """Transition to disposed."""
        pass

    def save(self, *args, **kwargs):
        if not self.identification_tag:
            # Generate a unique tag based on animal type if not provided
            self.identification_tag = f"{self.animal_type.upper()}-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.animal_type.capitalize()} - {self.identification_tag}"

SCORE_CHOICES = (
    (0.0, 'Not Usable'),
    (0.5, 'Not Bad'),
    (1.0, 'Good'),
)

class CattleDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='cattle_details',
        limit_choices_to={'animal_type': 'cattle'},
        help_text="The associated cattle animal."
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Breed of the cattle."
    )
    horn_status = models.CharField(
        max_length=50,
        blank=True,
        help_text="Status of horns (e.g., horned, polled, dehorned)."
    )
    liver_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the liver."
    )
    head_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the head."
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the bowels."
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return f"Details for Cattle: {self.animal.identification_tag}"

class SheepDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='sheep_details',
        limit_choices_to={'animal_type': 'sheep'},
        help_text="The associated sheep animal."
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Breed of the sheep."
    )
    wool_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="Type of wool (e.g., fine, medium, coarse)."
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return f"Details for Sheep: {self.animal.identification_tag}"

class GoatDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='goat_details',
        limit_choices_to={'animal_type': 'goat'},
        help_text="The associated goat animal."
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Breed of the goat."
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return f"Details for Goat: {self.animal.identification_tag}"

class LambDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='lamb_details',
        limit_choices_to={'animal_type': 'lamb'},
        help_text="The associated lamb animal."
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return f"Details for Lamb: {self.animal.identification_tag}"

class OglakDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='oglak_details',
        limit_choices_to={'animal_type': 'oglak'},
        help_text="The associated oglak animal."
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return f"Details for Oglak: {self.animal.identification_tag}"

# New Animal Detail Models
class CalfDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='calf_details',
        limit_choices_to={'animal_type': 'calf'},
        help_text="The associated calf animal."
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Breed of the calf."
    )
    horn_status = models.CharField(
        max_length=50,
        blank=True,
        help_text="Status of horns (e.g., horned, polled, dehorned)."
    )
    liver_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the liver."
    )
    head_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the head."
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the bowels."
    )

    def __str__(self):
        return f"Details for Calf: {self.animal.identification_tag}"

class HeiferDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='heifer_details',
        limit_choices_to={'animal_type': 'heifer'},
        help_text="The associated heifer animal."
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text="Breed of the heifer."
    )
    horn_status = models.CharField(
        max_length=50,
        blank=True,
        help_text="Status of horns (e.g., horned, polled, dehorned)."
    )
    liver_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the liver."
    )
    head_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the head."
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text="Score reflecting the usability of the bowels."
    )

    def __str__(self):
        return f"Details for Heifer: {self.animal.identification_tag}"



class WeightLog(BaseModel):
    animal = models.ForeignKey(
        Animal,
        on_delete=models.CASCADE,
        related_name='individual_weight_logs',
        null=True, blank=True,
        help_text="The animal whose weight is being logged (for individual weights)."
    )
    slaughter_order = models.ForeignKey(
        SlaughterOrder,
        on_delete=models.CASCADE,
        related_name='group_weight_logs',
        null=True, blank=True,
        help_text="The slaughter order this group weight belongs to (for group weights)."
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Weight recorded (e.g., live weight, hot carcass weight). For group weights, this is the average per animal."
    )
    weight_type = models.CharField(
        max_length=100,
        help_text="Type of weight (e.g., 'Live', 'Hot Carcass', 'Cold Carcass', 'Live Group')."
    )
    is_group_weight = models.BooleanField(
        default=False,
        help_text="True if this log entry represents a group weighing."
    )
    group_quantity = models.IntegerField(
        null=True, blank=True,
        help_text="Number of animals in the group, if this is a group weight."
    )
    group_total_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True, blank=True,
        help_text="Total weight of the group, if this is a group weight."
    )
    log_date = models.DateTimeField(
        auto_now_add=True,
        help_text="Date and time the weight was logged."
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(animal__isnull=False) | models.Q(slaughter_order__isnull=False),
                name='animal_or_slaughter_order_required'
            ),
            models.CheckConstraint(
                check=models.Q(is_group_weight=False, group_quantity__isnull=True, group_total_weight__isnull=True) |
                      models.Q(is_group_weight=True, group_quantity__isnull=False, group_total_weight__isnull=False),
                name='group_weight_consistency'
            )
        ]
