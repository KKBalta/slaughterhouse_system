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
    
    # Truncate uretici to first two words for label fitting
    uretici = truncate_to_first_two_words(uretici)
    
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
        'cattle': 'SIGIR',
        'sheep': 'KOYUN',
        'goat': 'KECI',
        'lamb': 'KUZU',
        'oglak': 'OGLAK',
        'calf': 'BUZA',
        'heifer': 'DUVE',
        'beef': 'DANA',
    }
    cinsi = animal_type_mapping.get(animal.animal_type, animal.animal_type.upper())
    
    # Get kupe number (identification tag) with validation for batch file compatibility
    raw_kupe_no = animal.identification_tag or "Bilinmiyor"
    validation_result = validate_animal_identification_for_batch(raw_kupe_no)
    kupe_no = validation_result['sanitized_name']
    
    # Log warnings if any (for debugging)
    if validation_result['warnings']:
        print(f"Animal {animal.id} identification validation warnings: {validation_result['warnings']}")
    
    # Get trader (destination address from slaughter order)
    tuccar = order.destination or ""
    
    # Truncate tuccar to first two words for label fitting
    tuccar = truncate_to_first_two_words(tuccar)
    
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
    bowels_status_value = "0.51"  # Default bowels status
    sakatat_status_value = "0.51"  # Default sakatat status
    
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

def truncate_to_first_two_words(text: str) -> str:
    """
    Truncate text to first two words for label fitting.
    
    Args:
        text: Input text to truncate
    
    Returns:
        Text truncated to first two words, or original text if 2 or fewer words
    """
    if not text:
        return ""
    
    # Split by whitespace and take first two words
    words = text.strip().split()
    if len(words) <= 2:
        return text.strip()
    
    return ' '.join(words[:2])

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
    
    
    # TSPL template matching your exact format (100mm x 260mm, 4 labels per sheet)
    tspl_template = f'''SIZE 97.5 mm, 260 mm
GAP 3 mm, 0 mm
DIRECTION 0,0
REFERENCE 0,0
OFFSET 0 mm
SET PEEL OFF
SET CUTTER OFF
SET PARTIAL_CUTTER OFF
SET TEAR ON
CLS
CODEPAGE 1254
TEXT 766,64,"0",90,9,9,"Kupe No"
TEXT 666,279,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 630,279,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 739,791,"ROMAN.TTF",90,1,10,"NET KG"
BAR 714,791, 1, 93
TEXT 768,1583,"0",90,14,11,"{company_info['company_name']}"
TEXT 736,1602,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 704,1556,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 672,1576,"ROMAN.TTF",90,1,11,"® ISLETME ONAY NO: {company_info['license_no']}"
TEXT 640,1622,"ROMAN.TTF",90,1,11,"CKALE VD: {company_info['operation_no']}"
TEXT 773,279,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 724,1033,"ROMAN.TTF",180,1,10,"{label_data['cinsi']}"
TEXT 732,64,"0",90,9,9,"Uretici Unvani"
TEXT 739,279,"0",90,10,11,"{label_data['uretici']}"
TEXT 698,64,"0",90,9,9,"Tuccar Unvani"
TEXT 664,64,"0",90,9,9,"Kesim Tarihi"
TEXT 628,64,"0",90,9,9,"Son Tuketim Tar."
TEXT 705,279,"0",90,10,11,"{label_data['tuccar']}"
TEXT 692,791,"0",90,25,14,"{label_data['weight']}"
TEXT 761,944,"ROMAN.TTF",180,1,9,"SAKATAT {label_data['sakatat_status']}"
QRCODE 770,601,L,4,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 766,255,"0",90,9,9,":"
TEXT 732,255,"0",90,9,9,":"
TEXT 698,255,"0",90,9,9,":"
TEXT 664,255,"0",90,9,9,":"
TEXT 628,255,"0",90,9,9,":"
TEXT 769,986,"0",180,9,9,"{label_data['siparis_no']}"
TEXT 566,64,"0",90,9,9,"Kupe No"
TEXT 466,279,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 430,279,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 539,791,"ROMAN.TTF",90,1,10,"NET KG"
BAR 514,791, 1, 93
TEXT 568,1583,"0",90,14,11,"{company_info['company_name']}"
TEXT 536,1602,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 504,1556,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 472,1576,"ROMAN.TTF",90,1,11,"® ISLETME ONAY NO: {company_info['license_no']}"
TEXT 440,1622,"ROMAN.TTF",90,1,11,"CKALE VD: {company_info['operation_no']}"
TEXT 573,279,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 524,1033,"ROMAN.TTF",180,1,10,"{label_data['cinsi']}"
TEXT 532,64,"0",90,9,9,"Uretici Unvani"
TEXT 539,279,"0",90,10,11,"{label_data['uretici']}"
TEXT 498,64,"0",90,9,9,"Tuccar Unvani"
TEXT 464,64,"0",90,9,9,"Kesim Tarihi"
TEXT 428,64,"0",90,9,9,"Son Tuketim Tar."
TEXT 505,279,"0",90,10,11,"{label_data['tuccar']}"
TEXT 492,791,"0",90,25,14,"{label_data['weight']}"
TEXT 561,944,"ROMAN.TTF",180,1,9,"SAKATAT {label_data['sakatat_status']}"
QRCODE 570,601,L,4,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 566,255,"0",90,9,9,":"
TEXT 532,255,"0",90,9,9,":"
TEXT 498,255,"0",90,9,9,":"
TEXT 464,255,"0",90,9,9,":"
TEXT 428,255,"0",90,9,9,":"
TEXT 584,986,"0",180,9,9,"{label_data['siparis_no']}"
TEXT 366,64,"0",90,9,9,"Kupe No"
TEXT 266,279,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 230,279,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 339,791,"ROMAN.TTF",90,1,10,"NET KG"
BAR 314,791, 1, 93
TEXT 368,1583,"0",90,14,11,"{company_info['company_name']}"
TEXT 336,1602,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 304,1556,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 272,1576,"ROMAN.TTF",90,1,11,"® ISLETME ONAY NO: {company_info['license_no']}"
TEXT 240,1622,"ROMAN.TTF",90,1,11,"CKALE VD: {company_info['operation_no']}"
TEXT 373,279,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 324,1033,"ROMAN.TTF",180,1,10,"{label_data['cinsi']}"
TEXT 332,64,"0",90,9,9,"Uretici Unvani"
TEXT 339,279,"0",90,10,11,"{label_data['uretici']}"
TEXT 298,64,"0",90,9,9,"Tuccar Unvani"
TEXT 264,64,"0",90,9,9,"Kesim Tarihi"
TEXT 228,64,"0",90,9,9,"Son Tuketim Tar."
TEXT 305,279,"0",90,10,11,"{label_data['tuccar']}"
TEXT 292,791,"0",90,25,14,"{label_data['weight']}"
TEXT 361,944,"ROMAN.TTF",180,1,9,"SAKATAT {label_data['sakatat_status']}"
QRCODE 370,601,L,4,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 366,255,"0",90,9,9,":"
TEXT 332,255,"0",90,9,9,":"
TEXT 298,255,"0",90,9,9,":"
TEXT 264,255,"0",90,9,9,":"
TEXT 228,255,"0",90,9,9,":"
TEXT 384,986,"0",180,9,9,"{label_data['siparis_no']}"
TEXT 167,64,"0",90,9,9,"Kupe No"
TEXT 67,279,"ROMAN.TTF",90,1,10,"{label_data['kesim_tarihi']}"
TEXT 31,279,"ROMAN.TTF",90,1,10,"{label_data['stt']}"
TEXT 140,791,"ROMAN.TTF",90,1,10,"NET KG"
BAR 115,791, 1, 93
TEXT 169,1583,"0",90,14,11,"{company_info['company_name']}"
TEXT 137,1602,"ROMAN.TTF",90,1,11,"{company_info['company_full_name']}"
TEXT 105,1556,"ROMAN.TTF",90,1,11,"{company_info['company_address']}"
TEXT 73,1576,"ROMAN.TTF",90,1,11,"® ISLETME ONAY NO: {company_info['license_no']}"
TEXT 41,1622,"ROMAN.TTF",90,1,11,"CKALE VD: {company_info['operation_no']}"
TEXT 174,279,"0",90,10,11,"{label_data['kupe_no']}"
TEXT 125,1033,"ROMAN.TTF",180,1,10,"{label_data['cinsi']}"
TEXT 133,64,"0",90,9,9,"Uretici Unvani"
TEXT 140,279,"0",90,10,11,"{label_data['uretici']}"
TEXT 99,64,"0",90,9,9,"Tuccar Unvani"
TEXT 65,64,"0",90,9,9,"Kesim Tarihi"
TEXT 29,64,"0",90,9,9,"Son Tuketim Tar."
TEXT 106,279,"0",90,10,11,"{label_data['tuccar']}"
TEXT 93,791,"0",90,25,14,"{label_data['weight']}"
TEXT 162,944,"ROMAN.TTF",180,1,9,"SAKATAT {label_data['sakatat_status']}"
QRCODE 171,601,L,4,A,90,M2,S7,"{label_data['qr_data']}"
TEXT 167,255,"0",90,9,9,":"
TEXT 133,255,"0",90,9,9,":"
TEXT 99,255,"0",90,9,9,":"
TEXT 65,255,"0",90,9,9,":"
TEXT 29,255,"0",90,9,9,":"
TEXT 185,986,"0",180,9,9,"{label_data['siparis_no']}"
PRINT 1,1
'''
    
    # Convert Unix line endings to Windows line endings for TSC printer compatibility
    tspl_template = tspl_template.replace('\n', '\r\n')
    
    return tspl_template

def generate_bat_file_content(prn_commands: str, printer_config: dict = None, filename: str = None) -> str:
    """
    Generate enhanced .bat file content with multiple printing methods and better error handling.
    
    Args:
        prn_commands: The TSPL/PRN commands to send to printer
        printer_config: Optional config dict, can specify 'port', 'printer_name', 'method'
        filename: Optional custom filename for the PRN file (default: animal_label.prn)
    """
    # Get configuration or use defaults
    printer_port = 'LPT1'
    printer_name = ''
    method = 'auto'  # auto, lpt, usb, network
    
    if printer_config:
        printer_port = printer_config.get('port', 'LPT1')
        printer_name = printer_config.get('printer_name', '')
        method = printer_config.get('method', 'auto')
    
    # Use dynamic filename or default
    prn_filename = filename if filename else 'animal_label.prn'
    
    # Format PRN commands for batch file
    formatted_prn = _format_prn_for_bat(prn_commands)
    
    # Generate enhanced .bat file with multiple printing methods
    bat_content = f'''@echo off
setlocal enabledelayedexpansion
color 0A
echo.
echo =========================================================
echo              CARNITRACK LABEL PRINTER
echo =========================================================
echo.
echo Printing animal label using multiple methods...
echo.

REM Create label data file in current directory (no temp file issues)
set LABEL_FILE=%~dp0{prn_filename}
set SUCCESS=0

echo [INFO] Creating label file: %LABEL_FILE%
REM Create the PRN file using PowerShell for better quote handling
powershell -Command "Set-Content -Path '%LABEL_FILE%' -Value @'
{prn_commands}
'@ -Encoding UTF8" >nul 2>&1

if not exist "%LABEL_FILE%" (
    echo [WARNING] PowerShell method failed, trying echo method...
    REM Fallback method using echo commands
    (
{formatted_prn}
    ) > "%LABEL_FILE%"
    
    if not exist "%LABEL_FILE%" (
        echo [ERROR] Failed to create label file!
        goto :ERROR_EXIT
    )
)

echo [INFO] Label file created successfully
for %%A in ("%LABEL_FILE%") do echo [INFO] File size: %%~zA bytes
echo.

REM Method 1: Try direct LPT1 port (for parallel port printers)
echo [METHOD 1] Trying LPT1 port...
if exist LPT1 (
    echo [INFO] LPT1 port detected
    copy /b "%LABEL_FILE%" LPT1: >nul 2>&1
    if !errorlevel! equ 0 (
        echo [SUCCESS] Label sent via LPT1!
        set SUCCESS=1
        goto :CLEANUP
    ) else (
        echo [WARNING] LPT1 method failed
    )
) else (
    echo [WARNING] LPT1 port not available
)
echo.

REM Method 2: Try TYPE command to LPT1
echo [METHOD 2] Trying TYPE command to LPT1...
type "%LABEL_FILE%" >LPT1 2>nul
if !errorlevel! equ 0 (
    echo [SUCCESS] Label sent via TYPE to LPT1!
    set SUCCESS=1
    goto :CLEANUP
) else (
    echo [WARNING] TYPE to LPT1 failed
)
echo.

REM Method 3: Try alternative ports (LPT2, LPT3)
for %%P in (LPT2 LPT3) do (
    echo [METHOD 3] Trying %%P port...
    if exist %%P (
        copy /b "%LABEL_FILE%" %%P: >nul 2>&1
        if !errorlevel! equ 0 (
            echo [SUCCESS] Label sent via %%P!
            set SUCCESS=1
            goto :CLEANUP
        )
    )
)

REM Method 4: Try USB printer mapping (if printer name provided)
if not "%printer_name%"=="" (
    echo [METHOD 4] Trying USB printer mapping...
    echo [INFO] Mapping printer: {printer_name}
    net use LPT1: "\\\\%COMPUTERNAME%\\{printer_name}" >nul 2>&1
    if !errorlevel! equ 0 (
        copy /b "%LABEL_FILE%" LPT1: >nul 2>&1
        if !errorlevel! equ 0 (
            echo [SUCCESS] Label sent via USB mapping!
            set SUCCESS=1
            net use LPT1: /delete >nul 2>&1
            goto :CLEANUP
        )
        net use LPT1: /delete >nul 2>&1
    )
    echo [WARNING] USB printer mapping failed
    echo.
)

REM Method 5: Try print command (Windows built-in)
echo [METHOD 5] Trying Windows PRINT command...
print "%LABEL_FILE%" >nul 2>&1
if !errorlevel! equ 0 (
    echo [SUCCESS] Label sent via PRINT command!
    set SUCCESS=1
    goto :CLEANUP
) else (
    echo [WARNING] PRINT command failed
)
echo.

REM Method 6: Try notepad print (last resort)
echo [METHOD 6] Trying Notepad silent print...
start /wait notepad /p "%LABEL_FILE%" >nul 2>&1
if !errorlevel! equ 0 (
    echo [INFO] Notepad print dialog opened (please select your printer)
    set SUCCESS=1
    goto :CLEANUP
) else (
    echo [WARNING] Notepad print failed
)

:ERROR_EXIT
echo.
echo =========================================================
echo [ERROR] ALL PRINTING METHODS FAILED!
echo =========================================================
echo.
echo Troubleshooting steps:
echo 1. Check if printer is connected and powered on
echo 2. Verify printer drivers are installed
echo 3. Try printing a test page from Windows
echo 4. Check printer port settings (LPT1, USB, Network)
echo 5. Run this batch file as Administrator
echo.
echo Label file saved as: %LABEL_FILE%
echo You can manually send this file to your printer
echo.
color 0C
goto :END

:CLEANUP
echo.
echo =========================================================
echo [SUCCESS] LABEL SENT TO PRINTER!
echo =========================================================
echo.
echo Label details:
echo - File: %LABEL_FILE%
echo - Size: 4 labels per sheet (97.5mm x 260mm)
echo - Format: TSPL for TSC printers
echo.
echo If labels don't print correctly:
echo 1. Check printer paper size settings
echo 2. Verify TSPL/EPL printer compatibility  
echo 3. Adjust printer darkness/speed settings
echo.

REM Clean up label file (optional - comment out to keep for debugging)
REM del "%LABEL_FILE%" >nul 2>&1

:END
echo Press any key to exit...
pause >nul
endlocal
'''
    
    # Convert Unix line endings to Windows line endings for Windows compatibility
    bat_content = bat_content.replace('\n', '\r\n')
    
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
            # Use ^ to escape special characters instead of doubling quotes
            line = line.replace('%', '%%')  # Escape percent signs
            line = line.replace('^', '^^')  # Escape caret
            line = line.replace('&', '^&')  # Escape ampersand
            line = line.replace('|', '^|')  # Escape pipe
            line = line.replace('<', '^<')  # Escape less than
            line = line.replace('>', '^>')  # Escape greater than
            
            # For echo commands with quotes, use a different approach
            if '"' in line:
                # Use echo with quotes around the entire line
                formatted_lines.append(f'echo {line}')
            else:
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
        printer_config = {'port': 'LPT1'}
    
    # Generate TSPL/PRN content
    prn_content = generate_tspl_prn_label(animal, label_type)
    
    # Generate dynamic filename based on animal data with sanitized identification tag
    sanitized_tag = validate_and_sanitize_english_name(animal.identification_tag or "UNKNOWN")
    dynamic_filename = f"animal_label_{sanitized_tag}_{label_type}.prn"
    
    # Generate .bat file content with dynamic filename
    bat_content = generate_bat_file_content(prn_content, printer_config, dynamic_filename)
    
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
    # Get sanitized identification tag for filenames
    sanitized_tag = validate_and_sanitize_english_name(animal_label.animal.identification_tag or "UNKNOWN")
    
    if format_type.lower() == 'bat':
        return {
            'content': animal_label.bat_content,
            'filename': f"print_label_{sanitized_tag}_{animal_label.label_type}.bat",
            'content_type': 'application/octet-stream'
        }
    elif format_type.lower() == 'prn':
        return {
            'content': animal_label.prn_content,
            'filename': f"animal_label_{sanitized_tag}_{animal_label.label_type}.prn",
            'content_type': 'text/plain'
        }
    elif format_type.lower() == 'pdf':
        if animal_label.pdf_file:
            return {
                'file': animal_label.pdf_file,
                'filename': f"animal_label_{sanitized_tag}_{animal_label.label_type}.pdf",
                'content_type': 'application/pdf'
            }
        else:
            raise ValueError("PDF file not found for this label")
    else:
        raise ValueError(f"Unsupported format: {format_type}")

def generate_enhanced_printer_config_bat(prn_commands: str, printer_configs: list = None) -> str:
    """
    Generate a BAT file with multiple printer configurations for maximum compatibility.
    
    Args:
        prn_commands: The TSPL/PRN commands
        printer_configs: List of printer config dicts with different options
    """
    if not printer_configs:
        # Default configurations for different printer types
        printer_configs = [
            {'port': 'LPT1', 'method': 'lpt', 'name': 'Parallel Port Printer'},
            {'port': 'USB001', 'method': 'usb', 'name': 'USB Printer'},
            {'printer_name': 'TSC TTP-245C', 'method': 'network', 'name': 'Network TSC Printer'},
            {'printer_name': 'Zebra', 'method': 'network', 'name': 'Network Zebra Printer'},
        ]
    
    # Create a more robust method for writing PRN content
    # Instead of using echo commands, we'll create a separate PRN file and reference it
    prn_filename = "animal_label_data.prn"
    
    bat_content = f'''@echo off
setlocal enabledelayedexpansion
title CARNITRACK Universal Label Printer
color 0B

echo =========================================================
echo          CARNITRACK UNIVERSAL LABEL PRINTER
echo =========================================================
echo.
echo This tool will try multiple methods to print your label
echo Compatible with: TSC, Zebra, Datamax, Honeywell printers
echo.

REM Create label file with embedded PRN data
set LABEL_FILE=%~dp0animal_label_%date:~-4,4%%date:~-10,2%%date:~-7,2%_%time:~0,2%%time:~3,2%%time:~6,2%.prn
set SUCCESS=0
set ATTEMPT=0

echo Creating label file with embedded data...
REM Create the PRN file using PowerShell for better quote handling
powershell -Command "Set-Content -Path '%LABEL_FILE%' -Value @'
{prn_commands}
'@ -Encoding UTF8" >nul 2>&1

if not exist "%LABEL_FILE%" (
    echo ERROR: Could not create label file!
    echo Trying alternative method...
    
    REM Alternative method using echo (fallback)
    (
{_format_prn_for_bat_simple(prn_commands)}
    ) > "%LABEL_FILE%"
    
    if not exist "%LABEL_FILE%" (
        echo ERROR: All methods failed to create label file!
        pause
        exit /b 1
    )
)

echo Label file created: %LABEL_FILE%
for %%A in ("%LABEL_FILE%") do echo File size: %%~zA bytes
echo.

REM Try different printing methods
set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] Direct LPT1 port...
if exist LPT1 (
    copy /b "%LABEL_FILE%" LPT1: >nul 2>&1
    if !errorlevel! equ 0 (
        echo SUCCESS: Printed via LPT1
        set SUCCESS=1
        goto :SUCCESS
    )
)

set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] TYPE to LPT1...
type "%LABEL_FILE%" >LPT1 2>nul
if !errorlevel! equ 0 (
    echo SUCCESS: Printed via TYPE to LPT1
    set SUCCESS=1
    goto :SUCCESS
)

set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] Alternative parallel ports...
for %%P in (LPT2 LPT3) do (
    if exist %%P (
        copy /b "%LABEL_FILE%" %%P: >nul 2>&1
        if !errorlevel! equ 0 (
            echo SUCCESS: Printed via %%P
            set SUCCESS=1
            goto :SUCCESS
        )
    )
)

set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] Network printer discovery...
REM Try to find and use network printers
for /f "tokens=2" %%i in ('wmic printer get name /format:list ^| find "Name="') do (
    if not "%%i"=="" (
        echo Trying printer: %%i
        net use LPT1: "\\\\%COMPUTERNAME%\\%%i" >nul 2>&1
        if !errorlevel! equ 0 (
            copy /b "%LABEL_FILE%" LPT1: >nul 2>&1
            if !errorlevel! equ 0 (
                echo SUCCESS: Printed via network printer %%i
                set SUCCESS=1
                net use LPT1: /delete >nul 2>&1
                goto :SUCCESS
            )
            net use LPT1: /delete >nul 2>&1
        )
    )
)

set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] Windows print spooler...
print "%LABEL_FILE%" >nul 2>&1
if !errorlevel! equ 0 (
    echo SUCCESS: Sent to Windows print spooler
    set SUCCESS=1
    goto :SUCCESS
)

set /a ATTEMPT+=1
echo [ATTEMPT %ATTEMPT%] Opening with default application...
start "" "%LABEL_FILE%"
echo INFO: Label file opened with default application
echo Please use your application's print function
set SUCCESS=1
goto :SUCCESS

:SUCCESS
echo.
echo =========================================================
echo PRINTING COMPLETED SUCCESSFULLY!
echo =========================================================
echo.
echo Label Information:
echo - Format: TSPL/PRN (4 labels per sheet)
echo - Size: 97.5mm x 260mm
echo - Printer: TSC compatible
echo - Contains: Animal data, QR codes, company info
echo.
echo If labels didn't print correctly:
echo 1. Check printer is ON and has paper
echo 2. Verify correct paper size (97.5mm width)
echo 3. Check printer driver settings
echo 4. Try running as Administrator
echo.
goto :END

:END
REM Keep label file for debugging (remove next line to auto-delete)
echo Label file saved: %LABEL_FILE%
echo.
pause
endlocal
'''
    
    return bat_content.replace('\n', '\r\n')

def _format_prn_for_bat_simple(prn_commands: str) -> str:
    """
    Simple fallback method for formatting PRN commands for BAT file.
    Uses basic echo commands without complex escaping.
    """
    lines = prn_commands.strip().split('\n')
    formatted_lines = []
    
    for line in lines:
        line = line.strip()
        if line:  # Skip empty lines
            # Basic escaping for batch files
            line = line.replace('%', '%%')  # Escape percent signs
            formatted_lines.append(f'echo {line}')
    
    return '\n'.join(formatted_lines)

def create_printer_troubleshooting_guide() -> str:
    """
    Generate a troubleshooting guide for printer issues.
    """
    guide = '''
CARNITRACK PRINTER TROUBLESHOOTING GUIDE
========================================

COMMON ISSUES AND SOLUTIONS:

1. "LPT1 port not available"
   - Most modern computers don't have parallel ports
   - Solution: Use USB printer or network printer mapping

2. "Access denied" or "Permission error"
   - Run the batch file as Administrator
   - Right-click the .bat file → "Run as administrator"

3. "Printer not found"
   - Check printer is connected and powered on
   - Verify printer drivers are installed
   - Test with a Windows test page first

4. "Label prints but is garbled"
   - Check printer supports TSPL language
   - Verify paper size settings (97.5mm width)
   - Check printer darkness/speed settings

5. "Nothing prints"
   - Check printer queue for stuck jobs
   - Restart the print spooler service
   - Try a different USB port or cable

PRINTER SETUP INSTRUCTIONS:

For TSC Printers:
1. Install TSC printer drivers
2. Set paper size to 97.5mm x 260mm
3. Set print quality to 203 DPI
4. Enable TSPL language mode

For USB Printers:
1. Share the printer in Windows
2. Note the exact printer name
3. The batch file will try to map it automatically

For Network Printers:
1. Add printer via IP address
2. Share the printer
3. Ensure network connectivity

TESTING:
1. Print a Windows test page first
2. Try the batch file with a simple label
3. Check all cable connections
4. Verify printer language settings

If problems persist, contact technical support.
'''
    return guide

# Backwards compatibility functions (keeping old ZPL function names)
def generate_zpl_label(animal, label_type='hot_carcass') -> str:
    """
    Backwards compatibility - now generates TSPL/PRN instead of ZPL.
    """
    return generate_tspl_prn_label(animal, label_type)


def validate_and_sanitize_english_name(text: str, max_length: int = 50) -> str:
    """
    Validate and sanitize text to ensure it contains only English characters suitable for batch files.
    
    This function:
    1. Replaces Turkish characters with English equivalents
    2. Removes or replaces special characters that cause issues in batch files
    3. Ensures the result is safe for file names and batch file operations
    
    Args:
        text: Input text that may contain Turkish characters
        max_length: Maximum length for the sanitized text
    
    Returns:
        Sanitized text with only English characters safe for batch files
    """
    if not text:
        return ""
    
    # Turkish to English character mapping
    turkish_to_english = {
        'ı': 'i', 'İ': 'I',  # Turkish i
        'ğ': 'g', 'Ğ': 'G',  # Turkish g
        'ü': 'u', 'Ü': 'U',  # Turkish u
        'ş': 's', 'Ş': 'S',  # Turkish s
        'ö': 'o', 'Ö': 'O',  # Turkish o
        'ç': 'c', 'Ç': 'C',  # Turkish c
    }
    
    # Replace Turkish characters with English equivalents
    sanitized = text
    for turkish_char, english_char in turkish_to_english.items():
        sanitized = sanitized.replace(turkish_char, english_char)
    
    # Remove or replace characters that cause issues in batch files
    # These characters can cause problems in Windows batch files
    problematic_chars = {
        '<': '_', '>': '_', '|': '_', '?': '_', '*': '_',
        '"': '_', ':': '_', ';': '_', '=': '_', '+': '_',
        '[': '_', ']': '_', '{': '_', '}': '_', '^': '_',
        '&': '_', '%': '_', '!': '_', '@': '_', '#': '_',
        '$': '_', '~': '_', '`': '_', '\\': '_', '/': '_',
        ' ': '_', '\t': '_', '\n': '_', '\r': '_'
    }
    
    for char, replacement in problematic_chars.items():
        sanitized = sanitized.replace(char, replacement)
    
    # Remove any remaining non-ASCII characters
    sanitized = ''.join(char for char in sanitized if ord(char) < 128)
    
    # Remove multiple consecutive underscores and trim
    import re
    sanitized = re.sub(r'_+', '_', sanitized).strip('_')
    
    # Ensure it's not empty and limit length
    if not sanitized:
        sanitized = "ANIMAL"
    
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('_')
    
    return sanitized

def validate_animal_identification_for_batch(identification_tag: str) -> dict:
    """
    Validate animal identification tag for batch file compatibility.
    
    Args:
        identification_tag: The animal identification tag to validate
    
    Returns:
        Dictionary with validation results:
        {
            'is_valid': bool,
            'sanitized_name': str,
            'original_name': str,
            'warnings': list,
            'errors': list
        }
    """
    result = {
        'is_valid': True,
        'sanitized_name': '',
        'original_name': identification_tag or '',
        'warnings': [],
        'errors': []
    }
    
    if not identification_tag:
        result['errors'].append('Identification tag is empty')
        result['is_valid'] = False
        result['sanitized_name'] = 'UNKNOWN'
        return result
    
    # Check for Turkish characters
    turkish_chars = ['ı', 'İ', 'ğ', 'Ğ', 'ü', 'Ü', 'ş', 'Ş', 'ö', 'Ö', 'ç', 'Ç']
    has_turkish = any(char in identification_tag for char in turkish_chars)
    
    if has_turkish:
        result['warnings'].append('Contains Turkish characters that may cause batch file issues')
    
    # Check for problematic characters
    problematic_chars = ['<', '>', '|', '?', '*', '"', ':', ';', '=', '+', '[', ']', '{', '}', '^', '&', '%', '!', '@', '#', '$', '~', '`', '\\', '/']
    has_problematic = any(char in identification_tag for char in problematic_chars)
    
    if has_problematic:
        result['warnings'].append('Contains special characters that may cause batch file issues')
    
    # Generate sanitized version
    result['sanitized_name'] = validate_and_sanitize_english_name(identification_tag)
    
    # Check if sanitization changed the name significantly
    if result['sanitized_name'] != identification_tag:
        result['warnings'].append(f'Name sanitized from "{identification_tag}" to "{result["sanitized_name"]}"')
    
    # Final validation
    if not result['sanitized_name']:
        result['errors'].append('Sanitized name is empty')
        result['is_valid'] = False
        result['sanitized_name'] = 'ANIMAL'
    
    return result

def get_company_info() -> dict:
    """
    Get company information for labels from settings or defaults.
    """
    compat_mode = get_printer_compatibility_mode()
    return {
        'company_name': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_NAME', "GUNDOGDULAR GIDA"), compat_mode),
        'company_full_name': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_FULL_NAME', "SAN VE TUR. TIC. LTD STI"), compat_mode),
        'company_address': format_turkish_text_for_printer(
            getattr(settings, 'COMPANY_ADDRESS', "BOZALAN - EZINE / ÇANAKKALE"), compat_mode),
        'license_no': getattr(settings, 'LICENSE_NO', '17-0509'),
        'operation_no': getattr(settings, 'OPERATION_NO', '4290056890'),
    }
