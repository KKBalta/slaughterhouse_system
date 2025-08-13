from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from .forms import SlaughterOrderForm, AnimalForm
from .models import SlaughterOrder
from processing.models import Animal
from .services import (
    create_slaughter_order,
    update_slaughter_order,
    cancel_slaughter_order,
    bill_order,
    add_animal_to_order,
    remove_animal_from_order
)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, ListView, DetailView
from django.views.generic.edit import UpdateView
from django.core.exceptions import ValidationError


class CreateSlaughterOrderView(LoginRequiredMixin, View):
    def get(self, request):
        form = SlaughterOrderForm()
        context = {'form': form}
        return render(request, 'reception/create_order.html', context)

    def post(self, request):
        form = SlaughterOrderForm(request.POST)
        if form.is_valid():
            try:
                order = create_slaughter_order(
                    client_id=form.cleaned_data['client'].id if form.cleaned_data.get('client') else None,
                    service_package_id=form.cleaned_data['service_package'].id,
                    order_datetime=form.cleaned_data['order_datetime'],
                    destination=form.cleaned_data['destination'],
                    client_name=form.cleaned_data.get('client_name', ''),
                    client_phone=form.cleaned_data.get('client_phone', ''),
                    animals_data=[]
                )
                messages.success(request, f'Slaughter Order {order.slaughter_order_no} created successfully!')
                return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': order.pk}))
            except Exception as e:
                messages.error(request, f'Error creating order: {e}')
        else:
            messages.error(request, 'Please correct the errors below.')
        
        context = {'form': form}
        return render(request, 'reception/create_order.html', context)


class SlaughterOrderListView(LoginRequiredMixin, ListView):
    model = SlaughterOrder
    template_name = 'reception/order_list.html'
    context_object_name = 'orders'
    paginate_by = 10

    def get_queryset(self):
        return SlaughterOrder.objects.all().order_by('-order_datetime')


class SlaughterOrderDetailView(LoginRequiredMixin, DetailView):
    model = SlaughterOrder
    template_name = 'reception/order_detail.html'
    context_object_name = 'order'


class SlaughterOrderUpdateView(LoginRequiredMixin, UpdateView):
    model = SlaughterOrder
    form_class = SlaughterOrderForm
    template_name = 'reception/update_order.html'
    
    def get_success_url(self):
        return reverse_lazy('reception:slaughter_order_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        try:
            update_data = {
                'service_package': form.cleaned_data['service_package'],
                'destination': form.cleaned_data['destination'],
                'order_datetime': form.cleaned_data['order_datetime'],
            }
            update_slaughter_order(order=self.get_object(), **update_data)
            messages.success(self.request, "Order updated successfully!")
            return super().form_valid(form)
        except ValidationError as e:
            form.add_error(None, e)
            return self.form_invalid(form)


class CancelSlaughterOrderView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(SlaughterOrder, pk=pk)
        try:
            cancel_slaughter_order(order)
            messages.success(request, f"Order {order.slaughter_order_no} has been cancelled.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': pk}))


class BillOrderView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(SlaughterOrder, pk=pk)
        try:
            bill_order(order)
            messages.success(request, f"Order {order.slaughter_order_no} has been marked as billed.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': pk}))


class AddAnimalToOrderView(LoginRequiredMixin, View):
    def get(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = AnimalForm()
        return render(request, 'reception/add_animal.html', {'form': form, 'order': order})

    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = AnimalForm(request.POST)
        if form.is_valid():
            try:
                add_animal_to_order(order=order, animal_data=form.cleaned_data)
                messages.success(request, "Animal added to order successfully.")
                return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': order_pk}))
            except ValidationError as e:
                messages.error(request, str(e))
        
        return render(request, 'reception/add_animal.html', {'form': form, 'order': order})


class EditAnimalInOrderView(LoginRequiredMixin, View):
    def get(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        form = AnimalForm(instance=animal)
        return render(request, 'reception/edit_animal.html', {'form': form, 'order': order, 'animal': animal})

    def post(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        form = AnimalForm(request.POST, instance=animal)
        if form.is_valid():
            try:
                # A service function `update_animal_in_order` would be better.
                form.save()
                messages.success(request, "Animal details updated successfully.")
                return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': order_pk}))
            except ValidationError as e:
                messages.error(request, str(e))
        
        return render(request, 'reception/edit_animal.html', {'form': form, 'order': order, 'animal': animal})


class RemoveAnimalFromOrderView(LoginRequiredMixin, View):
    def post(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        try:
            remove_animal_from_order(order=order, animal=animal)
            messages.success(request, f"Animal {animal.identification_tag} removed from order.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect(reverse('reception:slaughter_order_detail', kwargs={'pk': order_pk}))
