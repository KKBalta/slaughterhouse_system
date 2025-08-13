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

class SlaughterOrderUpdateForm(forms.ModelForm):
    # Client search functionality for updates
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
        
        # Pre-populate client fields if instance exists
        if self.instance and self.instance.pk:
            if self.instance.client:
                self.fields['client_search'].initial = self.instance.client.company_name or self.instance.client.get_full_name()
                self.fields['client_id'].initial = self.instance.client.pk
            else:
                self.fields['client_name'].initial = self.instance.client_name
                # Split phone number if it exists
                if self.instance.client_phone:
                    phone = self.instance.client_phone
                    if phone.startswith('+90'):
                        self.fields['client_phone_area_code'].initial = '+90'
                        self.fields['client_phone'].initial = phone[3:]
                    elif phone.startswith('+1'):
                        self.fields['client_phone_area_code'].initial = '+1'
                        self.fields['client_phone'].initial = phone[2:]
                    else:
                        self.fields['client_phone'].initial = phone

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
        fields = [
            'animal_type', 
            'identification_tag', 
            'received_date',
            'picture', 
            'passport_picture'
        ]
        widgets = {
            'animal_type': forms.Select(attrs={
                'class': 'modern-select-full'
            }),
            'identification_tag': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
                'placeholder': 'Enter identification tag (optional - auto-generated if empty)'
            }),
            'received_date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white'
            }),
            'picture': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100'
            }),
            'passport_picture': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['animal_type'].empty_label = "Select animal type"
        self.fields['identification_tag'].required = False
        
        # Set custom labels
        self.fields['picture'].label = "Animal Photo"
        self.fields['passport_picture'].label = "Passport/Document Photo"
        
        # Make both pictures required during registration
        self.fields['picture'].required = True
        self.fields['passport_picture'].required = True
