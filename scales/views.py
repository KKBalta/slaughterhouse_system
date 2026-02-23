"""Template-based views for scale session management and PLU/orphaned batch management."""
from datetime import timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.generic import TemplateView, ListView, DetailView, View
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext as _
from django.db import models as db_models
from django import forms
from django.http import JsonResponse

from processing.models import Animal
from .models import (
    Site,
    EdgeDevice,
    ScaleDevice,
    DisassemblySession,
    WeighingEvent,
    OrphanedBatch,
    PLUItem,
    EdgeActivityLog,
)

# ---------- Connectivity (60s freshness) ----------
DEFAULT_CONNECTIVITY_TIMEOUT_SECONDS = 60


def is_edge_online(edge, timeout_seconds=None):
    """True if edge last_seen_at is within timeout_seconds (default 60)."""
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_CONNECTIVITY_TIMEOUT_SECONDS
    if not edge.last_seen_at:
        return False
    return (timezone.now() - edge.last_seen_at) <= timedelta(seconds=timeout_seconds)


def is_device_online(device, timeout_seconds=None):
    """True if scale device last_heartbeat_at is within timeout_seconds (default 60)."""
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_CONNECTIVITY_TIMEOUT_SECONDS
    if not device.last_heartbeat_at:
        return False
    return (timezone.now() - device.last_heartbeat_at) <= timedelta(seconds=timeout_seconds)


def _age_seconds(dt):
    """Seconds since dt; None if dt is None."""
    if dt is None:
        return None
    delta = timezone.now() - dt
    return int(delta.total_seconds())


class ScalesDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "scales/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sites"] = Site.objects.filter(is_active=True)
        context["edges"] = EdgeDevice.objects.filter(is_active=True).select_related("site")
        context["active_sessions"] = DisassemblySession.objects.filter(
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).select_related("device", "animal", "site")[:20]
        context["pending_batches"] = OrphanedBatch.objects.filter(
            status="pending", is_active=True
        ).count()
        return context


class AdminOnlyMixin(UserPassesTestMixin):
    """Restrict access to admins for operational management pages."""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.role == self.request.user.Role.ADMIN


class EdgeManagementView(LoginRequiredMixin, AdminOnlyMixin, TemplateView):
    template_name = "scales/edge_management.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site_id = self.request.GET.get("site_id")
        edge_id = self.request.GET.get("edge_id")

        sites = Site.objects.filter(is_active=True).order_by("name")
        selected_site = sites.filter(id=site_id).first() if site_id else None
        edges = EdgeDevice.objects.filter(is_active=True).select_related("site").order_by("name", "created_at")
        if selected_site:
            edges = edges.filter(site=selected_site)
        selected_edge = edges.filter(id=edge_id).first() if edge_id else None

        printers = (
            ScaleDevice.objects.filter(is_active=True)
            .select_related("edge", "edge__site")
            .order_by("device_id")
        )
        if selected_edge:
            printers = printers.filter(edge=selected_edge)
        elif selected_site:
            printers = printers.filter(edge__site=selected_site)

        recent_logs = EdgeActivityLog.objects.select_related(
            "site", "edge", "device"
        ).order_by("-created_at")
        if selected_site:
            recent_logs = recent_logs.filter(site=selected_site)
        if selected_edge:
            recent_logs = recent_logs.filter(edge=selected_edge)

        edges_list = list(edges[:100])
        for edge in edges_list:
            edge.is_online_computed = is_edge_online(edge)
            edge.last_seen_age_seconds = _age_seconds(edge.last_seen_at)

        printers_list = list(printers[:100])
        for printer in printers_list:
            printer.is_online_computed = is_device_online(printer)
            printer.last_heartbeat_age_seconds = _age_seconds(printer.last_heartbeat_at)

        context.update(
            {
                "sites": sites,
                "edges": edges_list,
                "printers": printers_list,
                "recent_logs": recent_logs[:100],
                "selected_site_id": str(selected_site.id) if selected_site else "",
                "selected_edge_id": str(selected_edge.id) if selected_edge else "",
            }
        )
        return context


class EdgeBySiteJsonView(LoginRequiredMixin, AdminOnlyMixin, View):
    def get(self, request):
        site_id = request.GET.get("site_id")
        if not site_id:
            return JsonResponse({"edges": []})
        site = Site.objects.filter(id=site_id).first()
        site_name = site.name if site else ""
        edges = (
            EdgeDevice.objects.filter(site_id=site_id, is_active=True)
            .order_by("name", "created_at")
        )
        out = []
        for edge in edges:
            out.append({
                "id": str(edge.id),
                "name": edge.name or f"Edge {str(edge.id)[:8]}",
                "site_name": site_name,
                "is_online": is_edge_online(edge),
                "last_seen_at": edge.last_seen_at.isoformat() if edge.last_seen_at else None,
                "last_seen_age_seconds": _age_seconds(edge.last_seen_at),
                "version": edge.version,
            })
        return JsonResponse({"edges": out})


class PrintersByEdgeJsonView(LoginRequiredMixin, AdminOnlyMixin, View):
    def get(self, request):
        edge_id = request.GET.get("edge_id")
        if not edge_id:
            return JsonResponse({"printers": []})
        printers = (
            ScaleDevice.objects.filter(edge_id=edge_id, is_active=True)
            .order_by("device_id")
        )
        out = []
        for printer in printers:
            out.append({
                "id": str(printer.id),
                "device_id": printer.device_id,
                "global_device_id": printer.global_device_id,
                "device_type": printer.device_type,
                "status": printer.status,
                "is_online": is_device_online(printer),
                "last_heartbeat_at": printer.last_heartbeat_at.isoformat() if printer.last_heartbeat_at else None,
                "last_heartbeat_age_seconds": _age_seconds(printer.last_heartbeat_at),
                "last_event_at": printer.last_event_at.isoformat() if printer.last_event_at else None,
            })
        return JsonResponse({"printers": out})


class SessionListViewModel:
    """Shared queryset for session list."""

    @staticmethod
    def get_queryset(request):
        qs = (
            DisassemblySession.objects.filter(is_active=True)
            .select_related("device", "animal", "site")
            .order_by("-started_at")
        )
        status = request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs


class SessionListView(LoginRequiredMixin, ListView):
    model = DisassemblySession
    template_name = "scales/session_list.html"
    context_object_name = "sessions"
    paginate_by = 25

    def get_queryset(self):
        return SessionListViewModel.get_queryset(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_filter"] = self.request.GET.get("status", "")
        context["status_choices"] = DisassemblySession.STATUS_CHOICES
        return context


class SessionCreateForm(forms.Form):
    device = forms.ModelChoiceField(
        queryset=ScaleDevice.objects.none(),
        label=_("Scale device"),
        required=True,
        widget=forms.Select(
            attrs={
                "class": "block w-full rounded-md border border-gray-300 bg-white text-gray-900 py-2.5 px-3 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30",
            }
        ),
    )
    animal = forms.ModelChoiceField(
        queryset=Animal.objects.filter(
            status__in=["carcass_ready", "disassembled", "slaughtered"]
        ).order_by("-slaughter_date"),
        label=_("Animal"),
        required=True,
        widget=forms.Select(
            attrs={
                "class": "block w-full rounded-md border border-gray-300 bg-white text-gray-900 py-2.5 px-3 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        site_id = kwargs.pop("site_id", None)
        initial = kwargs.pop("initial", None) or {}
        super().__init__(*args, initial=initial, **kwargs)
        if site_id:
            busy_device_ids = set(
                DisassemblySession.objects.filter(
                    device__edge__site_id=site_id,
                    device__isnull=False,
                    status__in=["pending", "active", "paused"],
                    is_active=True,
                )
                .values_list("device_id", flat=True)
            )
            self.fields["device"].queryset = ScaleDevice.objects.filter(
                edge__site_id=site_id, is_active=True
            ).exclude(id__in=busy_device_ids).select_related("edge")
        for key, value in initial.items():
            if key in self.fields and value is not None:
                self.fields[key].initial = value


class SessionCreateView(LoginRequiredMixin, View):
    template_name = "scales/session_create.html"

    def get(self, request):
        sites = Site.objects.filter(is_active=True)
        site_id = request.GET.get("site_id") or (sites.first() and sites.first().id)
        initial = {}
        animal_id = request.GET.get("animal_id")
        if animal_id:
            try:
                animal = Animal.objects.get(
                    pk=animal_id,
                    status__in=["carcass_ready", "disassembled", "slaughtered"],
                )
                initial["animal"] = animal
            except Animal.DoesNotExist:
                pass
        form = SessionCreateForm(site_id=site_id, initial=initial)
        return render(
            request,
            self.template_name,
            {"form": form, "sites": sites, "selected_site_id": site_id},
        )

    def post(self, request):
        site_id = request.POST.get("site_id") or request.GET.get("site_id")
        form = SessionCreateForm(request.POST, site_id=site_id)
        if not form.is_valid():
            sites = Site.objects.filter(is_active=True)
            return render(
                request,
                self.template_name,
                {"form": form, "sites": sites, "selected_site_id": site_id},
            )
        device = form.cleaned_data["device"]
        animal = form.cleaned_data["animal"]
        existing = DisassemblySession.objects.filter(
            device=device,
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).first()
        if existing:
            messages.error(
                request,
                _("Device %(device)s already has an active session (animal: %(tag)s). Close it before starting a new one.")
                % {"device": device.device_id, "tag": existing.animal.identification_tag if existing.animal else "—"},
            )
            sites = Site.objects.filter(is_active=True)
            form = SessionCreateForm(request.POST, site_id=site_id)
            form.fields["device"].queryset = ScaleDevice.objects.filter(
                edge__site_id=site_id, is_active=True
            ).select_related("edge")
            return render(
                request,
                self.template_name,
                {"form": form, "sites": sites, "selected_site_id": site_id},
            )
        operator = request.user.get_full_name() or request.user.get_username() or str(request.user)
        site = device.edge.site
        session = DisassemblySession.objects.create(
            site=site,
            device=device,
            animal=animal,
            operator=operator,
            started_at=timezone.now(),
            status="pending",
        )
        messages.success(
            request,
            _("Session started for %(tag)s on %(device)s.")
            % {"tag": animal.identification_tag, "device": device.device_id},
        )
        return redirect("scales:session_detail", pk=session.id)


class SessionDetailView(LoginRequiredMixin, DetailView):
    model = DisassemblySession
    template_name = "scales/session_detail.html"
    context_object_name = "session"

    def get_queryset(self):
        return DisassemblySession.objects.filter(is_active=True).select_related(
            "device", "animal", "site"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["events"] = (
            WeighingEvent.objects.filter(session=self.object)
            .order_by("-scale_timestamp")[:100]
        )
        return context


class SessionEventsJsonView(LoginRequiredMixin, View):
    """Return session events and summary as JSON for polling (e.g. from disassembly detail)."""

    def get(self, request, pk):
        session = get_object_or_404(
            DisassemblySession, pk=pk, is_active=True
        )
        events = (
            WeighingEvent.objects.filter(session=session)
            .order_by("-scale_timestamp")[:100]
        )
        event_list = [
            {
                "id": str(e.id),
                "plu_code": e.plu_code,
                "product_name": e.product_name,
                "weight_grams": e.weight_grams,
                "scale_timestamp": e.scale_timestamp.isoformat() if e.scale_timestamp else None,
            }
            for e in events
        ]
        return JsonResponse(
            {
                "session_id": str(session.id),
                "status": session.status,
                "status_display": session.get_status_display(),
                "event_count": session.event_count,
                "total_weight_grams": session.total_weight_grams,
                "events": event_list,
            }
        )


class SessionCloseView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(
            DisassemblySession, pk=pk, is_active=True
        )
        if session.status not in ("pending", "active", "paused"):
            messages.warning(request, _("Session is already closed."))
            return redirect("scales:session_detail", pk=pk)
        session.status = "completed"
        session.ended_at = timezone.now()
        session.close_reason = request.POST.get("close_reason", "") or "Closed by operator"
        session.save(update_fields=["status", "ended_at", "close_reason", "updated_at"])
        messages.success(request, _("Session closed."))
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url:
            return redirect(next_url)
        return redirect("scales:session_list")


class SessionCancelView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(
            DisassemblySession, pk=pk, is_active=True
        )
        if session.status not in ("pending", "active", "paused"):
            messages.warning(request, _("Session is already closed."))
            return redirect("scales:session_detail", pk=pk)
        session.status = "cancelled"
        session.ended_at = timezone.now()
        session.close_reason = request.POST.get("close_reason", "") or "Cancelled"
        session.save(update_fields=["status", "ended_at", "close_reason", "updated_at"])
        messages.success(request, _("Session cancelled."))
        return redirect("scales:session_list")


class PLUListView(LoginRequiredMixin, ListView):
    model = PLUItem
    template_name = "scales/plu_list.html"
    context_object_name = "plu_items"
    paginate_by = 50

    def get_queryset(self):
        qs = PLUItem.objects.filter(is_active=True).order_by("plu_code")
        category = self.request.GET.get("category")
        if category:
            qs = qs.filter(category=category)
        search = self.request.GET.get("search")
        if search:
            qs = qs.filter(
                db_models.Q(plu_code__icontains=search)
                | db_models.Q(name__icontains=search)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category_filter"] = self.request.GET.get("category", "")
        context["search"] = self.request.GET.get("search", "")
        context["category_choices"] = PLUItem.CATEGORY_CHOICES
        return context


class OrphanedBatchListView(LoginRequiredMixin, ListView):
    model = OrphanedBatch
    template_name = "scales/orphaned_batch_list.html"
    context_object_name = "batches"
    paginate_by = 20

    def get_queryset(self):
        return (
            OrphanedBatch.objects.filter(status="pending", is_active=True)
            .select_related("edge", "device", "site")
            .order_by("-started_at")
        )


class OrphanedBatchReconcileView(LoginRequiredMixin, View):
    template_name = "scales/orphaned_batch_reconcile.html"

    def get(self, request, pk):
        batch = get_object_or_404(OrphanedBatch, pk=pk, status="pending", is_active=True)
        events = WeighingEvent.objects.filter(offline_batch_id=batch.batch_id).order_by(
            "scale_timestamp"
        )[:200]
        animals = Animal.objects.filter(
            status__in=["carcass_ready", "disassembled", "slaughtered"]
        ).order_by("-slaughter_date")[:100]
        return render(
            request,
            self.template_name,
            {"batch": batch, "events": events, "animals": animals},
        )

    def post(self, request, pk):
        batch = get_object_or_404(OrphanedBatch, pk=pk, status="pending", is_active=True)
        animal_id = request.POST.get("animal_id")
        if not animal_id:
            messages.error(request, _("Please select an animal."))
            return redirect("scales:orphaned_batch_reconcile", pk=pk)
        animal = get_object_or_404(Animal, pk=animal_id)
        from django.db import transaction
        with transaction.atomic():
            session = DisassemblySession.objects.create(
                site=batch.site,
                device=batch.device,
                animal=animal,
                operator=request.user.get_full_name() or str(request.user),
                started_at=batch.started_at,
                status="completed",
                ended_at=timezone.now(),
                close_reason="Reconciled from offline batch",
                event_count=batch.event_count,
                total_weight_grams=batch.total_weight_grams,
            )
            WeighingEvent.objects.filter(offline_batch_id=batch.batch_id).update(
                session=session, animal=animal
            )
            batch.status = "reconciled"
            batch.reconciled_to_session = session
            batch.reconciled_at = timezone.now()
            batch.reconciled_by = request.user.get_full_name() or str(request.user)
            batch.save(update_fields=["status", "reconciled_to_session", "reconciled_at", "reconciled_by", "updated_at"])
        messages.success(request, _("Batch reconciled to animal %(tag)s.") % {"tag": animal.identification_tag})
        return redirect("scales:orphaned_batch_list")
