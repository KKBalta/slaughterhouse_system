from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import DetailView, ListView, View
from django.views.generic.edit import UpdateView

from processing.models import Animal
from users.models import ClientProfile

from .forms import AnimalForm, BatchAnimalForm, SlaughterOrderForm, SlaughterOrderUpdateForm
from .models import SlaughterOrder
from .services import (
    add_animal_to_order,
    bill_order,
    cancel_slaughter_order,
    create_batch_animals,
    create_slaughter_order,
    remove_animal_from_order,
    update_slaughter_order,
)


class ClientSearchView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"clients": []})

        clients = ClientProfile.objects.filter(
            Q(company_name__icontains=query)
            | Q(contact_person__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
        )[:10]  # Limit to 10 results

        client_list = []
        for client in clients:
            if client.account_type == ClientProfile.AccountType.ENTERPRISE:
                display_name = f"{client.company_name}"
                contact_info = client.contact_person or "No contact person"
            else:
                display_name = f"{client.user.get_full_name()}" if client.user else client.contact_person
                contact_info = "Individual"

            client_list.append(
                {
                    "id": str(client.id),
                    "display_name": display_name,
                    "contact_info": contact_info,
                    "phone": client.phone_number,
                }
            )

        return JsonResponse({"clients": client_list})


class CreateSlaughterOrderView(LoginRequiredMixin, View):
    def get(self, request):
        form = SlaughterOrderForm()
        context = {"form": form}
        return render(request, "reception/create_order.html", context)

    def post(self, request):
        form = SlaughterOrderForm(request.POST)
        if form.is_valid():
            try:
                # Get client ID from form if provided
                client_id = form.cleaned_data.get("client_id")
                if client_id:
                    try:
                        client = ClientProfile.objects.get(id=client_id)
                    except ClientProfile.DoesNotExist:
                        client_id = None

                order = create_slaughter_order(
                    client_id=client_id,
                    service_package_id=form.cleaned_data["service_package"].id,
                    order_datetime=form.cleaned_data["order_datetime"],
                    destination=form.cleaned_data["destination"],
                    client_name=form.cleaned_data.get("client_name", ""),
                    client_phone=form.cleaned_data.get("client_phone", ""),
                    animals_data=[],
                )
                messages.success(request, f"Slaughter Order {order.slaughter_order_no} created successfully!")
                return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk}))
            except Exception as e:
                messages.error(request, f"Error creating order: {e}")
        else:
            messages.error(request, "Please correct the errors below.")

        context = {"form": form}
        return render(request, "reception/create_order.html", context)


class SlaughterOrderListView(LoginRequiredMixin, ListView):
    model = SlaughterOrder
    template_name = "reception/order_list.html"
    context_object_name = "orders"
    paginate_by = 10

    def get_queryset(self):
        queryset = SlaughterOrder.objects.select_related("client", "client__user", "service_package").order_by(
            "-order_datetime"
        )

        # Search functionality
        search = self.request.GET.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(slaughter_order_no__icontains=search)
                | Q(client__company_name__icontains=search)
                | Q(client__user__first_name__icontains=search)
                | Q(client__user__last_name__icontains=search)
                | Q(client__contact_person__icontains=search)
                | Q(client_name__icontains=search)
                | Q(destination__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_search"] = self.request.GET.get("search", "")
        return context


class SlaughterOrderDetailView(LoginRequiredMixin, DetailView):
    model = SlaughterOrder
    template_name = "reception/order_detail.html"
    context_object_name = "order"


class SlaughterOrderUpdateView(LoginRequiredMixin, UpdateView):
    model = SlaughterOrder
    form_class = SlaughterOrderUpdateForm
    template_name = "reception/update_order.html"

    def get_success_url(self):
        return reverse_lazy("reception:slaughter_order_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        try:
            # Get client data from form
            client_id = form.cleaned_data.get("client_id")
            client_name = form.cleaned_data.get("client_name", "")
            client_phone = form.cleaned_data.get("client_phone", "")

            # Update client information
            if client_id:
                try:
                    client = ClientProfile.objects.get(id=client_id)
                    self.object.client = client
                    self.object.client_name = ""
                    self.object.client_phone = ""
                except ClientProfile.DoesNotExist:
                    pass
            else:
                self.object.client = None
                self.object.client_name = client_name
                self.object.client_phone = client_phone

            # Update other fields
            update_data = {
                "service_package": form.cleaned_data["service_package"],
                "destination": form.cleaned_data["destination"],
                "order_datetime": form.cleaned_data["order_datetime"],
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
        return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": pk}))


class BillOrderView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(SlaughterOrder, pk=pk)
        try:
            bill_order(order)
            messages.success(request, f"Order {order.slaughter_order_no} has been marked as billed.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": pk}))


class AddAnimalToOrderView(LoginRequiredMixin, View):
    def get(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = AnimalForm()
        return render(request, "reception/add_animal.html", {"form": form, "order": order})

    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = AnimalForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                add_animal_to_order(order=order, animal_data=form.cleaned_data)
                messages.success(request, "Animal added to order successfully.")
                return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": order_pk}))
            except ValidationError as e:
                messages.error(request, str(e))

        return render(request, "reception/add_animal.html", {"form": form, "order": order})


class EditAnimalInOrderView(LoginRequiredMixin, View):
    def get(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        form = AnimalForm(instance=animal)
        return render(request, "reception/edit_animal.html", {"form": form, "order": order, "animal": animal})

    def post(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        form = AnimalForm(request.POST, request.FILES, instance=animal)
        if form.is_valid():
            try:
                # A service function `update_animal_in_order` would be better.
                form.save()
                messages.success(request, "Animal details updated successfully.")
                return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": order_pk}))
            except ValidationError as e:
                messages.error(request, str(e))

        return render(request, "reception/edit_animal.html", {"form": form, "order": order, "animal": animal})


class RemoveAnimalFromOrderView(LoginRequiredMixin, View):
    def post(self, request, order_pk, animal_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        animal = get_object_or_404(Animal, pk=animal_pk)
        try:
            remove_animal_from_order(order=order, animal=animal)
            messages.success(request, f"Animal {animal.identification_tag} removed from order.")
        except ValidationError as e:
            messages.error(request, str(e))
        return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": order_pk}))


class BatchAddAnimalsToOrderView(LoginRequiredMixin, View):
    def get(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = BatchAnimalForm()
        return render(request, "reception/batch_add_animals.html", {"form": form, "order": order})

    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        form = BatchAnimalForm(request.POST)

        if form.is_valid():
            try:
                animal_type = form.cleaned_data["animal_type"]
                quantity = form.cleaned_data["quantity"]
                tag_prefix = form.cleaned_data.get("tag_prefix")
                received_date = form.cleaned_data.get("received_date")
                skip_photos = form.cleaned_data.get("skip_photos", False)

                created_animals = create_batch_animals(
                    order=order,
                    animal_type=animal_type,
                    quantity=quantity,
                    tag_prefix=tag_prefix,
                    received_date=received_date,
                    skip_photos=skip_photos,
                )

                messages.success(
                    request,
                    f"Successfully created {len(created_animals)} {animal_type} animals for order {order.slaughter_order_no}.",
                )
                return redirect(reverse("reception:slaughter_order_detail", kwargs={"pk": order_pk}))

            except ValidationError as e:
                messages.error(request, str(e))

        return render(request, "reception/batch_add_animals.html", {"form": form, "order": order})


def search_clients(request):
    if "term" in request.GET:
        term = request.GET["term"]
        clients = ClientProfile.objects.filter(Q(user__username__icontains=term) | Q(phone_number__icontains=term))[:10]
        results = [{"id": client.pk, "text": client.user.username} for client in clients]
        return JsonResponse(results, safe=False)
    return JsonResponse([], safe=False)
