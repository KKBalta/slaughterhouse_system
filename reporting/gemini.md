# Reporting App - Comprehensive Design & Implementation Plan

This document details the design and implementation plan for the `reporting` Django app, which is responsible for generating comprehensive reports and analytics for the slaughterhouse management system. The app will aggregate data from all other applications to provide insights into operations, yield, throughput, and financial summaries.

## 🎯 **IMPLEMENTATION STATUS: PLANNING PHASE**

**Current Status:** Basic models exist, comprehensive reporting system to be implemented
**Target:** Production-ready reporting system with PDF/Excel output capabilities

---

## 📊 **REPORT TYPES & STRUCTURE**

### **1. Daily Reports**
- **Daily Slaughter Summary**: Animals slaughtered, weights, leather weights by type
- **Daily Throughput Report**: Processing pipeline status, bottlenecks, efficiency metrics
- **Daily Weight Analysis**: Live vs. carcass weights, yield calculations, weight loss analysis
- **Daily Client Activity**: Orders received, completed, pending by client type

### **2. Monthly Reports**
- **Monthly Operations Summary**: Comprehensive monthly statistics
- **Monthly Yield Analysis**: Average yields by animal type, seasonal trends
- **Monthly Financial Summary**: Revenue, costs, profitability analysis
- **Monthly Client Performance**: Top clients, order volumes, payment status

### **3. Yearly Reports**
- **Annual Operations Report**: Year-over-year comparisons, growth metrics
- **Annual Yield Trends**: Long-term yield analysis, seasonal patterns
- **Annual Financial Report**: Complete financial analysis, profit/loss statements
- **Annual Client Analysis**: Client retention, growth, market analysis

---

## 🏗️ **CURRENT ARCHITECTURE OVERVIEW**

### **Existing Models (Basic Structure)**
```python
# Already implemented in models.py
class Report(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    configuration = models.JSONField(blank=True, null=True)

class GeneratedReport(BaseModel):
    report_definition = models.ForeignKey(Report, on_delete=models.CASCADE)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL)
    generated_at = models.DateTimeField(auto_now_add=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    file_path = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
```

### **Enhanced Architecture Plan**
```
┌─────────────────────────────────────────┐
│              UI Layer                   │
│  • Report Selection Interface          │
│  • Date Range Selection                │
│  • Filter Options (Animal Type, Client) │
│  • Download Progress Indicators        │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│             View Layer                  │
│  • Report Generation Views              │
│  • Async Report Processing              │
│  • File Download Handling               │
│  • Error Handling & User Feedback      │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│            Service Layer                │
│  • Data Aggregation Services           │
│  • Report Generation Services          │
│  • PDF/Excel Export Services           │
│  • Cache Management Services           │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│             Model Layer                 │
│  • Enhanced Report Models              │
│  • Report Template Models              │
│  • Generated Report Tracking           │
│  • Report Configuration Models         │
└─────────────────────────────────────────┘
```

---

## 📋 **DETAILED IMPLEMENTATION PLAN**

### **Phase 1: Enhanced Models & Data Structure**

#### **1.1 Enhanced Report Model**
```python
class Report(BaseModel):
    REPORT_TYPE_CHOICES = (
        ('daily_operational', 'Daily Operational'),
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
    
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    report_type = models.CharField(max_length=50, choices=REPORT_TYPE_CHOICES)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    output_format = models.CharField(max_length=10, choices=OUTPUT_FORMAT_CHOICES, default='both')
    configuration = models.JSONField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    requires_date_range = models.BooleanField(default=True)
    default_filters = models.JSONField(blank=True, null=True)  # Default animal types, clients, etc.
```

#### **1.2 Report Template Model**
```python
class ReportTemplate(BaseModel):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='templates')
    template_name = models.CharField(max_length=100)  # 'pdf_template', 'excel_template'
    template_content = models.TextField()  # HTML for PDF, JSON schema for Excel
    is_default = models.BooleanField(default=False)
    version = models.CharField(max_length=10, default='1.0')
```

#### **1.3 Report Filter Model**
```python
class ReportFilter(BaseModel):
    FILTER_TYPE_CHOICES = (
        ('animal_type', 'Animal Type'),
        ('client', 'Client'),
        ('status', 'Animal Status'),
        ('date_range', 'Date Range'),
        ('weight_range', 'Weight Range'),
    )
    
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='filters')
    filter_type = models.CharField(max_length=20, choices=FILTER_TYPE_CHOICES)
    filter_name = models.CharField(max_length=100)
    is_required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True)
    options = models.JSONField(blank=True, null=True)  # For dropdown options
```

### **Phase 2: Data Aggregation Services**

#### **2.1 Core Data Aggregation Service**
```python
class ReportDataAggregator:
    """Central service for aggregating data from all apps"""
    
    def __init__(self, start_date, end_date, filters=None):
        self.start_date = start_date
        self.end_date = end_date
        self.filters = filters or {}
        
    def get_daily_slaughter_data(self):
        """Get daily slaughter data matching Excel format"""
        from processing.models import Animal, WeightLog
        from reception.models import SlaughterOrder
        from inventory.models import Carcass, Offal, ByProduct
        
        # Get animals slaughtered on the specified date
        animals = Animal.objects.filter(
            slaughter_date__date=self.start_date,
            status__in=['slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']
        ).select_related('slaughter_order', 'slaughter_order__client')
        
        daily_data = []
        
        for animal in animals:
            # Get weight data
            live_weight = self._get_weight(animal, 'live_weight')
            hot_carcass_weight = self._get_weight(animal, 'hot_carcass_weight')
            leather_weight = animal.leather_weight_kg or 0
            
            # Get offal and bowels status from detail models
            offal_status, bowels_status = self._get_offal_bowels_status(animal)
            
            # Get destination (customer who received)
            destination = self._get_destination(animal)
            
            daily_data.append({
                'client_name': animal.slaughter_order.client_name or animal.slaughter_order.client.company_name,
                'quantity': 1,  # Individual animal
                'animal_type': self._get_turkish_animal_type(animal.animal_type),
                'weight': hot_carcass_weight or live_weight,
                'offal_status': offal_status,
                'bowels_status': bowels_status,
                'leather_weight': leather_weight,
                'destination': destination,
                'description': ''
            })
        
        return daily_data
    
    def get_daily_summary_totals(self):
        """Get summary totals by animal type"""
        daily_data = self.get_daily_slaughter_data()
        
        # Group by animal type
        summary = {
            'buyukbas': {'kesim': 0, 'deri': 0, 'bagirsak': 0},
            'kuzu': {'kesim': 0, 'deri': 0, 'bagirsak': 0},
            'oglak': {'kesim': 0, 'deri': 0, 'bagirsak': 0},
            'koyun': {'kesim': 0, 'deri': 0, 'bagirsak': 0},
            'keci': {'kesim': 0, 'deri': 0, 'bagirsak': 0}
        }
        
        for item in daily_data:
            animal_type = item['animal_type'].lower()
            leather_weight = item['leather_weight'] or 0
            
            if animal_type in ['dana', 'duve', 'inek']:  # Büyükbaş
                summary['buyukbas']['kesim'] += item['quantity']
                summary['buyukbas']['deri'] += leather_weight
                if item['bowels_status'] == 'SAĞLAM':
                    summary['buyukbas']['bagirsak'] += item['quantity']
            elif animal_type == 'kuzu':
                summary['kuzu']['kesim'] += item['quantity']
                summary['kuzu']['deri'] += leather_weight
                if item['bowels_status'] == 'SAĞLAM':
                    summary['kuzu']['bagirsak'] += item['quantity']
            elif animal_type == 'oglak':
                summary['oglak']['kesim'] += item['quantity']
                summary['oglak']['deri'] += leather_weight
                if item['bowels_status'] == 'SAĞLAM':
                    summary['oglak']['bagirsak'] += item['quantity']
            elif animal_type == 'koyun':
                summary['koyun']['kesim'] += item['quantity']
                summary['koyun']['deri'] += leather_weight
                if item['bowels_status'] == 'SAĞLAM':
                    summary['koyun']['bagirsak'] += item['quantity']
            elif animal_type == 'keci':
                summary['keci']['kesim'] += item['quantity']
                summary['keci']['deri'] += leather_weight
                # Keçi için bağırsak sayısı gerekli değil
        
        return summary
    
    def _get_weight(self, animal, weight_type):
        """Get specific weight for animal"""
        try:
            weight_log = animal.individual_weight_logs.filter(
                weight_type=weight_type
            ).first()
            return float(weight_log.weight) if weight_log else 0
        except:
            return 0
    
    def _get_offal_bowels_status(self, animal):
        """Get offal and bowels status from detail models"""
        offal_status = 'SAĞLAM'  # Default
        bowels_status = 'SAĞLAM'  # Default
        
        # Check detail models for status
        if hasattr(animal, 'cattledetails'):
            details = animal.cattledetails
            if details.liver_status == 0:
                offal_status = 'ATIK'
            elif details.liver_status == 0.5:
                offal_status = 'YARIM'
            
            if details.bowels_status == 0:
                bowels_status = 'BOZUK'
        elif hasattr(animal, 'sheepdetails'):
            # Similar logic for sheep details
            pass
        # Add other animal types as needed
        
        return offal_status, bowels_status
    
    def _get_destination(self, animal):
        """Get destination customer"""
        # This would need to be implemented based on your business logic
        # Could be from inventory disposition or order destination
        return animal.slaughter_order.destination or ''
    
    def _get_turkish_animal_type(self, animal_type):
        """Convert English animal type to Turkish"""
        type_mapping = {
            'cattle': 'DANA',
            'sheep': 'KOYUN', 
            'goat': 'KEÇİ',
            'lamb': 'KUZU',
            'oglak': 'OĞLAK',
            'calf': 'DANA',
            'heifer': 'DÜVE',
            'beef': 'İNEK'
        }
        return type_mapping.get(animal_type, animal_type.upper())
```

#### **2.2 Specialized Report Services**
```python
class DailyReportService:
    """Service for generating daily reports"""
    
    def generate_daily_slaughter_summary(self, date, filters=None):
        """Daily slaughter operations summary"""
        
    def generate_daily_throughput_report(self, date, filters=None):
        """Daily processing pipeline analysis"""
        
    def generate_daily_weight_analysis(self, date, filters=None):
        """Daily weight and yield analysis"""

class MonthlyReportService:
    """Service for generating monthly reports"""
    
    def generate_monthly_operations_summary(self, year, month, filters=None):
        """Comprehensive monthly operations report"""
        
    def generate_monthly_yield_analysis(self, year, month, filters=None):
        """Monthly yield trends and analysis"""

class YearlyReportService:
    """Service for generating yearly reports"""
    
    def generate_annual_operations_report(self, year, filters=None):
        """Annual operations and growth analysis"""
```

### **Phase 3: Output Generation Services**

#### **3.1 PDF Generation Service**
```python
class PDFReportGenerator:
    """Service for generating PDF reports using ReportLab"""
    
    def __init__(self, report_data, template_config):
        self.report_data = report_data
        self.template_config = template_config
        
    def generate_daily_report_pdf(self):
        """Generate PDF for daily reports"""
        # Structured PDF with:
        # - Header with company logo and report info
        # - Executive summary section
        # - Detailed statistics tables
        # - Charts and graphs (using matplotlib)
        # - Footer with generation timestamp
        
    def generate_monthly_report_pdf(self):
        """Generate PDF for monthly reports"""
        
    def generate_yearly_report_pdf(self):
        """Generate PDF for yearly reports"""
```

#### **3.2 Excel Generation Service**
```python
class ExcelReportGenerator:
    """Service for generating Excel reports using openpyxl"""
    
    def __init__(self, report_data, template_config):
        self.report_data = report_data
        self.template_config = template_config
        
    def generate_daily_report_excel(self):
        """Generate Excel workbook for daily reports"""
        # Structured Excel with multiple sheets:
        # - Summary sheet with key metrics
        # - Animal Statistics sheet
        # - Weight Analysis sheet
        # - Client Activity sheet
        # - Raw Data sheet for further analysis
        
    def generate_monthly_report_excel(self):
        """Generate Excel workbook for monthly reports"""
        
    def generate_yearly_report_excel(self):
        """Generate Excel workbook for yearly reports"""
```

### **Phase 4: Report Templates & Schemas**

#### **4.1 PDF Template Schema**
```html
<!-- Daily Report PDF Template -->
<div class="report-container">
    <header class="report-header">
        <div class="company-info">
            <h1>Slaughterhouse Management System</h1>
            <h2>{{ report_title }}</h2>
            <p>Generated on: {{ generation_date }}</p>
            <p>Period: {{ start_date }} to {{ end_date }}</p>
        </div>
    </header>
    
    <section class="executive-summary">
        <h3>Executive Summary</h3>
        <div class="summary-metrics">
            <div class="metric-card">
                <h4>Total Animals Processed</h4>
                <span class="metric-value">{{ total_animals }}</span>
            </div>
            <div class="metric-card">
                <h4>Total Weight (kg)</h4>
                <span class="metric-value">{{ total_weight }}</span>
            </div>
            <div class="metric-card">
                <h4>Average Yield %</h4>
                <span class="metric-value">{{ average_yield }}%</span>
            </div>
        </div>
    </section>
    
    <section class="detailed-statistics">
        <h3>Detailed Statistics</h3>
        <!-- Animal type breakdown table -->
        <!-- Weight analysis table -->
        <!-- Client activity table -->
    </section>
    
    <section class="charts-section">
        <h3>Visual Analysis</h3>
        <!-- Embedded charts and graphs -->
    </section>
</div>
```

#### **4.2 Excel Template Schema (Matching Your Example)**
```json
{
  "workbook_structure": {
    "sheets": [
      {
        "name": "Daily Slaughter Report",
        "content": {
          "title": "GÜNLÜK KESİM RAPORU",
          "date": "{{ report_date }}",
          "main_table": {
            "headers": [
              "FİRMA ÜNVANI",
              "ADET", 
              "CİNSİ",
              "AĞIRLIK",
              "SAKATAT",
              "BAĞIRSAK",
              "DERİ",
              "ALINAN MÜŞTERİ",
              "AÇIKLAMA"
            ],
            "data": "{{ daily_slaughter_data }}",
            "start_row": 3,
            "header_style": {
              "bold": true,
              "background_color": "#D3D3D3",
              "border": true
            }
          },
          "summary_table": {
            "title": "ÖZET",
            "start_row": "{{ main_table_end_row + 3 }}",
            "headers": ["", "KESİM", "DERİ", "BAĞIRSAK"],
            "data": [
              {
                "row_label": "BÜYÜKBAŞ",
                "kesim": "{{ summary.buyukbas.kesim }}",
                "deri": "{{ summary.buyukbas.deri }}",
                "bagirsak": "{{ summary.buyukbas.bagirsak }}"
              },
              {
                "row_label": "KUZU", 
                "kesim": "{{ summary.kuzu.kesim }}",
                "deri": "{{ summary.kuzu.deri }}",
                "bagirsak": "{{ summary.kuzu.bagirsak }}"
              },
              {
                "row_label": "OĞLAK",
                "kesim": "{{ summary.oglak.kesim }}",
                "deri": "{{ summary.oglak.deri }}",
                "bagirsak": "{{ summary.oglak.bagirsak }}"
              },
              {
                "row_label": "KOYUN",
                "kesim": "{{ summary.koyun.kesim }}",
                "deri": "{{ summary.koyun.deri }}",
                "bagirsak": "{{ summary.koyun.bagirsak }}"
              },
              {
                "row_label": "KEÇİ",
                "kesim": "{{ summary.keci.kesim }}",
                "deri": "{{ summary.keci.deri }}",
                "bagirsak": "",
                "note": "KEÇİ DE BAĞIRSAK ADEDİ LAZIM DEĞİL"
              }
            ],
            "style": {
              "bold": true,
              "background_color": "#F0F0F0",
              "border": true
            }
          }
        }
      }
    ]
  }
}
```

**Excel Generation Service (Updated):**
```python
class ExcelReportGenerator:
    """Service for generating Excel reports matching the exact format"""
    
    def generate_daily_slaughter_excel(self, report_data):
        """Generate Excel matching your example format"""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
        from openpyxl.utils import get_column_letter
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Daily Slaughter Report"
        
        # Title
        ws['A1'] = f"GÜNLÜK KESİM RAPORU - {report_data['date']}"
        ws['A1'].font = Font(bold=True, size=14)
        ws.merge_cells('A1:I1')
        
        # Main table headers
        headers = [
            "FİRMA ÜNVANI", "ADET", "CİNSİ", "AĞIRLIK", 
            "SAKATAT", "BAĞIRSAK", "DERİ", "ALINAN MÜŞTERİ", "AÇIKLAMA"
        ]
        
        # Style for headers
        header_font = Font(bold=True)
        header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Write headers
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=3, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')
        
        # Write data
        row = 4
        for item in report_data['daily_data']:
            ws.cell(row=row, column=1, value=item['client_name'])
            ws.cell(row=row, column=2, value=item['quantity'])
            ws.cell(row=row, column=3, value=item['animal_type'])
            ws.cell(row=row, column=4, value=item['weight'])
            ws.cell(row=row, column=5, value=item['offal_status'])
            ws.cell(row=row, column=6, value=item['bowels_status'])
            ws.cell(row=row, column=7, value=item['leather_weight'])
            ws.cell(row=row, column=8, value=item['destination'])
            ws.cell(row=row, column=9, value=item['description'])
            
            # Apply borders to data rows
            for col in range(1, 10):
                ws.cell(row=row, column=col).border = thin_border
            
            row += 1
        
        # Summary section
        summary_start_row = row + 2
        ws.cell(row=summary_start_row, column=1, value="ÖZET").font = Font(bold=True, size=12)
        
        # Summary headers
        summary_headers = ["", "KESİM", "DERİ", "BAĞIRSAK"]
        for col, header in enumerate(summary_headers, 1):
            cell = ws.cell(row=summary_start_row + 1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
        
        # Summary data
        summary_data = [
            ("BÜYÜKBAŞ", report_data['summary']['buyukbas']),
            ("KUZU", report_data['summary']['kuzu']),
            ("OĞLAK", report_data['summary']['oglak']),
            ("KOYUN", report_data['summary']['koyun']),
            ("KEÇİ", report_data['summary']['keci'])
        ]
        
        summary_row = summary_start_row + 2
        for label, data in summary_data:
            ws.cell(row=summary_row, column=1, value=label).font = Font(bold=True)
            ws.cell(row=summary_row, column=2, value=data['kesim'])
            ws.cell(row=summary_row, column=3, value=data['deri'])
            
            if label == "KEÇİ":
                ws.cell(row=summary_row, column=4, value="")
                # Add note for Keçi
                ws.cell(row=summary_row + 1, column=1, value="KEÇİ DE BAĞIRSAK ADEDİ LAZIM DEĞİL")
            else:
                ws.cell(row=summary_row, column=4, value=data['bagirsak'])
            
            # Apply borders and styling
            for col in range(1, 5):
                cell = ws.cell(row=summary_row, column=col)
                cell.border = thin_border
                if col == 1:
                    cell.font = Font(bold=True)
            
            summary_row += 1
        
        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 20)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        return wb
```

### **Phase 5: Views & User Interface**

#### **5.1 Report Generation Views**
```python
class ReportDashboardView(LoginRequiredMixin, TemplateView):
    """Main dashboard for report selection and generation"""
    template_name = 'reporting/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['daily_reports'] = Report.objects.filter(frequency='daily', is_active=True)
        context['monthly_reports'] = Report.objects.filter(frequency='monthly', is_active=True)
        context['yearly_reports'] = Report.objects.filter(frequency='yearly', is_active=True)
        return context

class GenerateReportView(LoginRequiredMixin, FormView):
    """View for generating reports with filters"""
    template_name = 'reporting/generate_report.html'
    form_class = ReportGenerationForm
    
    def form_valid(self, form):
        # Start async report generation
        # Return to progress page
        pass

class ReportProgressView(LoginRequiredMixin, TemplateView):
    """View showing report generation progress"""
    template_name = 'reporting/report_progress.html'

class DownloadReportView(LoginRequiredMixin, View):
    """View for downloading generated reports"""
    def get(self, request, report_id):
        # Serve the generated file
        pass
```

#### **5.2 Report Generation Form**
```python
class ReportGenerationForm(forms.Form):
    report = forms.ModelChoiceField(
        queryset=Report.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    animal_types = forms.MultipleChoiceField(
        choices=Animal.ANIMAL_TYPES,
        required=False,
        widget=forms.CheckboxSelectMultiple()
    )
    
    output_format = forms.ChoiceField(
        choices=Report.OUTPUT_FORMAT_CHOICES,
        initial='both'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date and start_date > end_date:
            raise ValidationError("Start date must be before end date.")
        
        return cleaned_data
```

### **Phase 6: Management Commands & Google Scheduler Integration**

#### **6.1 Django Management Commands for Automated Reports**
```python
# management/commands/generate_daily_reports.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from reporting.services import ReportDataAggregator, PDFReportGenerator, ExcelReportGenerator
from reporting.models import Report, GeneratedReport
from users.models import User

class Command(BaseCommand):
    help = 'Generate daily reports for the previous day'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Specific date to generate reports for (YYYY-MM-DD). Defaults to yesterday.',
        )
        parser.add_argument(
            '--report-types',
            nargs='+',
            default=['daily_slaughter', 'daily_throughput', 'daily_weights'],
            help='List of report types to generate',
        )
        parser.add_argument(
            '--output-format',
            choices=['pdf', 'excel', 'both'],
            default='both',
            help='Output format for reports',
        )
        parser.add_argument(
            '--system-user',
            type=str,
            default='system',
            help='Username for system-generated reports',
        )
    
    def handle(self, *args, **options):
        # Determine report date
        if options['date']:
            report_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            report_date = (timezone.now() - timedelta(days=1)).date()
        
        # Get system user
        try:
            system_user = User.objects.get(username=options['system_user'])
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'System user "{options["system_user"]}" not found')
            )
            return
        
        # Generate reports
        for report_type in options['report_types']:
            self.generate_report(report_type, report_date, options['output_format'], system_user)
    
    def generate_report(self, report_type, date, output_format, user):
        """Generate a specific report type for a given date"""
        try:
            # Get report definition
            report = Report.objects.get(
                report_type=report_type,
                frequency='daily',
                is_active=True
            )
            
            # Calculate date range (daily reports typically cover one day)
            start_date = date
            end_date = date
            
            # Aggregate data
            aggregator = ReportDataAggregator(start_date, end_date)
            report_data = aggregator.get_all_data()
            
            # Create generated report record
            generated_report = GeneratedReport.objects.create(
                report_definition=report,
                generated_by=user,
                start_date=start_date,
                end_date=end_date,
                status='pending'
            )
            
            # Generate files
            file_paths = []
            
            if output_format in ['pdf', 'both']:
                pdf_generator = PDFReportGenerator(report_data, report.configuration)
                pdf_path = pdf_generator.generate_daily_report_pdf()
                file_paths.append(pdf_path)
            
            if output_format in ['excel', 'both']:
                excel_generator = ExcelReportGenerator(report_data, report.configuration)
                excel_path = excel_generator.generate_daily_report_excel()
                file_paths.append(excel_path)
            
            # Update generated report
            generated_report.file_path = file_paths[0] if file_paths else None
            generated_report.status = 'success'
            generated_report.save()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully generated {report_type} report for {date}'
                )
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    f'Failed to generate {report_type} report for {date}: {str(e)}'
                )
            )

# management/commands/generate_monthly_reports.py
class Command(BaseCommand):
    help = 'Generate monthly reports for the previous month'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='Year to generate reports for. Defaults to previous month.',
        )
        parser.add_argument(
            '--month',
            type=int,
            help='Month to generate reports for. Defaults to previous month.',
        )
        parser.add_argument(
            '--report-types',
            nargs='+',
            default=['monthly_operations', 'monthly_yield', 'monthly_financial'],
            help='List of report types to generate',
        )
    
    def handle(self, *args, **options):
        # Determine report month
        now = timezone.now()
        if options['year'] and options['month']:
            report_year = options['year']
            report_month = options['month']
        else:
            # Previous month
            prev_month = now.replace(day=1) - timedelta(days=1)
            report_year = prev_month.year
            report_month = prev_month.month
        
        # Calculate date range
        start_date = datetime(report_year, report_month, 1).date()
        if report_month == 12:
            end_date = datetime(report_year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(report_year, report_month + 1, 1).date() - timedelta(days=1)
        
        # Get system user
        system_user = User.objects.get(username='system')
        
        # Generate reports
        for report_type in options['report_types']:
            self.generate_monthly_report(report_type, start_date, end_date, system_user)
    
    def generate_monthly_report(self, report_type, start_date, end_date, user):
        """Generate a specific monthly report"""
        # Similar implementation to daily reports but for monthly data
        pass

# management/commands/generate_yearly_reports.py
class Command(BaseCommand):
    help = 'Generate yearly reports for the previous year'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='Year to generate reports for. Defaults to previous year.',
        )
    
    def handle(self, *args, **options):
        # Determine report year
        if options['year']:
            report_year = options['year']
        else:
            report_year = timezone.now().year - 1
        
        # Calculate date range
        start_date = datetime(report_year, 1, 1).date()
        end_date = datetime(report_year, 12, 31).date()
        
        # Generate yearly reports
        pass
```

#### **6.2 Google Cloud Scheduler Integration**

**Google Cloud Scheduler Configuration:**
```yaml
# cloud-scheduler-config.yaml
jobs:
  - name: daily-slaughter-reports
    description: "Generate daily slaughter reports at 6 AM every day"
    schedule: "0 6 * * *"  # 6 AM daily
    time_zone: "Europe/Istanbul"
    http_target:
      uri: "https://your-domain.com/api/reports/generate-daily/"
      http_method: POST
      headers:
        Authorization: "Bearer YOUR_API_TOKEN"
      body: |
        {
          "report_types": ["daily_slaughter", "daily_throughput", "daily_weights"],
          "output_format": "both",
          "system_user": "system"
        }
  
  - name: monthly-operations-reports
    description: "Generate monthly operations reports on the 1st of each month"
    schedule: "0 8 1 * *"  # 8 AM on 1st of each month
    time_zone: "Europe/Istanbul"
    http_target:
      uri: "https://your-domain.com/api/reports/generate-monthly/"
      http_method: POST
      headers:
        Authorization: "Bearer YOUR_API_TOKEN"
      body: |
        {
          "report_types": ["monthly_operations", "monthly_yield", "monthly_financial"],
          "output_format": "both"
        }
  
  - name: yearly-operations-reports
    description: "Generate yearly operations reports on January 1st"
    schedule: "0 9 1 1 *"  # 9 AM on January 1st
    time_zone: "Europe/Istanbul"
    http_target:
      uri: "https://your-domain.com/api/reports/generate-yearly/"
      http_method: POST
      headers:
        Authorization: "Bearer YOUR_API_TOKEN"
      body: |
        {
          "report_types": ["yearly_operations", "yearly_yield", "yearly_financial"],
          "output_format": "both"
        }
```

**API Endpoints for Scheduler:**
```python
# views.py - API endpoints for Google Scheduler
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
import json
import subprocess
import threading

@csrf_exempt
@require_http_methods(["POST"])
def generate_daily_reports_api(request):
    """API endpoint for Google Scheduler to trigger daily report generation"""
    try:
        # Parse request body
        data = json.loads(request.body)
        report_types = data.get('report_types', ['daily_slaughter', 'daily_throughput', 'daily_weights'])
        output_format = data.get('output_format', 'both')
        system_user = data.get('system_user', 'system')
        
        # Run management command in background
        def run_command():
            try:
                call_command(
                    'generate_daily_reports',
                    report_types=report_types,
                    output_format=output_format,
                    system_user=system_user
                )
            except CommandError as e:
                # Log error for monitoring
                print(f"Daily report generation failed: {e}")
        
        # Start background thread
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Daily report generation started',
            'report_types': report_types
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def generate_monthly_reports_api(request):
    """API endpoint for Google Scheduler to trigger monthly report generation"""
    try:
        data = json.loads(request.body)
        report_types = data.get('report_types', ['monthly_operations', 'monthly_yield', 'monthly_financial'])
        
        def run_command():
            try:
                call_command(
                    'generate_monthly_reports',
                    report_types=report_types
                )
            except CommandError as e:
                print(f"Monthly report generation failed: {e}")
        
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Monthly report generation started',
            'report_types': report_types
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def generate_yearly_reports_api(request):
    """API endpoint for Google Scheduler to trigger yearly report generation"""
    try:
        data = json.loads(request.body)
        year = data.get('year')
        
        def run_command():
            try:
                call_command(
                    'generate_yearly_reports',
                    year=year
                )
            except CommandError as e:
                print(f"Yearly report generation failed: {e}")
        
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Yearly report generation started',
            'year': year
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
```

**URL Configuration:**
```python
# urls.py
from django.urls import path
from . import views

urlpatterns = [
    # ... existing URLs ...
    
    # API endpoints for Google Scheduler
    path('api/reports/generate-daily/', views.generate_daily_reports_api, name='api_generate_daily_reports'),
    path('api/reports/generate-monthly/', views.generate_monthly_reports_api, name='api_generate_monthly_reports'),
    path('api/reports/generate-yearly/', views.generate_yearly_reports_api, name='api_generate_yearly_reports'),
]
```

#### **6.3 Alternative: Direct Management Command Execution**

**For simpler setup without API endpoints:**
```bash
# Google Cloud Scheduler can directly call management commands via Cloud Run or Compute Engine

# Daily reports - 6 AM every day
gcloud scheduler jobs create http daily-slaughter-reports \
    --schedule="0 6 * * *" \
    --uri="https://your-cloud-run-url/run-command" \
    --http-method=POST \
    --headers="Authorization=Bearer YOUR_TOKEN" \
    --message-body='{"command": "generate_daily_reports", "args": ["--output-format", "both"]}'

# Monthly reports - 1st of each month at 8 AM
gcloud scheduler jobs create http monthly-operations-reports \
    --schedule="0 8 1 * *" \
    --uri="https://your-cloud-run-url/run-command" \
    --http-method=POST \
    --headers="Authorization=Bearer YOUR_TOKEN" \
    --message-body='{"command": "generate_monthly_reports", "args": ["--output-format", "both"]}'

# Yearly reports - January 1st at 9 AM
gcloud scheduler jobs create http yearly-operations-reports \
    --schedule="0 9 1 1 *" \
    --uri="https://your-cloud-run-url/run-command" \
    --http-method=POST \
    --headers="Authorization=Bearer YOUR_TOKEN" \
    --message-body='{"command": "generate_yearly_reports", "args": ["--output-format", "both"]}'
```

#### **6.4 Management Commands Directory Structure**
```
reporting/
├── management/
│   ├── __init__.py
│   └── commands/
│       ├── __init__.py
│       ├── generate_daily_reports.py      # Daily report generation
│       ├── generate_monthly_reports.py    # Monthly report generation
│       ├── generate_yearly_reports.py     # Yearly report generation
│       ├── setup_system_user.py           # System user setup
│       ├── cleanup_old_reports.py         # Cleanup old generated reports
│       └── test_report_generation.py      # Test report generation
```

#### **6.5 System User Setup**
```python
# management/commands/setup_system_user.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.models import User

class Command(BaseCommand):
    help = 'Create system user for automated report generation'
    
    def handle(self, *args, **options):
        User = get_user_model()
        
        # Create system user if it doesn't exist
        system_user, created = User.objects.get_or_create(
            username='system',
            defaults={
                'email': 'system@slaughterhouse.local',
                'first_name': 'System',
                'last_name': 'User',
                'role': 'ADMIN',
                'is_staff': True,
                'is_active': True,
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS('System user created successfully')
            )
        else:
            self.stdout.write(
                self.style.WARNING('System user already exists')
            )
```

#### **6.6 Report Cleanup Management Command**
```python
# management/commands/cleanup_old_reports.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from reporting.models import GeneratedReport
import os

class Command(BaseCommand):
    help = 'Clean up old generated reports and their files'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Number of days to keep reports (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
    
    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        # Calculate cutoff date
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Find old reports
        old_reports = GeneratedReport.objects.filter(
            generated_at__lt=cutoff_date,
            status='success'
        )
        
        count = old_reports.count()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'DRY RUN: Would delete {count} reports older than {days} days'
                )
            )
            for report in old_reports[:10]:  # Show first 10
                self.stdout.write(f'  - {report.report_definition.name} ({report.generated_at})')
            if count > 10:
                self.stdout.write(f'  ... and {count - 10} more')
        else:
            # Delete files first
            deleted_files = 0
            for report in old_reports:
                if report.file_path and os.path.exists(report.file_path):
                    try:
                        os.remove(report.file_path)
                        deleted_files += 1
                    except OSError as e:
                        self.stdout.write(
                            self.style.ERROR(f'Failed to delete file {report.file_path}: {e}')
                        )
            
            # Delete database records
            deleted_count, _ = old_reports.delete()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Deleted {deleted_count} reports and {deleted_files} files'
                )
            )
```

#### **6.7 Test Report Generation Command**
```python
# management/commands/test_report_generation.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from reporting.services import ReportDataAggregator
from reporting.models import Report

class Command(BaseCommand):
    help = 'Test report generation with sample data'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--report-type',
            type=str,
            default='daily_slaughter',
            help='Report type to test',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Specific date to test (YYYY-MM-DD)',
        )
    
    def handle(self, *args, **options):
        report_type = options['report_type']
        
        # Determine test date
        if options['date']:
            test_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
        else:
            test_date = (timezone.now() - timedelta(days=1)).date()
        
        self.stdout.write(f'Testing {report_type} report for {test_date}')
        
        try:
            # Test data aggregation
            aggregator = ReportDataAggregator(test_date, test_date)
            data = aggregator.get_all_data()
            
            self.stdout.write(
                self.style.SUCCESS('Data aggregation successful')
            )
            self.stdout.write(f'Total animals: {data.get("total_animals", 0)}')
            self.stdout.write(f'Total weight: {data.get("total_weight", 0)} kg')
            
            # Test report generation
            report = Report.objects.get(
                report_type=report_type,
                frequency='daily',
                is_active=True
            )
            
            self.stdout.write(
                self.style.SUCCESS(f'Report definition found: {report.name}')
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Test failed: {str(e)}')
            )
```

---

## 📊 **REPORT CONTENT SPECIFICATIONS**

### **Daily Slaughter Summary Report**
**Based on Excel Example Structure:**

**Main Table Columns:**
1. **FİRMA ÜNVANI (Client Name)** - Company/customer name
2. **ADET (Quantity)** - Number of animals
3. **CİNSİ (Piece Type)** - Animal type (KUZU, OĞLAK, KEÇİ, DANA, DÜVE, İNEK, KOYUN)
4. **AĞIRLIK (Weight)** - Total weight in KG
5. **SAKATAT (Offal)** - Condition: SAĞLAM (Healthy), YARIM (Half), ATIK (Waste)
6. **BAĞIRSAK (Bowels)** - Condition: SAĞLAM (Healthy), BOZUK (Damaged)
7. **DERİ (Leather)** - Leather weight in KG
8. **ALINAN MÜŞTERİ (Destination)** - Customer who received the products
9. **AÇIKLAMA (Description)** - Additional notes

**Summary Section (Bottom):**
- **BÜYÜKBAŞ (Cattle/Large Animals)**: KESİM, DERİ, BAĞIRSAK totals
- **KUZU (Lamb)**: KESİM, DERİ, BAĞIRSAK totals  
- **OĞLAK (Kid/Goat)**: KESİM, DERİ, BAĞIRSAK totals
- **KOYUN (Sheep)**: KESİM, DERİ, BAĞIRSAK totals
- **KEÇİ (Goat)**: KESİM, DERİ totals (BAĞIRSAK not needed)

**Output Structure:**
- **PDF**: Single page with main table and summary section
- **Excel**: Single sheet matching the exact Excel format shown

### **Monthly Operations Report**
**Data Points:**
- Monthly totals and averages
- Month-over-month comparisons
- Seasonal trends
- Top performing clients
- Processing bottlenecks
- Financial summaries (if available)

**Output Structure:**
- **PDF**: 5-7 pages with comprehensive analysis
- **Excel**: 8-10 sheets with detailed breakdowns

### **Yearly Operations Report**
**Data Points:**
- Annual totals and trends
- Year-over-year growth analysis
- Seasonal pattern analysis
- Long-term client performance
- Operational efficiency trends
- Strategic insights and recommendations

**Output Structure:**
- **PDF**: 10-15 pages with executive summary and detailed analysis
- **Excel**: 12-15 sheets with comprehensive data and pivot tables

---

## 🔧 **TECHNICAL IMPLEMENTATION DETAILS**

### **Dependencies Required**
```python
# requirements.txt additions
reportlab>=4.0.0          # PDF generation
openpyxl>=3.1.0           # Excel generation
matplotlib>=3.7.0         # Charts and graphs
celery>=5.3.0             # Async processing
redis>=4.6.0              # Celery broker
pillow>=10.0.0            # Image processing for PDFs
```

### **File Storage Strategy**
```
media/
├── reports/
│   ├── daily/
│   │   ├── 2024/
│   │   │   ├── 01/
│   │   │   │   ├── daily_slaughter_2024-01-15.pdf
│   │   │   │   └── daily_slaughter_2024-01-15.xlsx
│   │   │   └── 02/
│   ├── monthly/
│   │   ├── 2024/
│   │   │   ├── monthly_operations_2024-01.pdf
│   │   │   └── monthly_operations_2024-01.xlsx
│   └── yearly/
│       ├── yearly_operations_2024.pdf
│       └── yearly_operations_2024.xlsx
```

### **Database Optimization**
- Indexes on date fields for efficient querying
- Materialized views for complex aggregations
- Caching for frequently accessed report data
- Background cleanup of old generated reports

---

## 🎯 **IMPLEMENTATION PHASES**

### **Phase 1: Foundation (Week 1-2)**
- ✅ Enhanced models and database structure
- ✅ Basic data aggregation services
- ✅ Management commands for report generation
- ✅ System user setup

### **Phase 2: Core Reports (Week 3-4)**
- ✅ Daily report generation (PDF + Excel)
- ✅ Basic monthly report functionality
- ✅ Report templates and styling
- ✅ Google Scheduler integration

### **Phase 3: Advanced Features (Week 5-6)**
- ✅ Monthly and yearly report generation
- ✅ Advanced filtering and customization
- ✅ API endpoints for scheduler
- ✅ Background processing optimization

### **Phase 4: Polish & Optimization (Week 7-8)**
- ✅ Performance optimization
- ✅ Error handling and user feedback
- ✅ Documentation and testing
- ✅ Production deployment setup

---

## 🧪 **TESTING STRATEGY**

### **Unit Tests**
- Data aggregation accuracy
- Report generation logic
- File format validation
- Error handling scenarios

### **Integration Tests**
- End-to-end report generation
- File download functionality
- Async processing workflows
- Database query performance

### **User Acceptance Tests**
- Report accuracy validation
- User interface usability
- Performance under load
- Cross-browser compatibility

---

## 📈 **SUCCESS METRICS**

### **Functional Requirements**
- ✅ Generate daily, monthly, yearly reports
- ✅ PDF and Excel output formats
- ✅ Accurate data aggregation from all apps
- ✅ User-friendly interface for report generation
- ✅ Async processing for large reports

### **Performance Requirements**
- ✅ Report generation under 30 seconds for daily reports
- ✅ Report generation under 2 minutes for monthly reports
- ✅ Report generation under 5 minutes for yearly reports
- ✅ Support for concurrent report generation

### **Quality Requirements**
- ✅ 99%+ data accuracy in reports
- ✅ Professional PDF/Excel formatting
- ✅ Comprehensive error handling
- ✅ Mobile-responsive interface

---

## 🚀 **FUTURE ENHANCEMENTS**

### **Advanced Analytics**
- Machine learning for yield prediction
- Anomaly detection in processing data
- Predictive analytics for capacity planning

### **Real-time Dashboards**
- Live operational metrics
- Real-time alerts and notifications
- Interactive data visualization

### **API Integration**
- REST API for report generation
- Third-party system integration
- Mobile app support

### **Advanced Reporting**
- Custom report builder
- Scheduled report delivery
- Email report distribution
- Report sharing and collaboration

---

**🎉 CONCLUSION: This comprehensive plan provides a robust foundation for implementing a production-ready reporting system that will provide valuable insights into slaughterhouse operations, yield analysis, and business performance. The modular architecture ensures scalability and maintainability while delivering professional-quality reports in both PDF and Excel formats.**