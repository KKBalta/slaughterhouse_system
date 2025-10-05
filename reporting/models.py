from django.db import models
from core.models import BaseModel
from users.models import User

class Report(BaseModel):
    REPORT_TYPE_CHOICES = (
        ('daily_slaughter', 'Daily Slaughter'),
        ('daily_throughput', 'Daily Throughput'),
        ('daily_weights', 'Daily Weight Analysis'),
        ('daily_clients', 'Daily Client Activity'),
        ('monthly_operations', 'Monthly Operations'),
        ('monthly_yield', 'Monthly Yield Analysis'),
        ('monthly_financial', 'Monthly Financial'),
        ('monthly_clients', 'Monthly Client Performance'),
        ('yearly_operations', 'Annual Operations'),
        ('yearly_yield', 'Annual Yield Trends'),
        ('yearly_financial', 'Annual Financial'),
        ('yearly_clients', 'Annual Client Analysis'),
    )
    
    FREQUENCY_CHOICES = (
        ('daily', 'Daily'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('custom', 'Custom Date Range'),
    )
    
    OUTPUT_FORMAT_CHOICES = (
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('both', 'Both PDF and Excel'),
    )

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="A descriptive name for the report (e.g., \"Daily Slaughter Report\")."
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
    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default='daily',
        help_text="How often this report is generated."
    )
    output_format = models.CharField(
        max_length=10,
        choices=OUTPUT_FORMAT_CHOICES,
        default='both',
        help_text="Output format for the report."
    )
    configuration = models.JSONField(
        blank=True, null=True,
        help_text="Stores parameters and settings specific to how this report is generated."
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether the report is currently available for generation."
    )
    requires_date_range = models.BooleanField(
        default=True,
        help_text="Whether this report requires a date range to be specified."
    )
    default_filters = models.JSONField(
        blank=True, null=True,
        help_text="Default filters for the report (animal types, clients, etc.)."
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