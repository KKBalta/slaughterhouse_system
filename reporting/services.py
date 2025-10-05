from django.apps import apps
from django.db.models import Count, Sum, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal


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
        
        # Get animals that have reached carcass_ready state or beyond within the date range
        animals = Animal.objects.filter(
            slaughter_date__date__range=[self.start_date, self.end_date],
            status__in=['carcass_ready', 'disassembled', 'packaged', 'delivered']
        ).select_related('slaughter_order', 'slaughter_order__client')
        
        print(f"DEBUG: Found {animals.count()} animals with carcass_ready+ status in date range {self.start_date} to {self.end_date}")
        
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
            
            # Get client name
            client_name = self._get_client_name(animal)
            
            # Debug: Print animal details
            print(f"DEBUG: Animal {animal.identification_tag} - Status: {offal_status}, Bowels: {bowels_status}")
            
            daily_data.append({
                'client_name': client_name,
                'quantity': 1,  # Individual animal
                'animal_type': self._get_turkish_animal_type(animal.animal_type),
                'live_weight': live_weight,
                'hot_carcass_weight': hot_carcass_weight,
                'offal_status': offal_status,
                'bowels_status': bowels_status,
                'leather_weight': leather_weight,
                'sakatat_weight': 1.0 if offal_status == 'SAĞLAM' else 0.0,  # 1.0 if healthy offal, 0.0 if not
                'destination': destination,
                'description': ''
            })
        
        # Group identical records and sum quantities
        return self._aggregate_identical_records(daily_data)
    
    def get_daily_summary_totals(self):
        """Get summary totals by animal type"""
        daily_data = self.get_daily_slaughter_data()
        
        # Group by animal type
        summary = {
            'buyukbas': {'kesim': 0, 'deri': 0, 'bagirsak': 0, 'sakatat': 0},
            'kuzu': {'kesim': 0, 'deri': 0, 'bagirsak': 0, 'sakatat': 0},
            'oglak': {'kesim': 0, 'deri': 0, 'bagirsak': 0, 'sakatat': 0},
            'koyun': {'kesim': 0, 'deri': 0, 'bagirsak': 0, 'sakatat': 0},
            'keci': {'kesim': 0, 'deri': 0, 'bagirsak': 0, 'sakatat': 0}
        }
        
        for item in daily_data:
            animal_type = item['animal_type'].upper()  # Use uppercase Turkish type
            leather_weight = item['leather_weight'] or 0
            
            if animal_type in ['SIGIR', 'DUVE', 'DANA']:  # Büyükbaş
                summary['buyukbas']['kesim'] += item['quantity']
                summary['buyukbas']['deri'] += leather_weight * item['quantity']  # Multiply by quantity for total leather weight
                if item['bowels_status'] == 'SAĞLAM':
                    summary['buyukbas']['bagirsak'] += item['quantity']
                # Count animals with sakatat weight 1.0
                if item.get('sakatat_weight', 0) == 1.0:
                    summary['buyukbas']['sakatat'] += item['quantity']
            elif animal_type == 'KUZU':
                summary['kuzu']['kesim'] += item['quantity']
                summary['kuzu']['deri'] += item['quantity']  # For small animals, use quantity as leather count
                if item['bowels_status'] == 'SAĞLAM':
                    summary['kuzu']['bagirsak'] += item['quantity']
                # Count animals with sakatat weight 1.0
                if item.get('sakatat_weight', 0) == 1.0:
                    summary['kuzu']['sakatat'] += item['quantity']
            elif animal_type == 'OGLAK':
                summary['oglak']['kesim'] += item['quantity']
                summary['oglak']['deri'] += item['quantity']  # For small animals, use quantity as leather count
                if item['bowels_status'] == 'SAĞLAM':
                    summary['oglak']['bagirsak'] += item['quantity']
                # Count animals with sakatat weight 1.0
                if item.get('sakatat_weight', 0) == 1.0:
                    summary['oglak']['sakatat'] += item['quantity']
            elif animal_type == 'KOYUN':
                summary['koyun']['kesim'] += item['quantity']
                summary['koyun']['deri'] += item['quantity']  # For small animals, use quantity as leather count
                if item['bowels_status'] == 'SAĞLAM':
                    summary['koyun']['bagirsak'] += item['quantity']
                # Count animals with sakatat weight 1.0
                if item.get('sakatat_weight', 0) == 1.0:
                    summary['koyun']['sakatat'] += item['quantity']
            elif animal_type == 'KECI':
                summary['keci']['kesim'] += item['quantity']
                summary['keci']['deri'] += item['quantity']  # For small animals, use quantity as leather count
                # Count animals with sakatat weight 1.0
                if item.get('sakatat_weight', 0) == 1.0:
                    summary['keci']['sakatat'] += item['quantity']
                # Keçi için bağırsak sayısı gerekli değil
        
        return summary
    
    def get_all_data(self):
        """Get all data for report generation"""
        daily_data = self.get_daily_slaughter_data()
        return {
            'date': self.start_date.strftime('%Y-%m-%d'),
            'start_date': self.start_date.strftime('%Y-%m-%d'),
            'end_date': self.end_date.strftime('%Y-%m-%d'),
            'daily_data': daily_data,
            'summary': self.get_daily_summary_totals(),
            'total_animals': len(daily_data),
            'total_live_weight': sum(item['live_weight'] for item in daily_data),
            'total_hot_carcass_weight': sum(item['hot_carcass_weight'] for item in daily_data),
            'total_leather_weight': sum(item['leather_weight'] for item in daily_data)
        }
    
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
        
        # Check detail models for status based on animal type
        details = None
        if animal.animal_type == 'cattle' and hasattr(animal, 'cattle_details'):
            details = animal.cattle_details
        elif animal.animal_type == 'sheep' and hasattr(animal, 'sheep_details'):
            details = animal.sheep_details
        elif animal.animal_type == 'goat' and hasattr(animal, 'goat_details'):
            details = animal.goat_details
        elif animal.animal_type == 'lamb' and hasattr(animal, 'lamb_details'):
            details = animal.lamb_details
        elif animal.animal_type == 'oglak' and hasattr(animal, 'oglak_details'):
            details = animal.oglak_details
        elif animal.animal_type == 'calf' and hasattr(animal, 'calf_details'):
            details = animal.calf_details
        elif animal.animal_type == 'heifer' and hasattr(animal, 'heifer_details'):
            details = animal.heifer_details
        elif animal.animal_type == 'beef' and hasattr(animal, 'beef_details'):
            details = animal.beef_details
        
        if details:
            # Debug: Print detail model info
            print(f"DEBUG: Found {details.__class__.__name__} for {animal.identification_tag}")
            print(f"DEBUG: sakatat_status = {details.sakatat_status}, bowels_status = {details.bowels_status}")
            
            # Set offal status based on sakatat_status
            if details.sakatat_status == 0:
                offal_status = 'ATIK'
            elif details.sakatat_status == 0.5:
                offal_status = 'YARIM'
            else:  # 1.0
                offal_status = 'SAĞLAM'
            
            # Set bowels status based on bowels_status
            if details.bowels_status == 0:
                bowels_status = 'BOZUK'
            elif details.bowels_status == 0.5:
                bowels_status = 'YARIM'
            else:  # 1.0
                bowels_status = 'SAĞLAM'
        else:
            # No detail model found - use default values (SAĞLAM = good)
            print(f"DEBUG: No detail model found for {animal.identification_tag} (type: {animal.animal_type}) - using defaults")
            offal_status = 'SAĞLAM'  # Default to good
            bowels_status = 'SAĞLAM'  # Default to good
        
        return offal_status, bowels_status
    
    def _get_destination(self, animal):
        """Get destination customer"""
        # This would need to be implemented based on your business logic
        # Could be from inventory disposition or order destination
        return animal.slaughter_order.destination or ''
    
    def _get_client_name(self, animal):
        """Get client name from slaughter order"""
        if animal.slaughter_order.client:
            return animal.slaughter_order.client.company_name or animal.slaughter_order.client.contact_person
        else:
            return animal.slaughter_order.client_name or 'Walk-in Customer'
    
    def _get_turkish_animal_type(self, animal_type):
        """Convert English animal type to Turkish - matches labeling system mapping"""
        type_mapping = {
            'cattle': 'SIGIR',
            'sheep': 'KOYUN', 
            'goat': 'KECI',
            'lamb': 'KUZU',
            'oglak': 'OGLAK',
            'calf': 'BUZA',
            'heifer': 'DUVE',
            'beef': 'DANA'
        }
        return type_mapping.get(animal_type, animal_type.upper())
    
    def _aggregate_identical_records(self, daily_data):
        """
        Group identical records and sum their quantities.
        Records are considered identical only if ALL fields match:
        - client_name, animal_type, offal_status, bowels_status, 
        - leather_weight, destination, description
        
        If ANY field differs, a separate row is created.
        Examples:
        - Different animal type (KUZU vs DANA) → separate rows
        - Different weight (25 vs 30) → separate rows  
        - Different offal status (SAĞLAM vs ATIK) → separate rows
        - Different client → separate rows
        """
        # Create a dictionary to group records by their key fields
        grouped_records = {}
        
        for record in daily_data:
            # Create a key based on ALL fields except quantity and weights
            # This ensures separate rows for any difference
            key = (
                record['client_name'],
                record['animal_type'],
                record['live_weight'],
                record['hot_carcass_weight'],
                record['offal_status'],
                record['bowels_status'],
                record['leather_weight'],
                record['sakatat_weight'],
                record['destination'],
                record['description']
            )
            
            if key in grouped_records:
                # If record exists, add to quantity
                existing = grouped_records[key]
                existing['quantity'] += record['quantity']
                # Weights should be the same for identical records, so no averaging needed
            else:
                # Create new record - this happens when ANY field is different
                grouped_records[key] = record.copy()
        
        # Convert back to list
        return list(grouped_records.values())


class ExcelReportGenerator:
    """Service for generating Excel reports matching the exact format"""
    
    def __init__(self, report_data, template_config=None):
        self.report_data = report_data
        self.template_config = template_config or {}
    
    def generate_daily_slaughter_excel(self):
        """Generate Excel matching your example format"""
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
        from openpyxl.utils import get_column_letter
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Daily Slaughter Report"
        
        # Title
        ws['A1'] = f"GÜNLÜK KESİM RAPORU - {self.report_data['date']}"
        ws['A1'].font = Font(bold=True, size=14)
        ws.merge_cells('A1:J1')  # Updated to J1 for 10 columns
        
        # Main table headers
        headers = [
            "FİRMA ÜNVANI", "ADET", "CİNSİ", "CANLI AĞIRLIK", "SICAK KARKAS AĞIRLIK",
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
        for item in self.report_data['daily_data']:
            ws.cell(row=row, column=1, value=item['destination'])  # ALINAN MÜŞTERİ (first column)
            ws.cell(row=row, column=2, value=item['quantity'])
            ws.cell(row=row, column=3, value=item['animal_type'])
            ws.cell(row=row, column=4, value=item['live_weight'])
            ws.cell(row=row, column=5, value=item['hot_carcass_weight'])
            ws.cell(row=row, column=6, value=item['offal_status'])
            ws.cell(row=row, column=7, value=item['bowels_status'])
            ws.cell(row=row, column=8, value=item['leather_weight'])
            ws.cell(row=row, column=9, value=item['client_name'])  # FİRMA ÜNVANI (before last column)
            ws.cell(row=row, column=10, value=item['description'])
            
            # Apply borders to data rows
            for col in range(1, 11):  # Updated to 11 for 10 columns
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
            ("BÜYÜKBAŞ", self.report_data['summary']['buyukbas']),
            ("KUZU", self.report_data['summary']['kuzu']),
            ("OĞLAK", self.report_data['summary']['oglak']),
            ("KOYUN", self.report_data['summary']['koyun']),
            ("KEÇİ", self.report_data['summary']['keci'])
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


class PDFReportGenerator:
    """Service for generating PDF reports using ReportLab"""
    
    def __init__(self, report_data):
        self.report_data = report_data
        
    def _convert_turkish_chars(self, text):
        """Convert Turkish characters to ASCII equivalents"""
        if not text:
            return text
            
        turkish_to_ascii = {
            'Ğ': 'G', 'ğ': 'g',
            'Ü': 'U', 'ü': 'u', 
            'Ş': 'S', 'ş': 's',
            'İ': 'I', 'ı': 'i',
            'Ö': 'O', 'ö': 'o',
            'Ç': 'C', 'ç': 'c'
        }
        
        for turkish, ascii_char in turkish_to_ascii.items():
            text = text.replace(turkish, ascii_char)
        
        return text
        
    def generate_daily_slaughter_pdf(self):
        """Generate PDF for daily slaughter reports"""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        import tempfile
        import os
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_file.close()
        
        # Create PDF document
        doc = SimpleDocTemplate(temp_file.name, pagesize=A4)
        story = []
        
        # Get styles
        styles = getSampleStyleSheet()
        
        # Title style
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        # Header style
        header_style = ParagraphStyle(
            'CustomHeader',
            parent=styles['Heading2'],
            fontSize=12,
            spaceAfter=12,
            alignment=TA_LEFT,
            textColor=colors.darkblue
        )
        
        # Add title
        title = Paragraph("GUNLUK KESIM RAPORU", title_style)
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Add date range
        start_date = self.report_data.get('start_date', '')
        end_date = self.report_data.get('end_date', '')
        date_text = f"Tarih Araligi: {start_date} - {end_date}"
        date_para = Paragraph(date_text, styles['Normal'])
        story.append(date_para)
        story.append(Spacer(1, 20))
        
        # Main data table
        daily_data = self.report_data.get('daily_data', [])
        if daily_data:
            # Table headers
            headers = [
                "FIRMA UNVANI", "ADET", "CINSI", "CANLI AGIRLIK", "SICAK KARKAS AGIRLIK",
                "SAKATAT", "BAGIRSAK", "DERI", "ALINAN MUSTERI", "ACIKLAMA"
            ]
            
            # Prepare table data
            table_data = [headers]
            for item in daily_data:
                row = [
                    self._convert_turkish_chars(item.get('destination', '')),
                    str(item.get('quantity', 0)),
                    self._convert_turkish_chars(item.get('animal_type', '')),
                    str(item.get('live_weight', 0)),
                    str(item.get('hot_carcass_weight', 0)),
                    self._convert_turkish_chars(item.get('offal_status', '')),
                    self._convert_turkish_chars(item.get('bowels_status', '')),
                    str(item.get('leather_weight', 0)),
                    self._convert_turkish_chars(item.get('client_name', '')),
                    self._convert_turkish_chars(item.get('description', ''))
                ]
                table_data.append(row)
            
            # Create table
            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                # Header styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('LEFTPADDING', (0, 0), (-1, 0), 6),
                ('RIGHTPADDING', (0, 0), (-1, 0), 6),
                
                # Data styling
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('LEFTPADDING', (0, 1), (-1, -1), 4),
                ('RIGHTPADDING', (0, 1), (-1, -1), 4),
                
                # Alternating row colors
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.white]),
            ]))
            
            story.append(table)
            story.append(Spacer(1, 20))
        
        # Summary section
        summary = self.report_data.get('summary', {})
        if summary:
            summary_title = Paragraph("OZET", header_style)
            story.append(summary_title)
            
            # Summary table
            summary_headers = ["HAYVAN TURU", "KESIM", "DERI", "BAGIRSAK", "SAKATAT"]
            summary_data = [summary_headers]
            
            # Add summary rows
            for animal_type, data in summary.items():
                if animal_type in ['buyukbas', 'kuzu', 'oglak', 'koyun', 'keci']:
                    turkish_name = {
                        'buyukbas': 'BUYUKBAS',
                        'kuzu': 'KUZU', 
                        'oglak': 'OGLAK',
                        'koyun': 'KOYUN',
                        'keci': 'KECI'
                    }.get(animal_type, animal_type.upper())
                    
                    row = [
                        turkish_name,
                        str(data.get('kesim', 0)),
                        str(data.get('deri', 0)),
                        str(data.get('bagirsak', 0)),
                        str(data.get('sakatat', 0))
                    ]
                    summary_data.append(row)
            
            # Create summary table
            summary_table = Table(summary_data, repeatRows=1)
            summary_table.setStyle(TableStyle([
                # Header styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                
                # Data styling
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                
                # Alternating row colors
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.lightblue, colors.white]),
            ]))
            
            story.append(summary_table)
        
        # Build PDF
        doc.build(story)
        
        return temp_file.name