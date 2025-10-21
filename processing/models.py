from django.db import models
from core.models import BaseModel
from reception.models import SlaughterOrder
from django_fsm import FSMField, transition
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
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

def scale_receipt_upload_path(instance, filename):
    """
    Generate upload path for scale receipt images using identification tag.
    """
    ext = filename.split('.')[-1] if '.' in filename else 'jpg'
    tag = instance.identification_tag if instance.identification_tag else f"{instance.animal_type.upper()}-{uuid.uuid4().hex[:10].upper()}"
    clean_tag = "".join(c for c in tag if c.isalnum() or c in ('-', '_')).rstrip()
    return f'scale_receipts/{clean_tag}_scale_receipt.{ext}'

class Animal(BaseModel):
    ANIMAL_TYPES = (
        ('cattle', _('Cattle')),
        ('sheep', _('Sheep')),
        ('goat', _('Goat')),
        ('lamb', _('Lamb')),
        ('oglak', _('Oglak')), # Child of Goat
        ('calf', _('Calf')), # Dana
        ('heifer', _('Heifer')), # Duve
        ('beef', _('Beef')), # Sigir
    )

    # FSM Statuses for Animal Workflow
    STATUS_CHOICES = (
        ('received', _('Received')),
        ('slaughtered', _('Slaughtered')),
        ('carcass_ready', _('Carcass Ready')),
        ('disassembled', _('Disassembled')),
        ('packaged', _('Packaged')),
        ('delivered', _('Delivered')),
        ('returned', _('Returned to Owner')),
        ('disposed', _('Disposed')),
    )

    slaughter_order = models.ForeignKey(
        SlaughterOrder,
        on_delete=models.CASCADE,
        related_name='animals',
        help_text=_("The slaughter order this animal belongs to.")
    )
    animal_type = models.CharField(
        max_length=50,
        choices=ANIMAL_TYPES,
        help_text=_("Type of animal (e.g., cattle, sheep, goat, lamb, oglak, calf, heifer, beef).")
    )
    identification_tag = models.CharField(
        max_length=100,
        unique=False, # Not unique at DB level to allow system-generated tags
        blank=True, null=True,
        help_text=_("Unique identification tag for the animal. System generates if not provided.")
    )
    received_date = models.DateTimeField(
        default=timezone.now, # Set default to now, but allow editing
        help_text=_("Date and time the animal was received.")
    )
    slaughter_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_("Date and time the animal was slaughtered.")
    )
    status = FSMField(
        default='received',
        choices=STATUS_CHOICES,
        protected=True,
        help_text=_("Current status of the animal in the processing workflow.")
    )
    picture = models.ImageField(
        upload_to=animal_picture_upload_path,
        blank=True, null=True,
        help_text=_("Picture of the animal.")
    )
    passport_picture = models.ImageField(
        upload_to=animal_passport_upload_path,
        blank=True, null=True,
        help_text=_("Picture of the animal's passport/documentation.")
    )
    scale_receipt_picture = models.ImageField(
        upload_to=scale_receipt_upload_path,
        blank=True, null=True,
        help_text=_("Picture of the scale receipt for the animal's weights.")
    )
    leather_weight_kg = models.DecimalField(
        max_digits=6, decimal_places=2,
        null=True, blank=True,
        help_text=_("The weight of the leather in kilograms.")
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
        else:
            # Validate and sanitize identification tag for batch file compatibility
            from labeling.utils import validate_animal_identification_for_batch
            validation_result = validate_animal_identification_for_batch(self.identification_tag)
            
            if not validation_result['is_valid']:
                # If validation fails, generate a new tag
                self.identification_tag = f"{self.animal_type.upper()}-{uuid.uuid4().hex[:10].upper()}"
            elif validation_result['warnings']:
                # If there are warnings (Turkish characters, etc.), sanitize the tag
                self.identification_tag = validation_result['sanitized_name']
                
        super().save(*args, **kwargs)

    def get_performance(self):
        """Return the performance ratio: live weight / hot carcass weight (if available)"""
        live_weight_log = self.individual_weight_logs.filter(weight_type='live_weight').order_by('-log_date').first()
        hot_carcass_log = self.individual_weight_logs.filter(weight_type='hot_carcass_weight').order_by('-log_date').first()
        if live_weight_log and hot_carcass_log and hot_carcass_log.weight:
            try:
                return round(float(hot_carcass_log.weight) / float(live_weight_log.weight)*100, 2)
            except (ZeroDivisionError, ValueError):
                return None
        return None

    def __str__(self):
        return f"{self.get_animal_type_display()} - {self.identification_tag}"

SCORE_CHOICES = (
    (0.0, _('Not Usable')),
    (0.5, _('Not Bad')),
    (1.0, _('Good')),
)

class CattleDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='cattle_details',
        limit_choices_to={'animal_type': 'cattle'},
        help_text=_("The associated cattle animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the cattle.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return _("Details for Cattle: %(tag)s") % {'tag': self.animal.identification_tag}

class SheepDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='sheep_details',
        limit_choices_to={'animal_type': 'sheep'},
        help_text=_("The associated sheep animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the sheep.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )
    # Removed leather_weight_kg from here

    def __str__(self):
        return _("Details for Sheep: %(tag)s") % {'tag': self.animal.identification_tag}

class GoatDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='goat_details',
        limit_choices_to={'animal_type': 'goat'},
        help_text=_("The associated goat animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the goat.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Goat: %(tag)s") % {'tag': self.animal.identification_tag}

class LambDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='lamb_details',
        limit_choices_to={'animal_type': 'lamb'},
        help_text=_("The associated lamb animal.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Lamb: %(tag)s") % {'tag': self.animal.identification_tag}

class OglakDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='oglak_details',
        limit_choices_to={'animal_type': 'oglak'},
        help_text=_("The associated oglak animal.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Oglak: %(tag)s") % {'tag': self.animal.identification_tag}

# New Animal Detail Models
class CalfDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='calf_details',
        limit_choices_to={'animal_type': 'calf'},
        help_text=_("The associated calf animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the calf.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Calf: %(tag)s") % {'tag': self.animal.identification_tag}

class HeiferDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='heifer_details',
        limit_choices_to={'animal_type': 'heifer'},
        help_text=_("The associated heifer animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the heifer.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Heifer: %(tag)s") % {'tag': self.animal.identification_tag}

class BeefDetails(BaseModel):
    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='beef_details',
        limit_choices_to={'animal_type': 'beef'},
        help_text=_("The associated beef animal.")
    )
    breed = models.CharField(
        max_length=100,
        blank=True,
        help_text=_("Breed of the beef.")
    )
    sakatat_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the sakatat (internal organs).")
    )
    bowels_status = models.DecimalField(
        max_digits=2, decimal_places=1,
        choices=SCORE_CHOICES, default=0.5,
        help_text=_("Score reflecting the usability of the bowels.")
    )

    def __str__(self):
        return _("Details for Beef: %(tag)s") % {'tag': self.animal.identification_tag}



class WeightLog(BaseModel):
    # Weight type choices for display
    WEIGHT_TYPE_CHOICES = [
        ('live_weight', _('Live Weight')),
        ('hot_carcass_weight', _('Hot Carcass Weight')),
        ('cold_carcass_weight', _('Cold Carcass Weight')),
        ('final_weight', _('Final Weight')),
        ('leather_weight', _('Leather Weight')),
        ('live_weight Group', _('Live Weight Group')),
        ('hot_carcass_weight Group', _('Hot Carcass Weight Group')),
        ('cold_carcass_weight Group', _('Cold Carcass Weight Group')),
        ('final_weight Group', _('Final Weight Group')),
    ]

    animal = models.ForeignKey(
        Animal,
        on_delete=models.CASCADE,
        related_name='individual_weight_logs',
        null=True, blank=True,
        help_text=_("The animal whose weight is being logged (for individual weights).")
    )
    slaughter_order = models.ForeignKey(
        SlaughterOrder,
        on_delete=models.CASCADE,
        related_name='group_weight_logs',
        null=True, blank=True,
        help_text=_("The slaughter order this group weight belongs to (for group weights).")
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=_("Weight recorded (e.g., live weight, hot carcass weight). For group weights, this is the average per animal.")
    )
    weight_type = models.CharField(
        max_length=100,
        choices=WEIGHT_TYPE_CHOICES,
        help_text=_("Type of weight (e.g., 'Live', 'Hot Carcass', 'Cold Carcass', 'Live Group').")
    )
    is_group_weight = models.BooleanField(
        default=False,
        help_text=_("True if this log entry represents a group weighing.")
    )
    group_quantity = models.IntegerField(
        null=True, blank=True,
        help_text=_("Number of animals in the group, if this is a group weight.")
    )
    group_total_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True, blank=True,
        help_text=_("Total weight of the group, if this is a group weight.")
    )
    log_date = models.DateTimeField(
        auto_now_add=True,
        help_text=_("Date and time the weight was logged.")
    )

    def __str__(self):
        if self.is_group_weight:
            return _("%(type)s - %(quantity)s animals (%(total_weight)skg total)") % {
                'type': self.get_weight_type_display(),
                'quantity': self.group_quantity,
                'total_weight': self.group_total_weight
            }
        else:
            return _("%(type)s - %(tag)s (%(weight)skg)") % {
                'type': self.get_weight_type_display(),
                'tag': self.animal.identification_tag,
                'weight': self.weight
            }

    def get_formatted_weight_type(self):
        """Return a clean, formatted version of the weight type for display"""
        weight_type = self.get_weight_type_display()
        # Remove 'Group' suffix for cleaner display in some contexts
        return weight_type.replace(' Group', '')

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