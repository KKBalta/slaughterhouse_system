import base64

def extract_bitmap_from_prn(prn_file_path):
    """Extract BITMAP data from PRN file"""
    with open(prn_file_path, 'rb') as f:
        content = f.read()
    
    content_str = content.decode('latin-1')
    bitmap_start = content_str.find('BITMAP 11,1043,98,96,1,')
    
    if bitmap_start != -1:
        bitmap_end = content_str.find('\n', bitmap_start)
        if bitmap_end == -1:
            bitmap_end = len(content_str)
        
        bitmap_line = content_str[bitmap_start:bitmap_end].strip()
        
        # Extract just the data part (after the comma)
        data_part = bitmap_line.split(',', 5)[-1]  # Get everything after the 5th comma
        
        # Convert to base64 for safe storage
        data_bytes = data_part.encode('latin-1')
        data_b64 = base64.b64encode(data_bytes).decode('ascii')
        
        print("="*50)
        print("BITMAP EXTRACTION COMPLETE")
        print("="*50)
        print(f"Full BITMAP line: {bitmap_line}")
        print(f"Base64 encoded data: {data_b64}")
        print("="*50)
        print("Copy this for your utils.py:")
        print("="*50)
        
        # Generate the function code
        function_code = f'''
def get_company_logo_bitmap() -> str:
    """
    Returns the static company logo BITMAP data for TSPL/PRN labels.
    This BITMAP is placed at position 11,1043 with dimensions 98x96.
    """
    import base64
    
    # Base64 encoded bitmap data (extracted from BOS.prn)
    bitmap_data_b64 = "{data_b64}"
    
    # Decode back to original format
    bitmap_bytes = base64.b64decode(bitmap_data_b64)
    bitmap_data = bitmap_bytes.decode('latin-1')
    
    return f"BITMAP 11,1043,98,96,1,{{bitmap_data}}"
'''
        
        print(function_code)
        print("="*50)
        
        return bitmap_line
    
    return None

# Usage - fix the path
bitmap = extract_bitmap_from_prn('BOS.prn')  # Remove the leading slash