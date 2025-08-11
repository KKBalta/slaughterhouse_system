from django.shortcuts import render, redirect
from django.urls import reverse
from .forms import SlaughterOrderForm
from .services import create_slaughter_order
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View

class CreateSlaughterOrderView(LoginRequiredMixin, View):
    def get(self, request):
        form = SlaughterOrderForm()
        context = {'form': form}
        return render(request, 'reception/create_order.html', context)

    def post(self, request):
        form = SlaughterOrderForm(request.POST)
        if form.is_valid():
            client = form.cleaned_data['client']
            service_package = form.cleaned_data['service_package']
            order_date = form.cleaned_data['order_date']
            destination = form.cleaned_data['destination']

            try:
                order = create_slaughter_order(
                    client_id=client.id,
                    service_package_id=service_package.id,
                    order_date=order_date,
                    animals_data=[],
                    destination=destination
                )
                messages.success(request, f'Slaughter Order {order.slaughter_order_no} created successfully!')
                return redirect(reverse('reception:create_slaughter_order'))
            except Exception as e:
                messages.error(request, f'Error creating order: {e}')
        else:
            messages.error(request, 'Please correct the errors below.')
        
        context = {'form': form}
        return render(request, 'reception/create_order.html', context)
