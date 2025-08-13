from django import forms
from .models import Animal

class AnimalFilterForm(forms.Form):
    # Status filter
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(Animal.STATUS_CHOICES),
        required=False,
        label="Status",
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md  focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white modern-select-full',
            'id': 'status',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    # Animal type filter
    animal_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(Animal.ANIMAL_TYPES),
        required=False,
        label="Animal Type",
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white modern-select-full',
            'id': 'animal_type',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    # Search field with AJAX functionality
    search = forms.CharField(
        max_length=255,
        required=False,
        label="Search Animals",
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': 'Tag, Order Number, or Animal Type',
            'id': 'animal-search',
            'autocomplete': 'off',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set initial values if provided in GET parameters
        if args and len(args) > 0:
            data = args[0]
            if data:
                self.fields['status'].initial = data.get('status', '')
                self.fields['animal_type'].initial = data.get('animal_type', '')
                self.fields['search'].initial = data.get('search', '')
