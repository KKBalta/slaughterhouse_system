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
        if hasattr(item, 'weight'):
            label_data['weight'] = str(item.weight)

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
    
    # Calculate STT (Son Tutetim Tarihi) - slaughter date + 10 days
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
        'cattle': 'Sigir',
        'sheep': 'Koyun',
        'goat': 'Keci',
        'lamb': 'Kuzu',
        'oglak': 'Oglak',
        'calf': 'Dana',
        'heifer': 'Duve',
        'beef': 'Sigir',
    }
    cinsi = animal_type_mapping.get(animal.animal_type, animal.animal_type.title())
    
    # Get kupe number (identification tag)
    kupe_no = animal.identification_tag or "Bilinmiyor"
    
    # Get trader (destination address from slaughter order)
    tuccar = order.destination or ""
    
    return {
        'uretici': uretici,
        'kupe_no': kupe_no,
        'tuccar': tuccar,
        'kesim_tarihi': kesim_tarihi,
        'stt': stt,
        'siparis_no': siparis_no,
        'cinsi': cinsi,
        'isletme_onay_no': '17-0509',  # Fixed approval number
    }

def generate_zpl_label(animal, label_type='hot_carcass') -> str:
    """
    Generate ZPL code for animal label based on the Turkish hot carcass format.
    """
    label_data = generate_animal_label_data(animal)
    
    # ZPL template for hot carcass label (Turkish labels)
    zpl_template = """^XA
^PW203
^LL2240
^LH0,0

^CF0,30

^FO20,50^A0R,40,40^FDETIKET URETICI: {uretici}^FS
^FO150,50^A0R,40,40^FDKUP NO: {kupe_no}^FS
^FO80,50^A0R,40,40^FDTUCCAR ADI: {tuccar}^FS

^FO10,900^A0R,40,40^FDKESIM TARIHI: {kesim_tarihi}^FS
^FO80,900^A0R,40,40^FDSTT: {stt}^FS
^FO150,900^A0R,40,40^FDSIPARIS NO: {siparis_no}^FS
^FO80,1500^A0R,40,40^FDCINSI: {cinsi}^FS
^FO10,1500^A0R,30,30^FDISLETME ONAY NO: {isletme_onay_no}^FS

^FO15,2000^BQN,2,6
^FDLA,{kupe_no}|{siparis_no}|{kesim_tarihi}|{stt}^FS

^XZ"""
    
    return zpl_template.format(**label_data)

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
    qr_data = f"{label_data['kupe_no']}|{label_data['siparis_no']}|{label_data['kesim_tarihi']}|{label_data['stt']}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    # Create QR code image and save to temporary file
    qr_img = qr.make_image(fill_color="black", back_color="white")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
        qr_img.save(tmp_file.name, format='PNG')
        # Add QR code to PDF
        c.drawImage(tmp_file.name, 50, y_position - 100, width=100, height=100)
        # Clean up temporary file
        import os
        os.unlink(tmp_file.name)
    
    # Save PDF
    c.save()
    buffer.seek(0)
    
    return buffer

def create_animal_label(animal, label_type='hot_carcass', user=None):
    """
    Create an AnimalLabel instance with generated ZPL and PDF content.
    """
    from .models import AnimalLabel
    
    # Generate ZPL content
    zpl_content = generate_zpl_label(animal, label_type)
    
    # Generate PDF content
    pdf_buffer = generate_pdf_label(animal, label_type)
    
    # Create AnimalLabel instance
    animal_label = AnimalLabel(
        animal=animal,
        label_type=label_type,
        printed_by=user,
        zpl_content=zpl_content
    )
    
    # Save to get the ID
    animal_label.save()
    
    # Save PDF file
    from django.core.files.base import ContentFile
    pdf_filename = f"animal_label_{animal.identification_tag}_{label_type}_{animal_label.id}.pdf"
    animal_label.pdf_file.save(pdf_filename, ContentFile(pdf_buffer.getvalue()), save=True)
    
    return animal_label

def get_animal_label_download_data(animal_label, format_type='zpl'):
    """
    Get download data for animal label in specified format.
    """
    if format_type.lower() == 'zpl':
        return {
            'content': animal_label.zpl_content,
            'filename': f"animal_label_{animal_label.animal.identification_tag}_{animal_label.label_type}.zpl",
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
