import uuid  # Import uuid for UUIDField

from django.db import models

from core.models import BaseModel
from processing.models import Animal, DisassemblyCut
from users.models import User


class LabelTemplate(BaseModel):
    TARGET_ITEM_TYPE_CHOICES = (
        ("carcass", "Carcass"),
        ("meat_cut", "Meat Cut"),
        ("offal", "Offal"),
        ("by_product", "By-Product"),
        ("animal", "Animal"),  # New type for animal labels
    )

    name = models.CharField(
        max_length=100, unique=True, help_text='A descriptive name for the template (e.g., "Carcass Label").'
    )
    template_data = models.JSONField(
        help_text="Stores the layout and content variables for the label (e.g., position of text, barcodes, images)."
    )
    target_item_type = models.CharField(
        max_length=50,
        choices=TARGET_ITEM_TYPE_CHOICES,
        help_text="Specifies which type of inventory item this template is for.",
    )
    label_format = models.CharField(
        max_length=20,
        choices=[
            ("prn", "PRN/TSPL"),
            ("pdf", "PDF"),
            ("both", "Both PRN and PDF"),
        ],
        default="both",
        help_text="The format(s) this template supports.",
    )

    def __str__(self):
        return self.name


class PrintJob(BaseModel):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )
    ITEM_TYPE_CHOICES = (
        ("carcass", "Carcass"),
        ("meat_cut", "Meat Cut"),
        ("offal", "Offal"),
        ("by_product", "By-Product"),
        ("animal", "Animal"),  # New type for animal labels
    )

    label_template = models.ForeignKey(
        LabelTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="print_jobs",
        help_text="The template used for this print job.",
    )
    item_type = models.CharField(max_length=50, choices=ITEM_TYPE_CHOICES, help_text="The type of item being labeled.")
    item_id = models.UUIDField(help_text="The ID of the specific inventory item being labeled.")
    quantity = models.IntegerField(default=1, help_text="Number of labels printed for this job.")
    print_date = models.DateTimeField(auto_now_add=True, help_text="When the print job was initiated.")
    printed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, help_text="The user who initiated the print job."
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", help_text="Status of the print job."
    )

    def __str__(self):
        return f"Print Job for {self.item_type} ID: {self.item_id} - {self.status}"


class Label(BaseModel):
    ITEM_TYPE_CHOICES = (
        ("carcass", "Carcass"),
        ("meat_cut", "Meat Cut"),
        ("offal", "Offal"),
        ("by_product", "By-Product"),
        ("animal", "Animal"),  # New type for animal labels
    )

    label_code = models.CharField(
        max_length=100, unique=True, help_text="A unique code printed on the label (e.g., QR code, barcode)."
    )
    item_type = models.CharField(max_length=50, choices=ITEM_TYPE_CHOICES, help_text="Specifies what the label is for.")
    item_id = models.UUIDField(
        help_text="The ID of the associated inventory item (e.g., Carcass.id, MeatCut.id, Animal.id)."
    )
    print_date = models.DateTimeField(auto_now_add=True, help_text="When the label was printed.")
    printed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, help_text="The user who printed the label."
    )

    def __str__(self):
        return f"Label {self.label_code} for {self.item_type} ID: {self.item_id}"


class AnimalLabel(BaseModel):
    """
    Specific model for animal labels used in hot carcass identification.
    Can also be used for disassembly cut labels.
    """

    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="labels", help_text="The animal this label is for."
    )
    cut = models.ForeignKey(
        DisassemblyCut,
        on_delete=models.CASCADE,
        related_name="labels",
        null=True,
        blank=True,
        help_text="The disassembly cut this label is for (if label_type is 'cut').",
    )
    label_type = models.CharField(
        max_length=50,
        choices=[
            ("hot_carcass", "Hot Carcass"),
            ("cold_carcass", "Cold Carcass"),
            ("final", "Final Product"),
            ("cut", "Cut"),
        ],
        default="hot_carcass",
        help_text="Type of label for the animal.",
    )
    label_code = models.CharField(max_length=100, unique=True, help_text="Unique identifier for this label.")
    print_date = models.DateTimeField(auto_now_add=True, help_text="When the label was printed.")
    printed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, help_text="The user who printed the label."
    )
    prn_content = models.TextField(blank=True, help_text="TSPL/PRN code for this label.")
    bat_content = models.TextField(blank=True, help_text=".bat file content for easy printing.")
    pdf_file = models.FileField(
        upload_to="animal_labels/pdf/", blank=True, null=True, help_text="PDF file for this label."
    )

    class Meta:
        # Note: unique_together with nullable fields is handled via application logic
        # label_code is already unique=True, which ensures global uniqueness
        # For cut labels: one label per cut (enforced in save/validation)
        # For other labels: one label per animal per label_type (enforced in save/validation)
        ordering = ["-print_date"]

    def __str__(self):
        if self.cut:
            return (
                f"Cut Label {self.label_code} for {self.animal.identification_tag} - {self.cut.get_cut_name_display()}"
            )
        return f"Animal Label {self.label_code} for {self.animal.identification_tag}"

    def save(self, *args, **kwargs):
        if not self.label_code:
            # Generate unique label code
            if self.cut:
                cut_slug = self.cut.get_cut_name_display().replace(" ", "_").upper()
                self.label_code = f"CL-{self.animal.identification_tag}-{cut_slug}-{uuid.uuid4().hex[:8].upper()}"
            else:
                self.label_code = (
                    f"AL-{self.animal.identification_tag}-{self.label_type.upper()}-{uuid.uuid4().hex[:8].upper()}"
                )
        super().save(*args, **kwargs)


class CustomLabel(BaseModel):
    """
    Standalone custom labels for hot carcass identification.
    Allows manual entry of all label fields without linking to an Animal record.
    """

    ANIMAL_TYPE_CHOICES = [
        ("SIGIR", "Sığır"),
        ("KOYUN", "Koyun"),
        ("KECI", "Keçi"),
        ("KUZU", "Kuzu"),
        ("OGLAK", "Oğlak"),
        ("BUZA", "Buzağı"),
        ("DUVE", "Düve"),
        ("DANA", "Dana"),
    ]

    label_code = models.CharField(max_length=100, unique=True, help_text="Unique identifier for this label.")
    uretici = models.CharField(max_length=100, verbose_name="Üretici Ünvanı", help_text="Producer name")
    kupe_no = models.CharField(max_length=100, verbose_name="Küpe No", help_text="Ear tag / identification number")
    tuccar = models.CharField(max_length=100, blank=True, verbose_name="Tüccar Ünvanı", help_text="Trader name")
    kesim_tarihi = models.DateField(verbose_name="Kesim Tarihi", help_text="Slaughter date")
    stt = models.DateField(
        verbose_name="Son Tüketim Tarihi", help_text="Expiration date (usually slaughter date + 10 days)"
    )
    siparis_no = models.CharField(max_length=50, blank=True, verbose_name="Sipariş No", help_text="Order number")
    cinsi = models.CharField(max_length=20, choices=ANIMAL_TYPE_CHOICES, verbose_name="Cinsi", help_text="Animal type")
    weight = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="Ağırlık (kg)", help_text="Net weight in kg"
    )
    sakatat_status = models.CharField(
        max_length=10, default="0.51", verbose_name="Sakatat Durumu", help_text="Offal status value"
    )
    qr_data = models.CharField(max_length=500, blank=True, verbose_name="QR Verisi", help_text="Optional QR code data")
    prn_content = models.TextField(blank=True, help_text="TSPL/PRN code for this label.")
    bat_content = models.TextField(blank=True, help_text=".bat file content for easy printing.")
    pdf_file = models.FileField(
        upload_to="custom_labels/pdf/", blank=True, null=True, help_text="PDF file for this label."
    )
    print_date = models.DateTimeField(auto_now_add=True, help_text="When the label was created.")
    printed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, help_text="The user who created the label."
    )

    class Meta:
        ordering = ["-print_date"]
        verbose_name = "Custom Label"
        verbose_name_plural = "Custom Labels"

    def __str__(self):
        return f"Custom Label {self.label_code} - {self.kupe_no}"

    def save(self, *args, **kwargs):
        if not self.label_code:
            self.label_code = f"CUSTOM-{self.kupe_no}-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)
