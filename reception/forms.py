from django import forms
from .models import SlaughterOrder, ServicePackage
from users.models import ClientProfile

class SlaughterOrderForm(forms.ModelForm):
    class Meta:
        model = SlaughterOrder
        fields = ['client', 'service_package', 'order_date', 'destination']
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate client and service_package choices
        self.fields['client'].queryset = ClientProfile.objects.all()
        self.fields['service_package'].queryset = ServicePackage.objects.all()
