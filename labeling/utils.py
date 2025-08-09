from django.apps import apps

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
