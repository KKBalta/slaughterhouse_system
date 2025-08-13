from django import forms
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal

class SlaughterOrderForm(forms.ModelForm):
    # Custom client search field
    client_search = forms.CharField(
        max_length=255,
        required=False,
        label="Search Registered Client",
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': 'Type client name to search...',
            'id': 'client-search',
            'autocomplete': 'off'
        })
    )
    
    # Hidden field to store selected client ID
    client_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'client-id'})
    )
    
    client_name = forms.CharField(
        max_length=255, 
        required=False, 
        label="Walk-in Client Name",
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': 'Enter client name for walk-in customers'
        })
    )
    
    # Phone area code selection
    AREA_CODE_CHOICES = [
        ('+90', '+90'),
        ('+1', '+1'),
    ]
    
    client_phone_area_code = forms.ChoiceField(
        choices=AREA_CODE_CHOICES,
        initial='+90',
        required=False,
        label="Area Code",
        widget=forms.Select(attrs={
            'class': 'modern-select',
            'title': 'Select country code: +90 for Turkey, +1 for USA/Canada'
        })
    )
    
    client_phone = forms.CharField(
        max_length=15, 
        required=False, 
        label="Walk-in Client Phone",
        widget=forms.TextInput(attrs={
            'class': 'flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': 'Enter phone number'
        })
    )

    class Meta:
        model = SlaughterOrder
        fields = ['service_package', 'order_datetime', 'destination']
        widgets = {
            'order_datetime': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white'
            }),
            'destination': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
                'placeholder': 'Enter destination (optional)'
            }),
            'service_package': forms.Select(attrs={
                'class': 'modern-select-full'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_package'].queryset = ServicePackage.objects.all()
        self.fields['service_package'].empty_label = "Select service package"

    def clean(self):
        cleaned_data = super().clean()
        client_id = cleaned_data.get('client_id')
        client_name = cleaned_data.get('client_name')

        if not client_id and not client_name:
            raise forms.ValidationError(
                "An order must be linked to either a registered client or a walk-in client name."
            )
        
        if client_id and client_name:
            raise forms.ValidationError(
                "Please provide either a registered client or a walk-in client, not both."
            )
        
        # Combine area code with phone number
        area_code = cleaned_data.get('client_phone_area_code')
        phone = cleaned_data.get('client_phone')
        if phone and area_code:
            cleaned_data['client_phone'] = f"{area_code}{phone}"
            
        return cleaned_data

class AnimalForm(forms.ModelForm):
    class Meta:
        model = Animal
        fields = ['animal_type', 'identification_tag']
        widgets = {
            'animal_type': forms.Select(attrs={
                'class': 'modern-select-full'
            }),
            'identification_tag': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
                'placeholder': 'Enter identification tag (optional - auto-generated if empty)'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['animal_type'].empty_label = "Select animal type"
        self.fields['identification_tag'].required = False
