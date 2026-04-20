import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.views.generic import DetailView, ListView

from reception.models import SlaughterOrder
from users.models import ClientProfile, User

STAFF_ROLES = frozenset({User.Role.ADMIN, User.Role.OWNER, User.Role.MANAGER, User.Role.OPERATOR})
CLIENT_ROLES = frozenset({User.Role.CLIENT, User.Role.WALKIN})


def _is_staff(user):
    return getattr(user, "role", "") in STAFF_ROLES


def _is_client(user):
    return getattr(user, "role", "") in CLIENT_ROLES


def _check_portal_access(user):
    if not _is_staff(user) and not _is_client(user):
        raise PermissionDenied


def _resolve_client_filter(request):
    """
    Returns a Q-compatible dict for filtering orders by client.

    - Staff: respect ?client=<pk> if provided, otherwise no client filter (see all orders).
    - Clients: always filter to their own profile.
    """
    if _is_staff(request.user):
        client_pk = request.GET.get("client")
        if client_pk:
            try:
                uuid.UUID(client_pk)
            except (ValueError, AttributeError):
                return {}
            return {"client__pk": client_pk}
        return {}  # staff with no filter sees all orders
    # CLIENT / WALKIN: always own orders only
    return {"client__user": request.user}


class ClientOrderListView(LoginRequiredMixin, ListView):
    model = SlaughterOrder
    template_name = "portal/order_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            _check_portal_access(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        filters = _resolve_client_filter(self.request)
        qs = SlaughterOrder.objects.select_related(
            "client",
            "service_package",
        ).prefetch_related("animals")
        if filters:
            qs = qs.filter(**filters)
        return qs.order_by("-order_datetime")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_staff_view"] = _is_staff(self.request.user)
        context["selected_client"] = None
        client_pk = self.request.GET.get("client")
        if client_pk and _is_staff(self.request.user):
            try:
                context["selected_client"] = ClientProfile.objects.get(pk=client_pk)
            except (ClientProfile.DoesNotExist, ValueError, ValidationError):
                pass
        return context


class ClientOrderDetailView(LoginRequiredMixin, DetailView):
    model = SlaughterOrder
    template_name = "portal/order_detail.html"
    context_object_name = "order"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            _check_portal_access(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        filters = _resolve_client_filter(self.request)
        qs = SlaughterOrder.objects.select_related(
            "client",
            "service_package",
            "destination_client",
        )
        if filters:
            qs = qs.filter(**filters)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        animals = list(
            self.object.animals.select_related("carcass")
            .prefetch_related(
                "carcass__meat_cuts",
                "offals",
                "by_products",
                "individual_weight_logs",
            )
            .order_by("received_date")
        )
        context["animals"] = animals
        context["animal_count"] = len(animals)
        context["is_staff_view"] = _is_staff(self.request.user)

        # Per-animal weight summary and order totals
        animal_summaries = []
        total_live_kg = None
        total_carcass_kg = None
        excluded_count = 0  # animals skipped from totals due to missing live weight

        for animal in animals:
            logs = animal.individual_weight_logs.all()
            sorted_logs = sorted(logs, key=lambda x: x.log_date, reverse=True)
            live_log = next((log for log in sorted_logs if log.weight_type == "live_weight"), None)
            carcass_log = next((log for log in sorted_logs if log.weight_type == "hot_carcass_weight"), None)
            live_w = float(live_log.weight) if live_log else None
            carcass_w = float(carcass_log.weight) if carcass_log else None
            live_weight_missing = live_w is None
            performance = None
            if live_w and carcass_w and live_w > 0:
                performance = round((carcass_w / live_w) * 100, 1)

            animal_summaries.append(
                {
                    "animal": animal,
                    "live_weight": live_w,
                    "carcass_weight": carcass_w,
                    "performance": performance,
                    "live_weight_missing": live_weight_missing,
                }
            )

            # Only include in order totals when live weight is present
            if not live_weight_missing:
                total_live_kg = (total_live_kg or 0) + live_w
                if carcass_w is not None:
                    total_carcass_kg = (total_carcass_kg or 0) + carcass_w
            else:
                excluded_count += 1

        context["animal_summaries"] = animal_summaries
        context["total_live_kg"] = round(total_live_kg, 2) if total_live_kg is not None else None
        context["total_carcass_kg"] = round(total_carcass_kg, 2) if total_carcass_kg is not None else None
        context["excluded_from_totals"] = excluded_count
        context["order_performance"] = (
            round((total_carcass_kg / total_live_kg) * 100, 1)
            if total_live_kg and total_carcass_kg and total_live_kg > 0
            else None
        )
        return context
