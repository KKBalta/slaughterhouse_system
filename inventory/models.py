from django.db import models
from django_fsm import FSMField, transition

from core.models import BaseModel
from processing.models import Animal


class StorageLocation(BaseModel):
    LOCATION_TYPE_CHOICES = (
        ("freezer", "Freezer"),
        ("cooler", "Cooler"),
        ("dry_storage", "Dry Storage"),
    )

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="A unique name for the storage location (e.g., 'Freezer 1', 'Cooler A, Shelf 3').",
    )
    location_type = models.CharField(
        max_length=50, choices=LOCATION_TYPE_CHOICES, help_text="Categorizes the type of storage."
    )
    capacity_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="The storage capacity in kilograms."
    )

    def __str__(self):
        return f"{self.name} ({self.get_location_type_display()})"


class Carcass(BaseModel):
    STATUS_CHOICES = (
        ("chilling", "Chilling"),
        ("disassembly_ready", "Disassembly Ready"),
        ("frozen", "Frozen"),
        ("dispatched", "Dispatched"),
    )
    DISPOSITION_CHOICES = (
        ("returned_to_owner", "Returned to Owner"),
        ("for_sale", "For Sale"),
        ("disposed", "Disposed"),
    )

    animal = models.OneToOneField(
        Animal, on_delete=models.CASCADE, related_name="carcass", help_text="The animal this carcass belongs to."
    )
    hot_carcass_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.0,  # Added default value
        help_text="The weight of the carcass immediately after slaughter.",
    )
    cold_carcass_weight = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="The weight of the carcass after chilling."
    )
    status = FSMField(
        default="chilling", choices=STATUS_CHOICES, protected=True, help_text="Current status of the carcass."
    )
    disposition = models.CharField(
        max_length=50, choices=DISPOSITION_CHOICES, help_text="How the carcass will be handled."
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="carcasses",
        help_text="The current physical storage location of the carcass.",
    )

    # FSM Transitions for Carcass
    @transition(field=status, source="chilling", target="disassembly_ready")
    def mark_disassembly_ready(self):
        """Transition from chilling to disassembly ready."""
        pass

    @transition(field=status, source=["chilling", "disassembly_ready"], target="frozen")
    def freeze_carcass(self):
        """Transition to frozen."""
        pass

    @transition(field=status, source=["disassembly_ready", "frozen"], target="dispatched")
    def dispatch_carcass(self):
        """Transition to dispatched."""
        pass

    def __str__(self):
        return f"Carcass of {self.animal.identification_tag} - {self.hot_carcass_weight} kg (Hot)"


class MeatCut(BaseModel):
    class BeefCuts(models.TextChoices):
        WHOLE_BONELESS = "WHOLE_BONELESS", "Whole Piece Boneless"
        NECK = "NECK", "Neck"
        CHUCK = "CHUCK", "Chuck"
        RIBEYE = "RIBEYE", "Ribeye"
        SHANK = "SHANK", "Shank"
        KNUCKLE = "KNUCKLE", "Knuckle"
        STRIPLOIN = "STRIPLOIN", "Striploin"
        TENDERLOIN = "TENDERLOIN", "Tenderloin"
        FLANK = "FLANK", "Flank"
        FILLET = "FILLET", "Fillet"
        BRISKET = "BRISKET", "Brisket"
        GROUND_BEEF = "GROUND_BEEF", "Ground Beef"
        STEW_MEAT = "STEW_MEAT", "Stew Meat"
        MEATBALL_MIX = "MEATBALL_MIX", "Meatball Mix"
        SAUSAGE = "SAUSAGE", "Sausage"
        BRAISED_MEAT = "BRAISED_MEAT", "Braised Meat"

    class LambGoatCuts(models.TextChoices):
        WHOLE_BONELESS = "WHOLE_BONELESS", "Whole Piece Boneless"
        NECK = "NECK", "Neck"
        SHOULDER = "SHOULDER", "Shoulder"
        LEG = "LEG", "Leg"
        RACK = "RACK", "Rack"
        FLANK = "FLANK", "Flank"
        CHOP = "CHOP", "Chop"
        GRILLED_CUTLET = "GRILLED_CUTLET", "Grilled Cutlet"
        EMPTY = "EMPTY", "Empty"  # For cases where nothing is cut

    DISPOSITION_CHOICES = (
        ("returned_to_owner", "Returned to Owner"),
        ("for_sale", "For Sale"),
        ("disposed", "Disposed"),
    )

    carcass = models.ForeignKey(
        Carcass,
        on_delete=models.CASCADE,
        related_name="meat_cuts",
        help_text="The carcass from which this cut was derived.",
    )
    cut_type = models.CharField(
        max_length=100,
        choices=BeefCuts.choices + LambGoatCuts.choices,  # Combine choices
        help_text="Describes the specific cut (e.g., 'Front Quarter', 'Hind Quarter').",
    )
    weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="The weight of this specific cut.")
    disposition = models.CharField(max_length=50, choices=DISPOSITION_CHOICES, help_text="How the cut will be handled.")
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Reference to a physical label printed for this cut.",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meat_cuts",
        help_text="The current physical storage location of the meat cut.",
    )

    def __str__(self):
        return f"{self.cut_type} from {self.carcass.animal.identification_tag} - {self.weight} kg"


class Offal(BaseModel):
    class BeefOffalTypes(models.TextChoices):
        LIVER = "LIVER", "Beef Liver"
        HEART = "HEART", "Heart"
        SPLEEN = "SPLEEN", "Spleen"
        HEAD_MEAT = "HEAD_MEAT", "Head Meat"
        CAUL_FAT = "CAUL_FAT", "Caul Fat"
        KIDNEY_FAT = "KIDNEY_FAT", "Kidney Fat"
        OMENTUM_FAT = "OMENTUM_FAT", "Omentum Fat"

    class LambGoatOffalTypes(models.TextChoices):
        LIVER_SET = "LIVER_SET", "Lamb Liver Set"
        HEAD = "HEAD", "Head"

    DISPOSITION_CHOICES = (
        ("returned_to_owner", "Returned to Owner"),
        ("for_sale", "For Sale"),
        ("disposed", "Disposed"),
    )

    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="offals", help_text="The animal this offal came from."
    )
    offal_type = models.CharField(
        max_length=100,
        choices=BeefOffalTypes.choices + LambGoatOffalTypes.choices,  # Combine choices
        help_text="Describes the type of offal (e.g., 'Liver', 'Kidneys').",
    )
    weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="The weight of the offal.")
    disposition = models.CharField(
        max_length=50, choices=DISPOSITION_CHOICES, help_text="How the offal will be handled."
    )
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Reference to a physical label printed for this offal.",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offals",
        help_text="The current physical storage location of the offal.",
    )

    def __str__(self):
        return f"{self.offal_type} from {self.animal.identification_tag} - {self.weight} kg"


class ByProduct(BaseModel):
    class ByProductTypes(models.TextChoices):
        SKIN = "SKIN", "Skin"
        HEAD = "HEAD", "Head"
        FEET = "FEET", "Feet"

    DISPOSITION_CHOICES = (
        ("returned_to_owner", "Returned to Owner"),
        ("for_sale", "For Sale"),
        ("disposed", "Disposed"),
    )

    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="by_products", help_text="The animal this by-product came from."
    )
    byproduct_type = models.CharField(
        max_length=100,
        choices=ByProductTypes.choices,
        help_text="Describes the type of by-product (e.g., 'Skin', 'Head').",
    )
    weight = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="The weight of the by-product."
    )
    disposition = models.CharField(
        max_length=50, choices=DISPOSITION_CHOICES, help_text="How the by-product will be handled."
    )
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Reference to a physical label printed for this by-product.",
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="by_products",
        help_text="The current physical storage location of the by-product.",
    )

    def __str__(self):
        return f"{self.byproduct_type} from {self.animal.identification_tag}"
