from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import DetailView, ListView, TemplateView, View

from reception.models import SlaughterOrder

from . import services
from .forms import (
    ANIMAL_DETAIL_FORMS,
    AnimalFilterForm,
    BatchWeightLogForm,
    DisassemblyCutForm,
    LeatherWeightForm,
    ScaleReceiptUploadForm,
    WeightLogForm,
)
from .models import Animal, DisassemblyCut, WeightLog
from .services import (
    ANIMAL_DETAIL_MODELS,
    log_group_weight,
    log_individual_weight,
    log_leather_weight,
    mark_animal_slaughtered,
)


class ProcessingDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "processing/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get counts by status
        status_counts = Animal.objects.values("status").annotate(count=Count("id"))
        status_dict = {item["status"]: item["count"] for item in status_counts}

        # Recent orders with animals ready for processing
        recent_orders = (
            SlaughterOrder.objects.filter(animals__status__in=["received", "slaughtered", "carcass_ready"])
            .distinct()
            .order_by("-order_datetime")[:10]
        )

        # Animals by status for quick actions
        received_animals = Animal.objects.filter(status="received").order_by("received_date")[:10]
        slaughtered_animals = Animal.objects.filter(status="slaughtered").order_by("-slaughter_date")[:10]

        # Orders ready for batch slaughter
        orders_ready_for_slaughter = (
            SlaughterOrder.objects.filter(animals__status="received")
            .annotate(received_count=Count("animals", filter=Q(animals__status="received")))
            .filter(received_count__gt=0)
            .order_by("-order_datetime")[:10]
        )

        # Orders ready for weight logging (animals in 'slaughtered' status or mixed statuses)
        # Filter out orders where weighing is complete
        orders_ready_for_weighing_initial = (
            SlaughterOrder.objects.filter(animals__status__in=["slaughtered", "carcass_ready"])
            .annotate(
                total_animals=Count("animals"),
                slaughtered_count=Count("animals", filter=Q(animals__status="slaughtered")),
                carcass_ready_count=Count("animals", filter=Q(animals__status="carcass_ready")),
            )
            .filter(
                # Only include orders with animals needing weight logging
                Q(slaughtered_count__gt=0) | Q(carcass_ready_count__gt=0)
            )
            .order_by("-order_datetime")
        )

        # Filter out orders where all weighing is complete
        orders_ready_for_weighing = []
        for order in orders_ready_for_weighing_initial[:20]:  # Check more orders initially
            # Calculate if weighing is complete by checking if all animals have hot carcass weight
            animals_needing_weight = order.animals.filter(status__in=["slaughtered", "carcass_ready"])

            # Check if all animals have either individual hot carcass weight logs OR are covered by batch logs
            animals_with_individual_weights = (
                animals_needing_weight.filter(individual_weight_logs__weight_type="hot_carcass_weight")
                .distinct()
                .count()
            )

            batch_logs = WeightLog.objects.filter(
                slaughter_order=order, weight_type="hot_carcass_weight Group", is_group_weight=True
            )
            batch_covered_count = sum(log.group_quantity for log in batch_logs)

            # If we have individual logs, use that count; otherwise use batch count
            weighed_count = (
                animals_with_individual_weights if animals_with_individual_weights > 0 else batch_covered_count
            )

            # Only include orders where weighing is NOT complete
            if weighed_count < animals_needing_weight.count():
                orders_ready_for_weighing.append(order)
                if len(orders_ready_for_weighing) >= 10:  # Limit to 10 orders
                    break

        # Calculate additional weight progress data for each order
        for order in orders_ready_for_weighing:
            # Add annotation fields that were lost due to filtering
            order.total_animals = order.animals.count()
            order.slaughtered_count = order.animals.filter(status="slaughtered").count()
            order.carcass_ready_count = order.animals.filter(status="carcass_ready").count()

            # Calculate accurate weight counts considering both individual and batch weights

            # Live weight count: Count unique animals that have EITHER individual logs OR are covered by batch logs
            live_individual_animals = set(
                order.animals.filter(individual_weight_logs__weight_type="live_weight").values_list("id", flat=True)
            )
            live_batch_logs = WeightLog.objects.filter(
                slaughter_order=order, weight_type="live_weight Group", is_group_weight=True
            )
            live_batch_count = sum(log.group_quantity for log in live_batch_logs)
            # For batch logs, we count the total quantity since we don't know which specific animals
            # But if individual logs exist, we prioritize the actual count
            if live_individual_animals:
                order.live_weight_count = len(live_individual_animals)
            else:
                order.live_weight_count = live_batch_count

            # Hot carcass weight count: Count unique animals that have EITHER individual logs OR are covered by batch logs
            hot_individual_animals = set(
                order.animals.filter(individual_weight_logs__weight_type="hot_carcass_weight").values_list(
                    "id", flat=True
                )
            )
            hot_batch_logs = WeightLog.objects.filter(
                slaughter_order=order, weight_type="hot_carcass_weight Group", is_group_weight=True
            )
            hot_batch_count = sum(log.group_quantity for log in hot_batch_logs)
            if hot_individual_animals:
                order.hot_carcass_count = len(hot_individual_animals)
            else:
                order.hot_carcass_count = hot_batch_count

            # Cold carcass weight count: Count unique animals that have EITHER individual logs OR are covered by batch logs
            cold_individual_animals = set(
                order.animals.filter(individual_weight_logs__weight_type="cold_carcass_weight").values_list(
                    "id", flat=True
                )
            )
            cold_batch_logs = WeightLog.objects.filter(
                slaughter_order=order, weight_type="cold_carcass_weight Group", is_group_weight=True
            )
            cold_batch_count = sum(log.group_quantity for log in cold_batch_logs)
            if cold_individual_animals:
                order.cold_carcass_count = len(cold_individual_animals)
            else:
                order.cold_carcass_count = cold_batch_count

            # Calculate weight completion percentage (use hot carcass count)
            order.weighed_count = order.hot_carcass_count
            if order.total_animals > 0:
                order.weight_progress_percentage = (order.weighed_count / order.total_animals) * 100
            else:
                order.weight_progress_percentage = 0

            # Calculate time since slaughter for urgency
            if order.slaughtered_count > 0:
                latest_slaughter = (
                    order.animals.filter(status__in=["slaughtered", "carcass_ready"], slaughter_date__isnull=False)
                    .order_by("-slaughter_date")
                    .first()
                )

                if latest_slaughter and latest_slaughter.slaughter_date:
                    time_diff = timezone.now() - latest_slaughter.slaughter_date
                    hours = int(time_diff.total_seconds() / 3600)
                    if hours < 24:
                        order.time_since_slaughter = f"{hours}h"
                    else:
                        days = int(hours / 24)
                        order.time_since_slaughter = f"{days}d"
                else:
                    order.time_since_slaughter = None
            else:
                order.time_since_slaughter = None

        context.update(
            {
                "status_counts": status_dict,
                "recent_orders": recent_orders,
                "received_animals": received_animals,
                "slaughtered_animals": slaughtered_animals,
                "orders_ready_for_slaughter": orders_ready_for_slaughter,
                "orders_ready_for_weighing": orders_ready_for_weighing,
                "total_animals_today": Animal.objects.filter(received_date__date=timezone.now().date()).count(),
                # Add count variables for blocktrans template tags
                "orders_ready_for_slaughter_count": len(orders_ready_for_slaughter),
                "orders_ready_for_weighing_count": len(orders_ready_for_weighing),
                "received_animals_count": received_animals.count(),
            }
        )

        return context


class AnimalListView(LoginRequiredMixin, ListView):
    model = Animal
    template_name = "processing/animal_list.html"
    context_object_name = "animals"
    paginate_by = 50

    def get_paginate_by(self, queryset):
        """Allow configurable page size via URL parameter"""
        page_size = self.request.GET.get("page_size", self.paginate_by)
        try:
            page_size = int(page_size)
            # Limit page size to reasonable bounds
            if page_size < 10:
                page_size = 10
            elif page_size > 200:
                page_size = 200
            return page_size
        except (ValueError, TypeError):
            return self.paginate_by

    def get_queryset(self):
        queryset = (
            Animal.objects.select_related("slaughter_order", "slaughter_order__client", "slaughter_order__client__user")
            .prefetch_related(
                "cattle_details",
                "sheep_details",
                "goat_details",
                "lamb_details",
                "oglak_details",
                "calf_details",
                "heifer_details",
                "individual_weight_logs",
            )
            .order_by("-received_date")
        )

        # Filter by status if provided
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)

        # Filter by animal type if provided
        animal_type = self.request.GET.get("animal_type")
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)

        # Enhanced search by identification tag, order number, and client name
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(identification_tag__icontains=search)
                | Q(slaughter_order__slaughter_order_no__icontains=search)
                | Q(slaughter_order__client__company_name__icontains=search)
                | Q(slaughter_order__client__user__first_name__icontains=search)
                | Q(slaughter_order__client__user__last_name__icontains=search)
                | Q(slaughter_order__client__contact_person__icontains=search)
                | Q(slaughter_order__client_name__icontains=search)  # For walk-in clients
                | Q(animal_type__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Initialize form with GET parameters
        form = AnimalFilterForm(self.request.GET)
        context["form"] = form

        # Add alert information for each animal
        animals_with_alerts = []
        for animal in context["animals"]:
            alert_info = {
                "animal": animal,
                "missing_details": False,
                "missing_leather_weight": False,
                "missing_hot_carcass_weight": False,
            }

            # Check for missing details based on animal type - only for animals with appropriate status
            allowed_statuses = [
                "slaughtered",
                "carcass_ready",
                "disassembled",
                "packaged",
                "delivered",
                "returned",
                "disposed",
            ]
            if animal.status in allowed_statuses:
                detail_model_mapping = {
                    "cattle": "cattle_details",
                    "sheep": "sheep_details",
                    "goat": "goat_details",
                    "lamb": "lamb_details",
                    "oglak": "oglak_details",
                    "calf": "calf_details",
                    "heifer": "heifer_details",
                }

                detail_attr = detail_model_mapping.get(animal.animal_type)
                if detail_attr:
                    # Check if related detail objects exist
                    # For OneToOneField, we use hasattr to check if the related object exists
                    if hasattr(animal, detail_attr):
                        try:
                            related_object = getattr(animal, detail_attr)
                            # If we get the object without exception, it exists
                            alert_info["missing_details"] = False
                        except Exception:
                            # If there's any exception accessing it, it doesn't exist
                            alert_info["missing_details"] = True
                    else:
                        # If the attribute itself doesn't exist
                        alert_info["missing_details"] = True

            # Check for missing leather weight
            if (
                animal.status != "received"
                and not animal.leather_weight_kg
                and animal.animal_type not in ["lamb", "sheep", "oglak", "goat"]
            ):
                alert_info["missing_leather_weight"] = True

            # Check for missing hot carcass weight
            if animal.status in ["slaughtered", "carcass_ready", "disassembled", "packaged", "delivered"]:
                has_hot_carcass = animal.individual_weight_logs.filter(weight_type="hot_carcass_weight").exists()
                if not has_hot_carcass:
                    alert_info["missing_hot_carcass_weight"] = True

            animals_with_alerts.append(alert_info)

        context["animals_with_alerts"] = animals_with_alerts

        # Keep the old context for backward compatibility
        context["status_choices"] = Animal.STATUS_CHOICES
        context["animal_type_choices"] = Animal.ANIMAL_TYPES
        context["current_status"] = self.request.GET.get("status", "")
        context["current_animal_type"] = self.request.GET.get("animal_type", "")
        context["current_search"] = self.request.GET.get("search", "")

        # Add pagination context
        context["current_page_size"] = self.get_paginate_by(self.get_queryset())
        context["available_page_sizes"] = [25, 50, 100, 200]

        # Add filter status
        context["has_filters"] = bool(
            self.request.GET.get("status") or self.request.GET.get("animal_type") or self.request.GET.get("search")
        )

        return context


class AnimalDetailView(LoginRequiredMixin, DetailView):
    model = Animal
    template_name = "processing/animal_detail.html"
    context_object_name = "animal"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if "delete_scale_receipt" in request.POST:
            # Delete the scale receipt image
            if self.object.scale_receipt_picture:
                self.object.scale_receipt_picture.delete(save=True)
                self.object.scale_receipt_picture = None
                self.object.save()
                messages.success(request, _("Scale receipt image deleted."))
            else:
                messages.error(request, _("No scale receipt image to delete."))
        else:
            form = ScaleReceiptUploadForm(request.POST, request.FILES, instance=self.object)
            if form.is_valid():
                form.save()
                messages.success(request, _("Scale receipt image uploaded successfully."))
            else:
                messages.error(request, _("Failed to upload scale receipt image."))
        return redirect("processing:animal_detail", pk=self.object.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["weight_logs"] = self.object.individual_weight_logs.order_by("-log_date")
        context["weight_form"] = WeightLogForm(animal=self.object)
        context["leather_form"] = LeatherWeightForm(instance=self.object)
        context["scale_receipt_form"] = ScaleReceiptUploadForm(instance=self.object)

        # Check for missing hot carcass weight for slaughtered animals
        if self.object.status in ["slaughtered", "carcass_ready", "disassembled", "packaged", "delivered"]:
            hot_carcass_logged = self.object.individual_weight_logs.filter(weight_type="hot_carcass_weight").exists()
            context["missing_hot_carcass_weight"] = not hot_carcass_logged
        else:
            context["missing_hot_carcass_weight"] = False

        # Add animal detail form based on animal type - only if animal is slaughtered or beyond
        animal_type = self.object.animal_type
        form_class = ANIMAL_DETAIL_FORMS.get(animal_type)
        detail_model = ANIMAL_DETAIL_MODELS.get(animal_type)

        # Check if animal status allows details to be filled
        allowed_statuses = [
            "slaughtered",
            "carcass_ready",
            "disassembled",
            "packaged",
            "delivered",
            "returned",
            "disposed",
        ]
        context["can_fill_details"] = self.object.status in allowed_statuses

        if form_class and detail_model and context["can_fill_details"]:
            try:
                # Try to get existing details
                detail_instance = detail_model.objects.get(animal=self.object)
                context["detail_form"] = form_class(instance=detail_instance)
                context["has_details"] = True
            except detail_model.DoesNotExist:
                # Create new form for creating details
                context["detail_form"] = form_class()
                context["has_details"] = False

            context["detail_form_title"] = _("%(animal_type)s Details") % {
                "animal_type": self.object.get_animal_type_display()
            }
        elif form_class and detail_model:
            # Animal exists but status doesn't allow details yet
            context["detail_form_title"] = _("%(animal_type)s Details") % {
                "animal_type": self.object.get_animal_type_display()
            }
            context["has_details"] = False
            try:
                detail_instance = detail_model.objects.get(animal=self.object)
                context["existing_details"] = detail_instance
            except detail_model.DoesNotExist:
                context["existing_details"] = None

        # Add disassembly readiness check
        context["can_proceed_to_disassembly"] = self.object.can_proceed_to_disassembly()

        # Scale sessions linked to this animal (FK scale_sessions + M2M disassembly_session_animals)
        from scales.models import DisassemblySession
        from scales.utils import get_session_per_animal_summary

        session_ids_fk = set(DisassemblySession.objects.filter(animal=self.object).values_list("id", flat=True))
        session_ids_m2m = set(DisassemblySession.objects.filter(animals=self.object).values_list("id", flat=True))
        all_session_ids = session_ids_fk | session_ids_m2m
        scale_sessions_with_allocation = []
        for sid in all_session_ids:
            try:
                session = (
                    DisassemblySession.objects.select_related("device", "site").prefetch_related("animals").get(pk=sid)
                )
            except DisassemblySession.DoesNotExist:
                continue
            summary = get_session_per_animal_summary(session)
            for row in summary:
                if row["animal"].id == self.object.id:
                    scale_sessions_with_allocation.append(
                        {
                            "session": session,
                            "total_allocated_grams": row["total_allocated_grams"],
                            "average_grams": row["average_grams"],
                            "effective_event_count": row["effective_event_count"],
                        }
                    )
                    break
        scale_sessions_with_allocation.sort(key=lambda x: x["session"].started_at, reverse=True)
        context["scale_sessions_with_allocation"] = scale_sessions_with_allocation

        return context


class MarkAnimalSlaughteredView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)

        try:
            mark_animal_slaughtered(animal)
            messages.success(request, _("Animal %(tag)s marked as slaughtered.") % {"tag": animal.identification_tag})
        except Exception as e:
            messages.error(request, _("Error marking animal as slaughtered: %(error)s") % {"error": str(e)})

        return redirect("processing:animal_detail", pk=animal.pk)


class AnimalWeightLogView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        form = WeightLogForm(request.POST, animal=animal)

        if form.is_valid():
            weight_type = form.cleaned_data["weight_type"]
            weight = form.cleaned_data["weight"]

            try:
                if weight_type == "leather_weight":
                    # Handle leather weight specially
                    log_leather_weight(animal, weight)
                    messages.success(
                        request,
                        _("Leather weight (%(weight)s kg) logged for %(tag)s.")
                        % {"weight": weight, "tag": animal.identification_tag},
                    )
                else:
                    # Check if this weight type already exists
                    existing_log = WeightLog.objects.filter(animal=animal, weight_type=weight_type).first()

                    # Handle regular weight logging
                    log_individual_weight(animal, weight_type, weight)

                    if existing_log:
                        messages.success(
                            request,
                            _("%(weight_type)s updated to %(weight)s kg for %(tag)s.")
                            % {
                                "weight_type": weight_type.replace("_", " ").title(),
                                "weight": weight,
                                "tag": animal.identification_tag,
                            },
                        )
                    else:
                        messages.success(
                            request,
                            _("%(weight_type)s (%(weight)s kg) logged for %(tag)s.")
                            % {
                                "weight_type": weight_type.replace("_", " ").title(),
                                "weight": weight,
                                "tag": animal.identification_tag,
                            },
                        )
            except Exception as e:
                messages.error(request, _("Error logging weight: %(error)s") % {"error": str(e)})
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

        return redirect("processing:animal_detail", pk=animal.pk)


class BatchSlaughterView(LoginRequiredMixin, TemplateView):
    template_name = "processing/batch_slaughter.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get orders with animals ready for slaughter
        orders = (
            SlaughterOrder.objects.filter(animals__status="received")
            .annotate(received_count=Count("animals", filter=Q(animals__status="received")))
            .filter(received_count__gt=0)
            .order_by("-order_datetime")
        )

        context["orders"] = orders
        return context

    def post(self, request):
        order_id = request.POST.get("order_id")
        if not order_id:
            messages.error(request, _("Please select an order."))
            return redirect("processing:batch_slaughter")

        order = get_object_or_404(SlaughterOrder, pk=order_id)
        animals_to_slaughter = order.animals.filter(status="received")

        success_count = 0
        error_count = 0

        for animal in animals_to_slaughter:
            try:
                mark_animal_slaughtered(animal)
                success_count += 1
            except Exception as e:
                error_count += 1

        if success_count > 0:
            messages.success(request, _("Successfully slaughtered %(count)s animals.") % {"count": success_count})
        if error_count > 0:
            messages.warning(request, _("%(count)s animals could not be processed.") % {"count": error_count})

        return redirect("processing:batch_slaughter")


class BatchWeightLogView(LoginRequiredMixin, TemplateView):
    template_name = "processing/batch_weights.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get the pre-selected order from URL parameter
        selected_order_id = self.request.GET.get("order")
        selected_order = None
        if selected_order_id:
            try:
                selected_order = SlaughterOrder.objects.get(pk=selected_order_id)
            except SlaughterOrder.DoesNotExist:
                selected_order = None

        # Get orders with animals ready for weight logging (any status that allows weight logging)
        # Filter to only show orders from the last week
        one_week_ago = timezone.now() - timedelta(days=7)
        relevant_statuses = ["received", "slaughtered", "carcass_ready", "disassembled", "packaged", "delivered"]
        orders = (
            SlaughterOrder.objects.filter(animals__status__in=relevant_statuses, order_datetime__gte=one_week_ago)
            .annotate(
                received_count=Count("animals", filter=Q(animals__status="received")),
                slaughtered_count=Count("animals", filter=Q(animals__status="slaughtered")),
                carcass_ready_count=Count("animals", filter=Q(animals__status="carcass_ready")),
                disassembled_count=Count("animals", filter=Q(animals__status="disassembled")),
                packaged_count=Count("animals", filter=Q(animals__status="packaged")),
                delivered_count=Count("animals", filter=Q(animals__status="delivered")),
            )
            .filter(
                Q(received_count__gt=0)
                | Q(slaughtered_count__gt=0)
                | Q(carcass_ready_count__gt=0)
                | Q(disassembled_count__gt=0)
                | Q(packaged_count__gt=0)
                | Q(delivered_count__gt=0)
            )
            .order_by("-order_datetime")
        )

        # Add batch weight progress information for each order
        orders_with_progress = []
        for order in orders:
            # Calculate progress for each weight type
            weight_progress = {}
            weight_types = ["live_weight", "hot_carcass_weight", "cold_carcass_weight", "final_weight"]

            for weight_type in weight_types:
                group_weight_type = f"{weight_type} Group"
                existing_logs = WeightLog.objects.filter(
                    slaughter_order=order, weight_type=group_weight_type, is_group_weight=True
                ).order_by("-log_date")

                # Calculate progress - use correct count based on weight type and status rules
                total_weighed = sum(log.group_quantity for log in existing_logs)

                # Weight type rules based on animal status:
                if weight_type == "live_weight":
                    # Live weight: Can be logged for ANY status (including received animals)
                    available_count = order.animals.filter(status__in=relevant_statuses).count()
                elif weight_type == "hot_carcass_weight":
                    # Hot carcass weight: Only for slaughtered/carcass_ready animals
                    available_count = order.animals.filter(
                        status__in=["slaughtered", "carcass_ready", "disassembled", "packaged", "delivered"]
                    ).count()
                elif weight_type == "cold_carcass_weight":
                    # Cold carcass weight: Only for carcass_ready+ animals
                    available_count = order.animals.filter(
                        status__in=["carcass_ready", "disassembled", "packaged", "delivered"]
                    ).count()
                elif weight_type == "final_weight":
                    # Final weight: Only for disassembled+ animals
                    available_count = order.animals.filter(status__in=["disassembled", "packaged", "delivered"]).count()
                else:
                    # Default fallback
                    available_count = order.animals.filter(status__in=relevant_statuses).count()

                remaining = available_count - total_weighed

                # Check if individual weights were auto-generated (completion)
                individual_logs_exist = WeightLog.objects.filter(
                    animal__slaughter_order=order, weight_type=weight_type, is_group_weight=False
                ).exists()

                weight_progress[weight_type] = {
                    "total_weighed": total_weighed,
                    "remaining": max(0, remaining),
                    "logs_count": existing_logs.count(),
                    "completed": individual_logs_exist or total_weighed >= available_count,
                    "latest_log": existing_logs.first(),
                    "available_count": available_count,  # Add this for debugging
                }

            orders_with_progress.append(
                {
                    "order": order,
                    "weight_progress": weight_progress,
                    "total_animal_count": (
                        order.received_count
                        + order.slaughtered_count
                        + order.carcass_ready_count
                        + order.disassembled_count
                        + order.packaged_count
                        + order.delivered_count
                    ),
                }
            )

        context["orders_with_progress"] = orders_with_progress
        context["form"] = BatchWeightLogForm()

        # Add recent batch weight logs for reference
        recent_logs = (
            WeightLog.objects.filter(is_group_weight=True).select_related("slaughter_order").order_by("-log_date")[:10]
        )
        context["recent_logs"] = recent_logs

        # Add selected order information
        context["selected_order"] = selected_order
        context["selected_order_id"] = selected_order_id

        return context

    def post(self, request):
        form = BatchWeightLogForm(request.POST)

        if form.is_valid():
            try:
                order_id = form.cleaned_data["order_id"]
                weight_type = form.cleaned_data["weight_type"]
                total_weight = form.cleaned_data["total_weight"]
                animal_count = form.cleaned_data["animal_count"]

                order = get_object_or_404(SlaughterOrder, pk=order_id)

                # Calculate average weight per animal
                average_weight = total_weight / animal_count

                # Create proper weight type for group weights
                group_weight_type = f"{weight_type} Group"

                # Check current progress before logging
                existing_logs = WeightLog.objects.filter(
                    slaughter_order=order, weight_type=group_weight_type, is_group_weight=True
                )
                current_total = sum(log.group_quantity for log in existing_logs)

                # Call service with correct parameters
                weight_log = log_group_weight(
                    slaughter_order=order,
                    weight=average_weight,  # Average weight per animal
                    weight_type=group_weight_type,
                    group_quantity=animal_count,
                    group_total_weight=total_weight,  # Total weight of the group
                )

                # Check if this completed the weight type
                new_total = current_total + animal_count

                # For hot carcass weight, count both slaughtered and carcass_ready animals
                if weight_type == "hot_carcass_weight":
                    available_count = order.animals.filter(status__in=["slaughtered", "carcass_ready"]).count()
                else:
                    available_count = order.animals.filter(status="slaughtered").count()

                if new_total >= available_count:
                    messages.success(
                        request,
                        _(
                            "✅ Batch weight logged successfully! All %(available_count)s animals for %(weight_type)s are now weighed. Individual weight logs have been automatically created with average weight of %(average_weight).2fkg per animal."
                        )
                        % {
                            "available_count": available_count,
                            "weight_type": weight_type.replace("_", " ").title(),
                            "average_weight": average_weight,
                        },
                    )
                else:
                    remaining = available_count - new_total
                    messages.success(
                        request,
                        _(
                            "Batch weight logged: %(animal_count)s animals weighed (%(total_weight)skg total, %(average_weight).2fkg average). %(remaining)s animals remaining for %(weight_type)s."
                        )
                        % {
                            "animal_count": animal_count,
                            "total_weight": total_weight,
                            "average_weight": average_weight,
                            "remaining": remaining,
                            "weight_type": weight_type.replace("_", " ").title(),
                        },
                    )

            except Exception as e:
                messages.error(request, _("Error logging batch weight: %(error)s") % {"error": str(e)})
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

        return redirect("processing:batch_weights")


class BatchWeightReportsView(LoginRequiredMixin, TemplateView):
    template_name = "processing/batch_weight_reports.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Get filter parameters from request
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        order_id = self.request.GET.get("order_id")

        # Convert date strings to datetime objects
        if date_from:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            except ValueError:
                date_from = None

        if date_to:
            try:
                date_to = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                date_to = None

        # Get comprehensive report data
        report_data = services.get_batch_weight_reports(date_from=date_from, date_to=date_to, order_id=order_id)

        context.update(report_data)
        context["form_data"] = {
            "date_from": date_from.strftime("%Y-%m-%d") if date_from else "",
            "date_to": date_to.strftime("%Y-%m-%d") if date_to else "",
            "order_id": order_id or "",
        }

        return context


class OrderStatusUpdateView(LoginRequiredMixin, View):
    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)

        # Update order status based on animal statuses
        # This could be expanded to handle specific status updates

        messages.success(request, _("Order %(order_no)s status updated.") % {"order_no": order.slaughter_order_no})
        return redirect("processing:dashboard")


class AnimalSearchView(View):  # Temporarily removed LoginRequiredMixin for debugging
    def get(self, request):
        query = request.GET.get("q", "").strip()

        if len(query) < 2:
            return JsonResponse({"animals": []})

        # Enhanced case-insensitive search including client name
        animals = Animal.objects.select_related(
            "slaughter_order", "slaughter_order__client", "slaughter_order__client__user"
        ).filter(
            Q(identification_tag__icontains=query)
            | Q(slaughter_order__slaughter_order_no__icontains=query)
            | Q(slaughter_order__client__company_name__icontains=query)
            | Q(slaughter_order__client__user__first_name__icontains=query)
            | Q(slaughter_order__client__user__last_name__icontains=query)
            | Q(slaughter_order__client__contact_person__icontains=query)
            | Q(slaughter_order__client_name__icontains=query)  # For walk-in clients
            | Q(animal_type__icontains=query)
        )[:20]  # Limit to 20 results

        animals_data = []
        for animal in animals:
            # Determine client info
            if animal.slaughter_order.client:
                client_info = (
                    animal.slaughter_order.client.company_name or animal.slaughter_order.client.get_full_name()
                )
            else:
                client_info = animal.slaughter_order.client_name or _("Walk-in Client")

            animals_data.append(
                {
                    "id": str(animal.pk),
                    "identification_tag": animal.identification_tag,
                    "animal_type_display": animal.get_animal_type_display(),
                    "order_number": animal.slaughter_order.slaughter_order_no,
                    "client_info": client_info,
                    "status": animal.status,
                    "status_display": animal.get_status_display(),
                    "received_date": animal.received_date.strftime("%b %d, %H:%M"),
                    "detail_url": reverse("processing:animal_detail", kwargs={"pk": animal.pk}),
                }
            )

        return JsonResponse({"animals": animals_data})


class LeatherWeightLogView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        form = LeatherWeightForm(request.POST, instance=animal)

        if form.is_valid():
            try:
                leather_weight = form.cleaned_data["leather_weight_kg"]
                # Save the form to update the animal instance
                form.save()
                messages.success(
                    request,
                    _("Leather weight (%(weight)s kg) logged for %(tag)s.")
                    % {"weight": leather_weight, "tag": animal.identification_tag},
                )
            except Exception as e:
                messages.error(request, _("Error logging leather weight: %(error)s") % {"error": str(e)})
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

        return redirect("processing:animal_detail", pk=animal.pk)


class AnimalSearchDebugView(View):
    """Debug view to test search functionality"""

    def get(self, request):
        query = request.GET.get("q", "").strip()

        if len(query) < 2:
            return JsonResponse({"debug": "query too short", "animals": []})

        try:
            # Enhanced case-insensitive search including client name
            animals = Animal.objects.select_related(
                "slaughter_order", "slaughter_order__client", "slaughter_order__client__user"
            ).filter(
                Q(identification_tag__icontains=query)
                | Q(slaughter_order__slaughter_order_no__icontains=query)
                | Q(slaughter_order__client__company_name__icontains=query)
                | Q(slaughter_order__client__user__first_name__icontains=query)
                | Q(slaughter_order__client__user__last_name__icontains=query)
                | Q(slaughter_order__client__contact_person__icontains=query)
                | Q(slaughter_order__client_name__icontains=query)  # For walk-in clients
                | Q(animal_type__icontains=query)
            )[:20]  # Limit to 20 results

            animals_data = []
            for animal in animals:
                # Determine client info
                if animal.slaughter_order.client:
                    client_info = (
                        animal.slaughter_order.client.company_name or animal.slaughter_order.client.get_full_name()
                    )
                else:
                    client_info = animal.slaughter_order.client_name or _("Walk-in Client")

                animals_data.append(
                    {
                        "id": str(animal.pk),
                        "identification_tag": animal.identification_tag,
                        "animal_type_display": animal.get_animal_type_display(),
                        "order_number": animal.slaughter_order.slaughter_order_no,
                        "client_info": client_info,
                        "status": animal.status,
                        "status_display": animal.get_status_display(),
                        "received_date": animal.received_date.strftime("%b %d, %H:%M"),
                        "detail_url": reverse("processing:animal_detail", kwargs={"pk": animal.pk}),
                    }
                )

            return JsonResponse(
                {"debug": f"found {len(animals_data)} results for query: {query}", "animals": animals_data}
            )

        except Exception as e:
            return JsonResponse({"debug": f"error: {str(e)}", "animals": [], "error": str(e)})


class AnimalDetailsUpdateView(LoginRequiredMixin, View):
    """View for updating animal-specific details"""

    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)

        # Check if animal status allows details to be filled
        allowed_statuses = [
            "slaughtered",
            "carcass_ready",
            "disassembled",
            "packaged",
            "delivered",
            "returned",
            "disposed",
        ]
        if animal.status not in allowed_statuses:
            messages.error(
                request,
                _(
                    "Animal details can only be filled after the animal has been slaughtered. Current status: %(status)s. Please slaughter the animal first."
                )
                % {"status": animal.get_status_display()},
            )
            return redirect("processing:animal_detail", pk=animal.pk)

        # Get the appropriate form class and model for this animal type
        form_class = ANIMAL_DETAIL_FORMS.get(animal.animal_type)
        detail_model = ANIMAL_DETAIL_MODELS.get(animal.animal_type)

        if not form_class or not detail_model:
            messages.error(
                request,
                _("No detail form available for %(animal_type)s.") % {"animal_type": animal.get_animal_type_display()},
            )
            return redirect("processing:animal_detail", pk=animal.pk)

        try:
            # Try to get existing details
            detail_instance = detail_model.objects.get(animal=animal)
            form = form_class(request.POST, instance=detail_instance)
            action = _("updated")
        except detail_model.DoesNotExist:
            # Create new details
            form = form_class(request.POST)
            action = _("created")

        if form.is_valid():
            detail_instance = form.save(commit=False)
            detail_instance.animal = animal
            detail_instance.save()

            messages.success(
                request,
                _("%(animal_type)s details %(action)s successfully for %(tag)s.")
                % {"animal_type": animal.get_animal_type_display(), "action": action, "tag": animal.identification_tag},
            )
        else:
            # Display form errors
            for field, errors in form.errors.items():
                field_label = form.fields[field].label or field.replace("_", " ").title()
                for error in errors:
                    messages.error(request, f"{field_label}: {error}")

        return redirect("processing:animal_detail", pk=animal.pk)


class DisassemblyDashboardView(LoginRequiredMixin, ListView):
    model = Animal
    template_name = "processing/disassembly_dashboard.html"
    context_object_name = "animals"
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import Prefetch, Q

        from scales.models import DisassemblySession

        active_sessions = DisassemblySession.objects.filter(
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).order_by("-started_at")
        queryset = (
            Animal.objects.filter(status__in=["carcass_ready", "disassembled"])
            .select_related("slaughter_order", "slaughter_order__client", "slaughter_order__service_package")
            .prefetch_related(
                "disassembly_cuts",
                "individual_weight_logs",
                Prefetch("scale_sessions", queryset=active_sessions, to_attr="active_scale_sessions"),
                Prefetch("disassembly_session_animals", queryset=active_sessions, to_attr="active_scale_sessions_m2m"),
            )
            .order_by("-slaughter_date")
        )

        # Filter by disassembly service package
        queryset = queryset.filter(slaughter_order__service_package__includes_disassembly=True)

        # Filter to only show eligible animals:
        # - Animals already disassembled: show them
        # - Animals with carcass_ready status: only show if they have hot carcass weight logged
        queryset = queryset.filter(
            Q(status="disassembled")  # Already disassembled - show them
            | Q(
                status="carcass_ready",
                individual_weight_logs__weight_type="hot_carcass_weight",
                individual_weight_logs__is_group_weight=False,
            )
        ).distinct()  # Use distinct() to avoid duplicates from the join

        # Filter by animal ID if provided (for quick add from animal detail page)
        animal_id = self.request.GET.get("animal")
        if animal_id:
            queryset = queryset.filter(pk=animal_id)

        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(identification_tag__icontains=search)
                | Q(slaughter_order__slaughter_order_no__icontains=search)
                | Q(slaughter_order__client__company_name__icontains=search)
                | Q(slaughter_order__client_name__icontains=search)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Merge FK and M2M active scale sessions so template sees a single list
        for animal in context.get("animals", []):
            fk_sessions = list(getattr(animal, "active_scale_sessions", []))
            m2m_sessions = getattr(animal, "active_scale_sessions_m2m", [])
            seen = {s.id for s in fk_sessions}
            for s in m2m_sessions:
                if s.id not in seen:
                    fk_sessions.append(s)
                    seen.add(s.id)
            animal.active_scale_sessions = fk_sessions

        # Get the selected animal from URL parameter
        animal_id = self.request.GET.get("animal")
        selected_animal = None
        if animal_id:
            try:
                selected_animal = Animal.objects.select_related(
                    "slaughter_order", "slaughter_order__service_package"
                ).get(pk=animal_id)
            except Animal.DoesNotExist:
                pass

        # Separate animals by disassembly type
        boneless_animals = []
        standard_animals = []

        for animal in context.get("animals", []):
            if animal.is_boneless_disassembly():
                boneless_animals.append(animal)
            elif animal.is_standard_disassembly():
                standard_animals.append(animal)

        context["boneless_animals"] = boneless_animals
        context["standard_animals"] = standard_animals
        context["selected_animal"] = selected_animal
        context["current_search"] = self.request.GET.get("search", "")

        # Add form for selected animal
        if selected_animal:
            from .forms import DisassemblyCutForm

            context["disassembly_form"] = DisassemblyCutForm(animal=selected_animal)

        return context


class DisassemblyDetailView(LoginRequiredMixin, DetailView):
    """Dedicated view for managing disassembly cuts for a specific animal"""

    model = Animal
    template_name = "processing/disassembly_detail.html"
    context_object_name = "animal"

    def get_object(self, queryset=None):
        """Return 404 with helpful message when animal exists but isn't eligible for disassembly."""
        from django.http import Http404

        pk = self.kwargs.get(self.pk_url_kwarg)
        if pk is None:
            raise Http404(_("No animal found matching the query"))
        if queryset is None:
            queryset = self.get_queryset()
        try:
            return queryset.get(pk=pk)
        except self.model.DoesNotExist:
            # Animal may exist but not be eligible (e.g. order lacks disassembly service)
            if Animal.objects.filter(pk=pk).exists():
                raise Http404(
                    _(
                        "This animal is not eligible for disassembly. The order may not include the disassembly service, or hot carcass weight may not be logged yet."
                    )
                )
            raise Http404(_("No animal found matching the query"))

    def get_queryset(self):
        # Only show animals eligible for disassembly
        from django.db.models import Q

        return (
            Animal.objects.filter(
                Q(status="disassembled")
                | Q(
                    status="carcass_ready",
                    individual_weight_logs__weight_type="hot_carcass_weight",
                    individual_weight_logs__is_group_weight=False,
                ),
                slaughter_order__service_package__includes_disassembly=True,
            )
            .select_related("slaughter_order", "slaughter_order__service_package")
            .prefetch_related("disassembly_cuts", "individual_weight_logs")
            .distinct()
        )

    @staticmethod
    def _sync_scale_events_to_cuts(animal, session, events, session_animals):
        """
        Materialize allocated scale events as DisassemblyCut rows so they are
        visible/printable in the existing cuts pipeline.
        """
        from scales.utils import get_event_allocation

        event_ids = set()
        for event in events:
            alloc = get_event_allocation(event, session_animals)
            allocated_grams = int(alloc.get(str(animal.id), 0) or 0)
            if allocated_grams <= 0:
                continue

            event_ids.add(event.id)
            weight_kg = (Decimal(allocated_grams) / Decimal("1000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            DisassemblyCut.objects.update_or_create(
                animal=animal,
                session=session,
                source_event=event,
                defaults={
                    "cut_name": (
                        getattr(event, "display_product_name", "") or event.product_name or f"PLU {event.plu_code}"
                    )[:100],
                    "weight_kg": weight_kg,
                },
            )

        # Remove stale generated cuts for events no longer present/allocated.
        stale_qs = DisassemblyCut.objects.filter(
            animal=animal,
            session=session,
            source_event__isnull=False,
        )
        if event_ids:
            stale_qs = stale_qs.exclude(source_event_id__in=event_ids)
        stale_qs.delete()

    def get_context_data(self, **kwargs):
        from django.db.models import Q

        from scales.models import DisassemblySession, WeighingEvent
        from scales.utils import (
            get_catalog_name_for_plu,
            get_event_allocation,
            get_product_display_names,
            get_session_per_animal_summary,
            normalize_plu_code,
        )

        context = super().get_context_data(**kwargs)
        animal = self.object

        # Sync events from all linked sessions (active + completed) into existing cuts.
        linked_sessions = (
            DisassemblySession.objects.filter(Q(animal=animal) | Q(animals=animal))
            .select_related("site")
            .prefetch_related("animals")
            .order_by("-started_at")
        )
        for linked_session in linked_sessions:
            linked_animals = list(linked_session.animals.order_by("id"))
            if not linked_animals and linked_session.animal_id:
                linked_animals = [linked_session.animal]
            if not linked_animals:
                continue
            linked_events = list(
                WeighingEvent.objects.filter(session=linked_session, is_active=True, deleted_at__isnull=True).order_by(
                    "-scale_timestamp"
                )[:300]
            )
            if not linked_events:
                continue
            linked_product_names = get_product_display_names(
                [ev.plu_code for ev in linked_events], site=linked_session.site
            )
            for ev in linked_events:
                ev.display_product_name = (
                    get_catalog_name_for_plu(ev.plu_code)
                    or linked_product_names.get(ev.plu_code)
                    or ev.product_name
                    or f"PLU {normalize_plu_code(ev.plu_code)}"
                )
            self._sync_scale_events_to_cuts(
                animal=animal,
                session=linked_session,
                events=linked_events,
                session_animals=linked_animals,
            )

        # Active scale session for this animal (session.animal or session.animals M2M)
        active_session = (
            DisassemblySession.objects.filter(
                Q(animal=animal) | Q(animals=animal),
                status__in=["pending", "active", "paused"],
                is_active=True,
            )
            .select_related("device", "site")
            .prefetch_related("animals")
            .order_by("-started_at")
            .first()
        )
        session_events = []
        scale_allocation_for_this_animal = None
        if active_session:
            session_animals = list(active_session.animals.order_by("id"))
            if not session_animals and active_session.animal_id:
                session_animals = [active_session.animal]
            session_events = list(
                WeighingEvent.objects.filter(session=active_session, is_active=True, deleted_at__isnull=True).order_by(
                    "-scale_timestamp"
                )[:100]
            )
            product_names = get_product_display_names([ev.plu_code for ev in session_events], site=active_session.site)
            for ev in session_events:
                if ev.product_display_override:
                    ev.display_product_name = ev.product_display_override
                else:
                    ev.display_product_name = (
                        product_names.get(ev.plu_code) or ev.product_name or f"PLU {normalize_plu_code(ev.plu_code)}"
                    )
                alloc = get_event_allocation(ev, session_animals)
                ev.allocated_grams_for_this_animal = alloc.get(str(animal.id), 0)
            summary = get_session_per_animal_summary(active_session)
            for row in summary:
                if row["animal"].id == animal.id:
                    scale_allocation_for_this_animal = row
                    break
            self._sync_scale_events_to_cuts(
                animal=animal,
                session=active_session,
                events=session_events,
                session_animals=session_animals,
            )
        context["active_session"] = active_session
        context["session_events"] = session_events
        context["has_active_session"] = active_session is not None
        context["scale_allocation_for_this_animal"] = scale_allocation_for_this_animal

        # Add disassembly readiness check
        context["can_proceed_to_disassembly"] = animal.can_proceed_to_disassembly()

        # Add form for adding new cuts
        context["disassembly_form"] = DisassemblyCutForm(animal=animal)

        # Get all existing cuts with their labels prefetched
        from labeling.models import AnimalLabel

        cuts = animal.disassembly_cuts.select_related("source_event").all().order_by("-created_at")
        # Attach labels directly to cuts for easier template access
        for cut in cuts:
            cut.label = AnimalLabel.objects.filter(cut=cut, label_type="cut").order_by("-print_date").first()

        context["disassembly_cuts"] = cuts
        context["manual_disassembly_cuts"] = cuts.filter(source_event__isnull=True)

        # Get hot carcass weight
        hot_carcass_log = (
            animal.individual_weight_logs.filter(weight_type="hot_carcass_weight", is_group_weight=False)
            .order_by("-log_date")
            .first()
        )
        context["hot_carcass_weight"] = hot_carcass_log.weight if hot_carcass_log else None
        context["hot_carcass_log_date"] = hot_carcass_log.log_date if hot_carcass_log else None

        return context


class AddDisassemblyCutView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)

        form = DisassemblyCutForm(request.POST, animal=animal)
        if form.is_valid():
            try:
                cut = form.save(commit=False)
                cut.animal = animal
                # Attach active scale session if one exists (session-first disassembly)
                from scales.models import DisassemblySession

                active_session = (
                    DisassemblySession.objects.filter(
                        Q(animal=animal) | Q(animals=animal),
                        status__in=["pending", "active", "paused"],
                        is_active=True,
                    )
                    .order_by("-started_at")
                    .first()
                )
                if active_session:
                    cut.session = active_session
                cut.save()

                # Auto-transition to disassembled if not already and conditions are met
                if animal.status == "carcass_ready":
                    try:
                        readiness = animal.can_proceed_to_disassembly()
                        if readiness["can_proceed"]:
                            animal.perform_disassembly()
                            animal.save()
                    except Exception as e:
                        # Log the error but don't fail the cut addition
                        import logging

                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to transition animal {animal.pk} to disassembled: {e}")

                cut_display = cut.get_cut_name_display()
                if animal.is_boneless_disassembly():
                    messages.success(
                        request,
                        _("Boneless meat weight (%(weight)s kg) recorded successfully.") % {"weight": cut.weight_kg},
                    )
                else:
                    messages.success(
                        request,
                        _('Cut "%(cut)s" (%(weight)s kg) added successfully.')
                        % {"cut": cut_display, "weight": cut.weight_kg},
                    )
            except Exception as e:
                messages.error(request, _("Error saving cut: %(error)s") % {"error": str(e)})
        else:
            for field, errors in form.errors.items():
                field_label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    messages.error(request, f"{field_label}: {error}")

        # Redirect back to disassembly detail page
        return redirect("processing:disassembly_detail", pk=animal.pk)


class EditDisassemblyCutView(LoginRequiredMixin, View):
    """View for editing an existing disassembly cut"""

    @staticmethod
    def _render_disassembly_detail_with_edit_context(request, animal, form, cut):
        """
        Reuse DisassemblyDetailView context so edit mode keeps all sidebar/session
        widgets working (active session banner, allocation summary, hot carcass stats, etc.).
        """
        detail_view = DisassemblyDetailView()
        detail_view.request = request
        detail_view.object = animal
        context = detail_view.get_context_data()
        context["disassembly_form"] = form
        context["editing_cut"] = cut
        return render(request, "processing/disassembly_detail.html", context)

    def get(self, request, pk, cut_pk):
        animal = get_object_or_404(Animal, pk=pk)
        cut = get_object_or_404(DisassemblyCut, pk=cut_pk, animal=animal)
        if cut.source_event_id:
            messages.error(request, _("Scale-origin cuts are read-only. Edit the source event in Scale Session."))
            return redirect("processing:disassembly_detail", pk=animal.pk)

        form = DisassemblyCutForm(instance=cut, animal=animal)
        return self._render_disassembly_detail_with_edit_context(request, animal, form, cut)

    def post(self, request, pk, cut_pk):
        animal = get_object_or_404(Animal, pk=pk)
        cut = get_object_or_404(DisassemblyCut, pk=cut_pk, animal=animal)
        if cut.source_event_id:
            messages.error(request, _("Scale-origin cuts are read-only. Edit the source event in Scale Session."))
            return redirect("processing:disassembly_detail", pk=animal.pk)

        form = DisassemblyCutForm(request.POST, instance=cut, animal=animal)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, _("Cut updated successfully."))
                return redirect("processing:disassembly_detail", pk=animal.pk)
            except Exception as e:
                messages.error(request, _("Error updating cut: %(error)s") % {"error": str(e)})
        else:
            for field, errors in form.errors.items():
                field_label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    messages.error(request, f"{field_label}: {error}")

        return self._render_disassembly_detail_with_edit_context(request, animal, form, cut)


class DeleteDisassemblyCutView(LoginRequiredMixin, View):
    """View for deleting an existing disassembly cut"""

    def post(self, request, pk, cut_pk):
        animal = get_object_or_404(Animal, pk=pk)
        cut = get_object_or_404(DisassemblyCut, pk=cut_pk, animal=animal)
        if cut.source_event_id:
            messages.error(
                request, _("Scale-origin cuts cannot be deleted directly. Delete or reassign the source scale event.")
            )
            return redirect("processing:disassembly_detail", pk=animal.pk)

        cut_name = cut.get_cut_name_display()
        cut.delete()

        messages.success(request, _('Cut "%(cut)s" deleted successfully.') % {"cut": cut_name})
        return redirect("processing:disassembly_detail", pk=animal.pk)
