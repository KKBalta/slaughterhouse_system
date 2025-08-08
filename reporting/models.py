from django.db import models
from core.models import BaseModel
from users.models import User

class Report(BaseModel):
    REPORT_TYPE_CHOICES = (
        ('operational', 'Operational'),
        ('financial', 'Financial'),
        ('analytics', 'Analytics'),
    )

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="A descriptive name for the report (e.g., \"Daily Throughput Report\")."
    )
    description = models.TextField(
        blank=True,
        help_text="Explains the purpose and content of the report."
    )
    report_type = models.CharField(
        max_length=50,
        choices=REPORT_TYPE_CHOICES,
        help_text="Categorizes the report."
    )
    configuration = models.JSONField(
        blank=True, null=True,
        help_text="Stores parameters and settings specific to how this report is generated."
    )

    def __str__(self):
        return self.name

class GeneratedReport(BaseModel):
    STATUS_CHOICES = (
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending'),
    )

    report_definition = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name='generated_reports',
        help_text="The definition of the report that was generated."
    )
    generated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="The user who generated the report."
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp of when the report was generated."
    )
    start_date = models.DateField(
        null=True, blank=True,
        help_text="The start date of the data period covered by the report."
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text="The end date of the data period covered by the report."
    )
    file_path = models.CharField(
        max_length=255,
        blank=True, null=True,
        help_text="Path to the generated report file (e.g., PDF, CSV)."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Status of the report generation."
    )

    def __str__(self):
        return f"Generated Report: {self.report_definition.name} on {self.generated_at.strftime('%Y-%m-%d %H:%M')}"