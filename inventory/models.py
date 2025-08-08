from django.db import models
from core.models import BaseModel
from processing.models import Animal
from users.models import User # Assuming User model is in users app

class Carcass(BaseModel):
    STATUS_CHOICES = (
        ('chilling', 'Chilling'),
        ('disassembly_ready', 'Disassembly Ready'),
        ('frozen', 'Frozen'),
        ('dispatched', 'Dispatched'),
    )
    DISPOSITION_CHOICES = (
        ('returned_to_owner', 'Returned to Owner'),
        ('for_sale', 'For Sale'),
        ('disposed', 'Disposed'),
    )

    animal = models.OneToOneField(
        Animal,
        on_delete=models.CASCADE,
        related_name='carcass',
        help_text="The animal this carcass belongs to."
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="The weight of the carcass (e.g., hot or cold carcass weight)."
    )
    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default='chilling',
        help_text="Current status of the carcass."
    )
    disposition = models.CharField(
        max_length=50,
        choices=DISPOSITION_CHOICES,
        help_text="How the carcass will be handled."
    )

    def __str__(self):
        return f"Carcass of {self.animal.identification_tag} - {self.weight} kg"

class MeatCut(BaseModel):
    DISPOSITION_CHOICES = (
        ('returned_to_owner', 'Returned to Owner'),
        ('for_sale', 'For Sale'),
        ('disposed', 'Disposed'),
    )

    carcass = models.ForeignKey(
        Carcass,
        on_delete=models.CASCADE,
        related_name='meat_cuts',
        help_text="The carcass from which this cut was derived."
    )
    cut_type = models.CharField(
        max_length=100,
        help_text="Describes the specific cut (e.g., 'Front Quarter', 'Hind Quarter')."
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="The weight of this specific cut."
    )
    disposition = models.CharField(
        max_length=50,
        choices=DISPOSITION_CHOICES,
        help_text="How the cut will be handled."
    )
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True, blank=True,
        help_text="Reference to a physical label printed for this cut."
    )

    def __str__(self):
        return f"{self.cut_type} from {self.carcass.animal.identification_tag} - {self.weight} kg"

class Offal(BaseModel):
    DISPOSITION_CHOICES = (
        ('returned_to_owner', 'Returned to Owner'),
        ('for_sale', 'For Sale'),
        ('disposed', 'Disposed'),
    )

    animal = models.ForeignKey(
        Animal,
        on_delete=models.CASCADE,
        related_name='offals',
        help_text="The animal this offal came from."
    )
    offal_type = models.CharField(
        max_length=100,
        help_text="Describes the type of offal (e.g., 'Liver', 'Kidneys')."
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="The weight of the offal."
    )
    disposition = models.CharField(
        max_length=50,
        choices=DISPOSITION_CHOICES,
        help_text="How the offal will be handled."
    )
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True, blank=True,
        help_text="Reference to a physical label printed for this offal."
    )

    def __str__(self):
        return f"{self.offal_type} from {self.animal.identification_tag} - {self.weight} kg"

class ByProduct(BaseModel):
    DISPOSITION_CHOICES = (
        ('returned_to_owner', 'Returned to Owner'),
        ('for_sale', 'For Sale'),
        ('disposed', 'Disposed'),
    )

    animal = models.ForeignKey(
        Animal,
        on_delete=models.CASCADE,
        related_name='by_products',
        help_text="The animal this by-product came from."
    )
    byproduct_type = models.CharField(
        max_length=100,
        help_text="Describes the type of by-product (e.g., 'Skin', 'Head')."
    )
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True, blank=True,
        help_text="The weight of the by-product."
    )
    disposition = models.CharField(
        max_length=50,
        choices=DISPOSITION_CHOICES,
        help_text="How the by-product will be handled."
    )
    label_id = models.CharField(
        max_length=100,
        unique=True,
        null=True, blank=True,
        help_text="Reference to a physical label printed for this by-product."
    )

    def __str__(self):
        return f"{self.byproduct_type} from {self.animal.identification_tag}"

class Label(BaseModel):
    ITEM_TYPE_CHOICES = (
        ('carcass', 'Carcass'),
        ('meat_cut', 'Meat Cut'),
        ('offal', 'Offal'),
        ('by_product', 'By-Product'),
    )

    label_code = models.CharField(
        max_length=100,
        unique=True,
        help_text="A unique code printed on the label (e.g., QR code, barcode)."
    )
    item_type = models.CharField(
        max_length=50,
        choices=ITEM_TYPE_CHOICES,
        help_text="Specifies what the label is for."
    )
    item_id = models.UUIDField(
        help_text="The ID of the associated inventory item (e.g., Carcass.id, MeatCut.id)."
    )
    print_date = models.DateTimeField(
        auto_now_add=True,
        help_text="When the label was printed."
    )
    printed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="The user who printed the label."
    )

    def __str__(self):
        return f"Label {self.label_code} for {self.item_type} ID: {self.item_id}"