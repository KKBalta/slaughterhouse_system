from django.apps import apps
from django.utils import timezone
from django.conf import settings
import os
import tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import black, white
import qrcode
from io import BytesIO
import base64

def generate_label_content(item_type: str, item_id: str, label_template) -> dict:
    """
    Generates label content based on item type, item ID, and a label template.
    Assumes label_template.template_data is a dictionary of field names to extract.
    """
    model_map = {
        'carcass': 'inventory.Carcass',
        'meat_cut': 'inventory.MeatCut',
        'offal': 'inventory.Offal',
        'by_product': 'inventory.ByProduct',
        'animal': 'processing.Animal',  # Add animal support
    }

    if item_type not in model_map:
        raise ValueError(f"Unsupported item_type: {item_type}")

    Model = apps.get_model(model_map[item_type])
    try:
        item = Model.objects.get(id=item_id)
    except Model.DoesNotExist:
        raise Model.DoesNotExist(f"{item_type.capitalize()} with ID {item_id} not found.")

    label_data = {}
    # Assuming template_data is a list of field names to extract
    if isinstance(label_template.template_data, list):
        for field_name in label_template.template_data:
            if hasattr(item, field_name):
                label_data[field_name] = str(getattr(item, field_name))
            else:
                label_data[field_name] = "N/A"
    else:
        # Fallback if template_data is not a list (e.g., a simple string or complex JSON)
        label_data['raw_template_data'] = label_template.template_data
        label_data['item_id'] = str(item.id)
        label_data['item_type'] = item_type
        # Add some default fields for basic labels
        if hasattr(item, 'identification_tag'): # For Carcass, Offal, ByProduct
            label_data['identification_tag'] = str(item.identification_tag)
        elif hasattr(item, 'carcass') and hasattr(item.carcass.animal, 'identification_tag'): # For MeatCut
            label_data['identification_tag'] = str(item.carcass.animal.identification_tag)
        
        # Handle weight retrieval based on item type
        if item_type == 'carcass':
            # For carcass, prioritize hot_carcass_weight, then cold_carcass_weight
            if hasattr(item, 'hot_carcass_weight') and item.hot_carcass_weight:
                label_data['weight'] = str(item.hot_carcass_weight)
            elif hasattr(item, 'cold_carcass_weight') and item.cold_carcass_weight:
                label_data['weight'] = str(item.cold_carcass_weight)
            else:
                label_data['weight'] = "N/A"
        elif hasattr(item, 'weight'):
            # For other items (MeatCut, Offal, ByProduct), use the weight field
            label_data['weight'] = str(item.weight)
        else:
            label_data['weight'] = "N/A"

    return label_data

def generate_animal_label_data(animal) -> dict:
    """
    Generate label data for an animal based on the Turkish hot carcass label format.
    """
    # Get client information
    order = animal.slaughter_order
    if order.client:
        uretici = order.client.company_name or order.client.get_full_name()
    else:
        uretici = order.client_name or "Bilinmeyen"
    
    # Get slaughter date
    kesim_tarihi = animal.slaughter_date.strftime("%d.%m.%Y") if animal.slaughter_date else "Bilinmiyor"
    
    # Calculate STT (Son Tuketim Tarihi) - slaughter date + 10 days
    if animal.slaughter_date:
        from datetime import timedelta
        stt_date = animal.slaughter_date + timedelta(days=10)
        stt = stt_date.strftime("%d.%m.%Y")
    else:
        stt = "Bilinmiyor"
    
    # Get order number
    siparis_no = order.slaughter_order_no or "Bilinmiyor"
    
    # Get animal type with Turkish character replacement (for printer compatibility)
    animal_type_mapping = {
        'cattle': 'DANA',
        'sheep': 'KOYUN',
        'goat': 'KECI',
        'lamb': 'KUZU',
        'oglak': 'OGLAK',
        'calf': 'DANA',
        'heifer': 'DUVE',
        'beef': 'SIGIR',
    }
    cinsi = animal_type_mapping.get(animal.animal_type, animal.animal_type.upper())
    
    # Get kupe number (identification tag)
    kupe_no = animal.identification_tag or "Bilinmiyor"
    
    # Get trader (destination address from slaughter order)
    tuccar = order.destination or ""
    
    # Get hot carcass weight from WeightLog (where weights are actually stored)
    weight = "Err"  # Default weight
    try:
        # Get the most recent hot carcass weight log for this animal
        hot_carcass_log = animal.individual_weight_logs.filter(
            weight_type='hot_carcass_weight'
        ).order_by('-log_date').first()
        
        if hot_carcass_log and hot_carcass_log.weight:
            weight = str(int(hot_carcass_log.weight))
    except Exception:
        weight = "Err"
    
    # Get organ status values from animal details
    bowels_status_value = "0.5"  # Default bowels status
    sakatat_status_value = "0.5"  # Default sakatat status
    
    # Check if animal has detail model with organ status scores
    try:
        # Get the animal details based on animal type
        if hasattr(animal, f'{animal.animal_type}_details'):
            details = getattr(animal, f'{animal.animal_type}_details')
            
            # Get bowels status value (for karkas_status in label)
            if hasattr(details, 'bowels_status') and details.bowels_status is not None:
                # Format the value: if it's a whole number, show without decimal
                bowels_value = float(details.bowels_status)
                if bowels_value == int(bowels_value):
                    bowels_status_value = str(int(bowels_value))
                else:
                    bowels_status_value = str(bowels_value)
            
            # Get sakatat (offal/liver) status value
            if hasattr(details, 'sakatat_status') and details.sakatat_status is not None:
                # Format the value: if it's a whole number, show without decimal
                sakatat_value = float(details.sakatat_status)
                if sakatat_value == int(sakatat_value):
                    sakatat_status_value = str(int(sakatat_value))
                else:
                    sakatat_status_value = str(sakatat_value)
                    
    except Exception:
        # If we can't get status, use defaults
        pass
    
    # Generate QR code URL for cloud app tracking with i18n support
    from django.utils.translation import get_language
    current_language = get_language() or 'tr'  # Default to Turkish
    base_url = getattr(settings, 'SITE_URL', 'https://carnitrack-app-1000671720976.europe-west1.run.app')
    qr_url = f"{base_url}/{current_language}/processing/animals/{animal.id}/"
    
    # Use only the URL for QR code data
    qr_data = qr_url
    
    # Get printer compatibility mode
    compat_mode = get_printer_compatibility_mode()
    
    return {
        'uretici': format_turkish_text_for_printer(uretici, compat_mode),
        'kupe_no': format_turkish_text_for_printer(kupe_no, compat_mode),
        'tuccar': format_turkish_text_for_printer(tuccar, compat_mode),
        'kesim_tarihi': kesim_tarihi,
        'stt': stt,
        'siparis_no': format_turkish_text_for_printer(siparis_no, compat_mode),
        'cinsi': cinsi,
        'weight': weight,
        'bowels_status': format_turkish_text_for_printer(bowels_status_value, compat_mode),  # Changed from karkas_status
        'sakatat_status': format_turkish_text_for_printer(sakatat_status_value, compat_mode),
        'isletme_onay_no': '17-0509',  # Fixed approval number
        'qr_url': qr_url,
        'qr_data': qr_data,
    }

def format_turkish_text_for_printer(text: str, compatibility_mode: str = 'unicode') -> str:
    """
    Format Turkish text for TSC printer compatibility with multiple modes.
    
    Args:
        text: Input text with Turkish characters
        compatibility_mode: 'unicode' (default), 'ascii', or 'codepage1254'
    
    Returns:
        Formatted text suitable for printer
    """
    if not text:
        return ""
    
    if compatibility_mode == 'unicode':
        # Keep Turkish characters as-is (requires CODEPAGE 1254 support)
        # Most modern TSC printers support this with proper codepage setting
        return text
        
    elif compatibility_mode == 'ascii':
        # Replace Turkish characters with ASCII equivalents (safest for old printers)
        char_map = {
            'ı': 'i', 'İ': 'I',  # Turkish i
            'ğ': 'g', 'Ğ': 'G',  # Turkish g
            'ü': 'u', 'Ü': 'U',  # Turkish u
            'ş': 's', 'Ş': 'S',  # Turkish s
            'ö': 'o', 'Ö': 'O',  # Turkish o
            'ç': 'c', 'Ç': 'C',  # Turkish c
        }
        
        result = text
        for turkish_char, ascii_char in char_map.items():
            result = result.replace(turkish_char, ascii_char)
        return result
        
    elif compatibility_mode == 'codepage1254':
        # Ensure proper encoding for Windows-1254 codepage
        try:
            # Encode to Windows-1254 and back to ensure compatibility
            encoded = text.encode('windows-1254', errors='replace')
            return encoded.decode('windows-1254')
        except:
            # Fallback to ASCII mode if encoding fails
            return format_turkish_text_for_printer(text, 'ascii')
    
    return text

def get_printer_compatibility_mode() -> str:
    """
    Get printer compatibility mode from settings.
    """
    return getattr(settings, 'PRINTER_TURKISH_MODE', 'unicode')

def generate_tspl_prn_label(animal, label_type='hot_carcass') -> str:
    """
    Generate TSPL/PRN commands for animal label based on the Turkish hot carcass format.
    Compatible with TSC printers using the exact format from your example.
    """
    label_data = generate_animal_label_data(animal)
    company_info = get_company_info()
    
    # Company logo BITMAP data
    company_logo_bitmap = get_company_logo_bitmap()
    
    # TSPL template matching your exact format (100mm x 260mm, 4 labels per sheet)
    tspl_template = f'''SIZE 100 mm, 260 mm
BLINE 10 mm, 0 mm
SPEED 3
DENSITY 12
SET RIBBON ON
DIRECTION 0,0
REFERENCE 0,0
OFFSET 0 mm
SET PEEL OFF
SET CUTTER OFF
SET PARTIAL_CUTTER OFF
SET TEAR ON
CLS
{company_logo_bitmap}
CODEPAGE 1254

TEXT 779,80,"0",90,9,9,"Küpe No"
TEXT 679,295,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 643,295,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 749,807,"ROMAN.TTF",90,1,10,"NET KG"
BAR 724,807, 1, 93
TEXT 779,1643,"0",90,14,11,"{company_info['company_name']}"
TEXT 747,1610,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 715,1626,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 683,1649,"ROMAN.TTF",90,1,11,"Ruhsat No: {company_info['license_no']}"
TEXT 651,1599,"ROMAN.TTF",90,1,11,"İşlem No: {label_data['siparis_no']}"
TEXT 785,295,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 771,1028,"ROMAN.TTF",180,1,10,"{label_data['cinsi']} KOL"
TEXT 745,80,"0",90,9,9,"Üretici Ünvanı"
TEXT 752,295,"0",90,10,11,"{label_data['uretici']}"
TEXT 711,80,"0",90,9,9,"Tüccar Ünvanı"
TEXT 677,80,"0",90,9,9,"Kesim Tarihi"
TEXT 641,80,"0",90,9,9,"Son Tüketim Tarihi"
TEXT 718,295,"0",90,10,11,"{label_data['tuccar']}"
TEXT 702,807,"0",90,25,14,"{label_data['weight']}"
TEXT 771,984,"ROMAN.TTF",180,1,9,"{label_data['bowels_status']}"
TEXT 772,958,"ROMAN.TTF",180,1,9,"{label_data['sakatat_status']}"
QRCODE 772,617,L,5,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 779,270,"0",90,9,9,":"
TEXT 745,270,"0",90,9,9,":"
TEXT 711,270,"0",90,9,9,":"
TEXT 677,270,"0",90,9,9,":"
TEXT 641,270,"0",90,9,9,":"
TEXT 579,80,"0",90,9,9,"Küpe No"
TEXT 479,295,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 443,295,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 549,807,"ROMAN.TTF",90,1,10,"NET KG"
BAR 524,807, 1, 93
TEXT 579,1643,"0",90,14,11,"{company_info['company_name']}"
TEXT 547,1610,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 515,1626,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 483,1649,"ROMAN.TTF",90,1,11,"Ruhsat No: {company_info['license_no']}"
TEXT 451,1599,"ROMAN.TTF",90,1,11,"İşlem No: {label_data['siparis_no']}"
TEXT 585,295,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 571,1028,"ROMAN.TTF",180,1,10,"{label_data['cinsi']} KOL"
TEXT 545,80,"0",90,9,9,"Üretici Ünvanı"
TEXT 552,295,"0",90,10,11,"{label_data['uretici']}"
TEXT 511,80,"0",90,9,9,"Tüccar Ünvanı"
TEXT 477,80,"0",90,9,9,"Kesim Tarihi"
TEXT 441,80,"0",90,9,9,"Son Tüketim Tarihi"
TEXT 518,295,"0",90,10,11,"{label_data['tuccar']}"
TEXT 502,807,"0",90,25,14,"{label_data['weight']}"
TEXT 571,984,"ROMAN.TTF",180,1,9,"{label_data['bowels_status']}"
TEXT 572,958,"ROMAN.TTF",180,1,9,"{label_data['sakatat_status']}"
QRCODE 572,617,L,5,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 579,270,"0",90,9,9,":"
TEXT 545,270,"0",90,9,9,":"
TEXT 511,270,"0",90,9,9,":"
TEXT 477,270,"0",90,9,9,":"
TEXT 441,270,"0",90,9,9,":"
TEXT 379,80,"0",90,9,9,"Küpe No"
TEXT 279,295,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 243,295,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 349,807,"ROMAN.TTF",90,1,10,"NET KG"
BAR 324,807, 1, 93
TEXT 379,1643,"0",90,14,11,"{company_info['company_name']}"
TEXT 347,1610,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 315,1626,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 283,1649,"ROMAN.TTF",90,1,11,"Ruhsat No: {company_info['license_no']}"
TEXT 251,1599,"ROMAN.TTF",90,1,11,"İşlem No: {label_data['siparis_no']}"
TEXT 385,295,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 371,1028,"ROMAN.TTF",180,1,10,"{label_data['cinsi']} KOL"
TEXT 345,80,"0",90,9,9,"Üretici Ünvanı"
TEXT 352,295,"0",90,10,11,"{label_data['uretici']}"
TEXT 311,80,"0",90,9,9,"Tüccar Ünvanı"
TEXT 277,80,"0",90,9,9,"Kesim Tarihi"
TEXT 241,80,"0",90,9,9,"Son Tüketim Tarihi"
TEXT 318,295,"0",90,10,11,"{label_data['tuccar']}"
TEXT 302,807,"0",90,25,14,"{label_data['weight']}"
TEXT 371,984,"ROMAN.TTF",180,1,9,"{label_data['bowels_status']}"
TEXT 372,958,"ROMAN.TTF",180,1,9,"{label_data['sakatat_status']}"
QRCODE 372,617,L,5,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 379,270,"0",90,9,9,":"
TEXT 345,270,"0",90,9,9,":"
TEXT 311,270,"0",90,9,9,":"
TEXT 277,270,"0",90,9,9,":"
TEXT 241,270,"0",90,9,9,":"

REM Label 4 (Bottom)
TEXT 180,80,"0",90,9,9,"Küpe No"
TEXT 80,295,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 44,295,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 150,807,"ROMAN.TTF",90,1,10,"NET KG"
BAR 125,807, 1, 93
TEXT 180,1643,"0",90,14,11,"{company_info['company_name']}"
TEXT 148,1610,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 116,1626,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 84,1649,"ROMAN.TTF",90,1,11,"Ruhsat No: {company_info['license_no']}"
TEXT 52,1599,"ROMAN.TTF",90,1,11,"İşlem No: {label_data['siparis_no']}"
TEXT 186,295,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 172,1028,"ROMAN.TTF",180,1,10,"{label_data['cinsi']} KOL"
TEXT 146,80,"0",90,9,9,"Üretici Ünvanı"
TEXT 153,295,"0",90,10,11,"{label_data['uretici']}"
TEXT 112,80,"0",90,9,9,"Tüccar Ünvanı"
TEXT 78,80,"0",90,9,9,"Kesim Tarihi"
TEXT 42,80,"0",90,9,9,"Son Tüketim Tarihi"
TEXT 119,295,"0",90,10,11,"{label_data['tuccar']}"
TEXT 103,807,"0",90,25,14,"{label_data['weight']}"
TEXT 172,984,"ROMAN.TTF",180,1,9,"{label_data['bowels_status']}"
TEXT 173,958,"ROMAN.TTF",180,1,9,"{label_data['sakatat_status']}"
QRCODE 173,617,L,5,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 180,270,"0",90,9,9,":"
TEXT 146,270,"0",90,9,9,":"
TEXT 112,270,"0",90,9,9,":"
TEXT 78,270,"0",90,9,9,":"
TEXT 42,270,"0",90,9,9,":"

PRINT 1,1'''
    
    return tspl_template

def generate_bat_file_content(prn_commands: str, printer_config: dict = None) -> str:
    """
    Generate simple .bat file content that sends PRN file to default printer.
    
    Args:
        prn_commands: The TSPL/PRN commands to send to printer
        printer_config: Not used - kept for backward compatibility
    """
    # Format PRN commands for batch file
    formatted_prn = _format_prn_for_bat(prn_commands)
    
    # Generate simple .bat file that uses the default printer
    bat_content = f'''@echo off
echo.
echo =========================================
echo    Animal Label Printer
echo =========================================
echo.

REM Create temporary PRN file
set TEMP_FILE=%TEMP%\\animal_label_%RANDOM%.prn

echo Creating PRN file...
REM Write PRN commands to temporary file
(
{formatted_prn}
) > "%TEMP_FILE%"

echo Sending to default printer...
REM Send PRN file to default printer using copy command
copy "%TEMP_FILE%" PRN > nul

REM Clean up temporary file
del "%TEMP_FILE%" > nul 2>&1

echo Label sent successfully!
echo.
pause
'''
    
    return bat_content

def _format_prn_for_bat(prn_commands: str) -> str:
    """
    Format PRN commands for inclusion in BAT file.
    Each line needs to be prefixed with 'echo ' for BAT file.
    """
    lines = prn_commands.strip().split('\n')
    formatted_lines = []
    
    for line in lines:
        line = line.strip()
        if line:  # Skip empty lines
            # Escape special characters for batch files
            line = line.replace('"', '""')  # Escape quotes
            line = line.replace('%', '%%')  # Escape percent signs
            formatted_lines.append(f'echo {line}')
    
    return '\n'.join(formatted_lines)

def generate_pdf_label(animal, label_type='hot_carcass') -> BytesIO:
    """
    Generate PDF label for animal based on the Turkish hot carcass format.
    """
    label_data = generate_animal_label_data(animal)
    
    # Create PDF buffer
    buffer = BytesIO()
    
    # Create PDF canvas (A4 size)
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Set font and size
    c.setFont("Helvetica-Bold", 12)
    
    # Title
    c.drawString(50, height - 50, "ANIMAL LABEL")
    c.setFont("Helvetica", 10)
    
    # Label content
    y_position = height - 80
    line_height = 20
    
    # Producer information
    c.drawString(50, y_position, f"ETIKET URETICI: {label_data['uretici']}")
    y_position -= line_height
    
    c.drawString(50, y_position, f"KUP NO: {label_data['kupe_no']}")
    y_position -= line_height
    
    c.drawString(50, y_position, f"TUCCAR ADI: {label_data['tuccar']}")
    y_position -= line_height * 2
    
    # Slaughter information
    c.drawString(50, y_position, f"KESIM TARIHI: {label_data['kesim_tarihi']}")
    y_position -= line_height
    
    c.drawString(50, y_position, f"STT: {label_data['stt']}")
    y_position -= line_height
    
    c.drawString(50, y_position, f"SIPARIS NO: {label_data['siparis_no']}")
    y_position -= line_height * 2
    
    # Animal information
    c.drawString(50, y_position, f"CINSI: {label_data['cinsi']}")
    y_position -= line_height
    
    c.drawString(50, y_position, f"ISLETME ONAY NO: {label_data['isletme_onay_no']}")
    y_position -= line_height * 3  # More space for QR code
    
    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(label_data['qr_url'])
    qr.make(fit=True)
    
    # Create QR code image and save to temporary file
    qr_img = qr.make_image(fill_color="black", back_color="white")
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
        qr_img.save(tmp_file.name, format='PNG')
        # Add QR code to PDF
        c.drawImage(tmp_file.name, 50, y_position - 100, width=100, height=100)
        # Clean up temporary file
        os.unlink(tmp_file.name)
    
    # Save PDF
    c.save()
    buffer.seek(0)
    
    return buffer

def create_animal_label(animal, label_type='hot_carcass', user=None, printer_config=None):
    """
    Create an AnimalLabel instance with generated TSPL/PRN and .bat content.
    
    Args:
        animal: Animal instance
        label_type: Type of label (default: 'hot_carcass')
        user: User who created the label
        printer_config: Printer configuration dict for .bat file generation
    """
    from .models import AnimalLabel
    
    # Default printer config if none provided
    if printer_config is None:
        printer_config = {'type': 'com', 'port': 'COM3'}
    
    # Generate TSPL/PRN content
    prn_content = generate_tspl_prn_label(animal, label_type)
    
    # Generate .bat file content
    bat_content = generate_bat_file_content(prn_content, printer_config)
    
    # Generate PDF content
    pdf_buffer = generate_pdf_label(animal, label_type)
    
    # Create AnimalLabel instance
    animal_label = AnimalLabel(
        animal=animal,
        label_type=label_type,
        printed_by=user,
        prn_content=prn_content,  # Store PRN instead of ZPL
        bat_content=bat_content   # Store .bat file content
    )
    
    # Save to get the ID
    animal_label.save()
    
    # Save PDF file
    from django.core.files.base import ContentFile
    pdf_filename = f"animal_label_{animal.identification_tag}_{label_type}_{animal_label.id}.pdf"
    animal_label.pdf_file.save(pdf_filename, ContentFile(pdf_buffer.getvalue()), save=True)
    
    return animal_label

def get_animal_label_download_data(animal_label, format_type='bat'):
    """
    Get download data for animal label in specified format.
    
    Args:
        animal_label: AnimalLabel instance
        format_type: 'bat', 'prn', or 'pdf'
    """
    if format_type.lower() == 'bat':
        return {
            'content': animal_label.bat_content,
            'filename': f"print_label_{animal_label.animal.identification_tag}_{animal_label.label_type}.bat",
            'content_type': 'application/octet-stream'
        }
    elif format_type.lower() == 'prn':
        return {
            'content': animal_label.prn_content,
            'filename': f"animal_label_{animal_label.animal.identification_tag}_{animal_label.label_type}.prn",
            'content_type': 'text/plain'
        }
    elif format_type.lower() == 'pdf':
        if animal_label.pdf_file:
            return {
                'file': animal_label.pdf_file,
                'filename': f"animal_label_{animal_label.animal.identification_tag}_{animal_label.label_type}.pdf",
                'content_type': 'application/pdf'
            }
        else:
            raise ValueError("PDF file not found for this label")
    else:
        raise ValueError(f"Unsupported format: {format_type}")

# Backwards compatibility functions (keeping old ZPL function names)
def generate_zpl_label(animal, label_type='hot_carcass') -> str:
    """
    Backwards compatibility - now generates TSPL/PRN instead of ZPL.
    """
    return generate_tspl_prn_label(animal, label_type)

def get_company_logo_bitmap() -> str:
    """
    Returns the static company logo BITMAP data for TSPL/PRN labels.
    This BITMAP is placed at position 11,1043 with dimensions 98x96.
    """
    import base64
    
    # Base64 encoded bitmap data (extracted from BOS.prn)
    bitmap_data_b64 = "//////////VVqq9V///////////////////////////qq1Veq///////////////////////////6qtVXqv//////////////////////////+qrVV6r/////////////////////////6qtVXq//////3////////////////////9VWqr1f/////7/////////////////////VVqq9X/////+/////////////////////1VaqvV//////v////////////////6qvVV6qtX////////////////////////9VXqq9VWr/////////////////////////VV6qvVVq/////////////////////////1Veqr1Vav////////////////////7qrVVaq/VVa//////////////////////91VqqtVfqqtf//////////////////////dVaqrVX6qrX//////////////////////3VWqq1V+qq1////////////////////61Vav///6qrX/////////////////////9aqtX///9VVr//////////////////////WqrV////VVa//////////////////////1qq1f///1VWv/////////////3////1VWr///////9a///////////////7////6qrV///////+tf//////////////+////+qq1f///////rX///////////////v////qqtX///////61/////////////////1Wq//////////rf///9//////////////6rVf/////////1v///+//////////////+q1X/////////9b////v//////////////qtV//////////W////7////////////qr3//////////1///////////////////1V7//////////6///////////////////9Ve//////////+v///////////////////VXv//////////r///////////////6q9f//////////76v////////////////9Vev//////////99X/////////////////VXr///////////fV/////////////////1V6///////////31f//////////////tVf////////////9X////////////////2qv////////////+r////////////////9qr/////////////q/////////////////aq/////////////6v////////////9VVr//////3//////+r//////////////+qq1//////7///////V///////////////qqtf/////+///////1f//////////////6qrX//////v//////9X////////////96v///////////////3//////////////+9X///////////////7///////////////vV///////////////+///////////////71f///////////////v///////////+qv///////////////////////////////VX///////////////////////////////1V///////////////////////////////9Vf////////////////////////////7Vf//////////////+///////////////9qv///////////////f///////////////ar///////////////3///////////////2q///////////////9////////////9Vb/////////////////3////////////+qt/////////////////7/////////////qrf////////////////+/////////////6q3/////////////////v//////////er//////////9///////v////////////vV//////////+///////3////////////71f//////////v//////9////////////+9X//////////7///////f/////////6r//////////////////////7////////9V//////////////////////9/////////Vf//////////////////////f////////1X//////////////////////3///+//1X/////7////////////////9//////f/6r/////9////////////////+//////3/+q//////f////////////////v/////9//qv/////3////////////////7/////1W///////////////////////3///////6rf//////////////////////7///////+q3//////////////////////+////////qt///////////////////////v/////q////////////////////////v///////1f///////////////////////3///////9X///////////////////////9////////V////////////////////////f////q9//////////////f////////9f//////1e//////////////v////////+v//////9Xv/////////////7/////////r///////V7/////////////+/////////6////9V///////////////+q//////////////+q////////////////Vf//////////////qv///////////////1X//////////////6r///////////////9V////////////1r////////+//////oAH/////////////61/////////f/////0AD/////////////+tf////////3/////9AA//////////////rX////////9//////QAP//////////6q///////////////wFAC//////1/////9Vf//////////////4CgBf/////6//////VX//////////////+AoAX/////+v/////1V///////////////gKAF//////r///vX///9//////////8GPoB//////z/////3r///+//////////+DH0A//////5/////96////v//////////gx9AP/////+f/////ev///7//////////4MfQD//////n//9V///////////////AYlwA//////vf///+q///////////////gMS4Af/////3v////qv//////////////4DEuAH/////97////6r//////////////+AxLgB//////e//6v//////////////4BAfAD/////9f////9X//////////////8AgPgB/////+v/////V///////////////AID4Af/////r/////1f//////////////wCA+AH/////6//+r//////////////8AFD8AH+////+/////V//////////////+ACh+AD/f////f////1f//////////////gAofgA/3////3////9X//////////////4AKH4AP9////9//1X//////////////wAANwAH/////7////6r//////////////4AAG4AD/////9////+q//////////////+AABuAA//////f////qv//////////////gAAbgAP/////3//W///////f//////+ABBfAAP/////X////rf//////v///////AAgvgAH/////r////63//////7///////wAIL4AB/////6////+t//////+///////8ACC+AAf////+v/6v///////+v/1/6v4AH6/gAf//9f/v///9X////////X/6/9X8AD9fwAP//+v/3////V////////1/+v/V/AA/X8AD///r/9////1f///////9f/r/1fwAP1/AA///6//f/9f+qr/VWqwA/A/ADAA//PAA//4Af6////+v/VV/qrVYAfgfgBgAf/ngAf/8AP9f////r/1Vf6q1WAH4H4AYAH/54AH//AD/X////6/9VX+qtVgB+B+AGAB/+eAB//wA/1/9X/+tX8qqhAH4D8AYAPV8+AD//gB/1///+r//Wr+VVQgD8B+AMAHq+fAB//wA/6////q//1q/lVUIA/AfgDAB6vnwAf/8AP+v///6v/9av5VVCAPwH4AwAer58AH//AD/r/qv/1X/q9VcAPgHwAAB977+AH/+AH/r///1X/6r/1equAHwD4AAA+99/AD//AD/1///9V/+q/9XqrgB8A+AAAPvffwA//wA/9f///Vf/qv/V6q4AfAPgAAD7338AP/8AP/X+t//qr/VXq4A+AOAAAPj/H8AP/wAf+////W//1V/qr1cAfAHAAAHx/j+AH/4AP/f///1v/9Vf6q9XAHwBwAAB8f4/gB/+AD/3///9b//VX+qvVwB8AcAAAfH+P4Af/gA/9/1f/+tX9qq5AD4A8AAA/F8f4A//gB/1///6v//Wr+1VcgB8AeAAAfi+P8Af/wA/6///+r//1q/tVXIAfAHgAAH4vj/AH/8AP+v///q//9av7VVyAHwB4AAB+L4/wB//AD/r/6//1VPqtVeAPgDwAAH8/4/gD/+AH/7///9f/6qn1WqvAHwB4AAD+f8fwB//AD/9////X/+qp9VqrwB8AeAAA/n/H8Af/wA//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"
    
    # Decode back to original format
    bitmap_bytes = base64.b64decode(bitmap_data_b64)
    bitmap_data = bitmap_bytes.decode('latin-1')
    
    return f"BITMAP 11,1043,98,96,1,{bitmap_data}"

def get_company_info() -> dict:
    """
    Get company information for labels from settings or defaults.
    """
    compat_mode = get_printer_compatibility_mode()
    return {
        'company_name': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_NAME', 'POMET ET  VE'), compat_mode),
        'company_full_name': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_FULL_NAME', 'ET ÜRÜNLERİ LTD. ŞTİ.'), compat_mode),
        'company_address': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_ADDRESS', 'Lapseki / ÇANAKKALE'), compat_mode),
        'license_no': getattr(settings, 'LICENSE_NO', '17-0509'),
        'operation_no': getattr(settings, 'OPERATION_NO', 'TR17 12345678'),
    }
