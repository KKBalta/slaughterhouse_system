from django import forms
from django.utils.translation import gettext_lazy as _
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal

class SlaughterOrderForm(forms.ModelForm):
    # Custom client search field
    client_search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Search Registered Client"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Type client name to search...'),
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
        label=_("Walk-in Client Name"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Enter client name for walk-in customers')
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
        label=_("Area Code"),
        widget=forms.Select(attrs={
            'class': 'modern-select',
            'title': _('Select country code: +90 for Turkey, +1 for USA/Canada')
        })
    )
    
    client_phone = forms.CharField(
        max_length=15, 
        required=False, 
        label=_("Walk-in Client Phone"),
        widget=forms.TextInput(attrs={
            'class': 'flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Enter phone number')
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
                'placeholder': _('Enter destination (optional)')
            }),
            'service_package': forms.Select(attrs={
                'class': 'modern-select-full'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_package'].queryset = ServicePackage.objects.all()
        self.fields['service_package'].empty_label = _("Select service package")

    def clean(self):
        cleaned_data = super().clean()
        client_id = cleaned_data.get('client_id')
        client_name = cleaned_data.get('client_name')

        if not client_id and not client_name:
            raise forms.ValidationError(
                _("An order must be linked to either a registered client or a walk-in client name.")
            )
        
        if client_id and client_name:
            raise forms.ValidationError(
                _("Please provide either a registered client or a walk-in client, not both.")
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
        label=_("Search Registered Client"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Type client name to search...'),
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
        label=_("Walk-in Client Name"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Enter client name for walk-in customers')
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
        label=_("Area Code"),
        widget=forms.Select(attrs={
            'class': 'modern-select',
            'title': _('Select country code: +90 for Turkey, +1 for USA/Canada')
        })
    )
    
    client_phone = forms.CharField(
        max_length=15, 
        required=False, 
        label=_("Walk-in Client Phone"),
        widget=forms.TextInput(attrs={
            'class': 'flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Enter phone number')
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
                'placeholder': _('Enter destination (optional)')
            }),
            'service_package': forms.Select(attrs={
                'class': 'modern-select-full'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_package'].queryset = ServicePackage.objects.all()
        self.fields['service_package'].empty_label = _("Select service package")
        
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
                _("An order must be linked to either a registered client or a walk-in client name.")
            )
        
        if client_id and client_name:
            raise forms.ValidationError(
                _("Please provide either a registered client or a walk-in client, not both.")
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
                'placeholder': _('Enter identification tag (optional - auto-generated if empty)')
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
        # Extract skip_photos parameter if provided
        self.skip_photos = kwargs.pop('skip_photos', False)
        super().__init__(*args, **kwargs)
        self.fields['animal_type'].empty_label = _("Select animal type")
        self.fields['identification_tag'].required = False
        
        # Set custom labels
        self.fields['picture'].label = _("Animal Photo (Optional)")
        self.fields['passport_picture'].label = _("Passport/Document Photo (Optional)")
        
        # Make photos optional for both individual and batch creation
        self.fields['picture'].required = False
        self.fields['passport_picture'].required = False

class BatchAnimalForm(forms.Form):
    """Form for creating multiple animals at once with automatic tag generation"""
    
    animal_type = forms.ChoiceField(
        choices=Animal.ANIMAL_TYPES,
        label=_("Animal Type"),
        widget=forms.Select(attrs={
            'class': 'modern-select-full'
        })
    )
    
    quantity = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=1,
        label=_("Number of Animals"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Enter number of animals (1-100)')
        })
    )
    
    tag_prefix = forms.CharField(
        max_length=20,
        required=False,
        label=_("Tag Prefix (Optional)"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('e.g., BATCH-001 (leave empty for auto-generation)')
        }),
        help_text=_("Custom prefix for identification tags. If empty, auto-generated tags will be used.")
    )
    
    received_date = forms.DateTimeField(
        required=False,
        label=_("Received Date & Time"),
        widget=forms.DateTimeInput(attrs={
            'type': 'datetime-local',
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white'
        }),
        help_text=_("Leave empty to use current date/time for all animals")
    )
    
    skip_photos = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Skip Photos for Batch"),
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded'
        }),
        help_text=_("Check this to create animals without photos (photos can be added later)")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['animal_type'].empty_label = _("Select animal type")

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity and quantity > 100:
            raise forms.ValidationError(_("Maximum 100 animals can be created in a single batch."))
        return quantity