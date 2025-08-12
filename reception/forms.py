from django import forms
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile
from processing.models import Animal

class SlaughterOrderForm(forms.ModelForm):
    client_name = forms.CharField(max_length=255, required=False, label="Walk-in Client Name")
    client_phone = forms.CharField(max_length=20, required=False, label="Walk-in Client Phone")

    class Meta:
        model = SlaughterOrder
        fields = ['client', 'client_name', 'client_phone', 'service_package', 'order_date', 'destination']
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = ClientProfile.objects.all()
        self.fields['client'].required = False
        self.fields['service_package'].queryset = ServicePackage.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get('client')
        client_name = cleaned_data.get('client_name')

        if not client and not client_name:
            raise forms.ValidationError(
                "An order must be linked to either a registered client or a walk-in client name."
            )
        
        if client and client_name:
            raise forms.ValidationError(
                "Please provide either a registered client or a walk-in client, not both."
            )
        return cleaned_data

class AnimalForm(forms.ModelForm):
    class Meta:
        model = Animal
        fields = ['animal_type', 'identification_tag']
