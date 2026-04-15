"""Template-based views for scale session management and PLU/orphaned batch management."""

import logging
from datetime import timedelta
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.paginator import Paginator
from django.db import models as db_models
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

# Queryset filter for animals eligible for disassembly (scale session + cuts page)
DISASSEMBLY_ELIGIBLE_FILTER = Q(
    Q(status="disassembled")
    | Q(
        status="carcass_ready",
        individual_weight_logs__weight_type="hot_carcass_weight",
        individual_weight_logs__is_group_weight=False,
    )
) & Q(slaughter_order__service_package__includes_disassembly=True)

from django import forms
from django.http import JsonResponse

from labeling.models import PrintJob
from processing.models import Animal
from users.policies import can_manage_tenant_users

from .api_views import _bump_edge_print_jobs_version
from .forms import SiteForm
from .print_worker_cache import get_edge_print_worker_pulse
from .models import (
    DisassemblySession,
    EdgeActivityLog,
    EdgeDevice,
    EdgeSetupCode,
    OrphanedBatch,
    PLUItem,
    Printer,
    ScaleDevice,
    Site,
    WeighingEvent,
)
from .utils import (
    get_product_display_names,
    maybe_mark_event_animals_disassembled,
    normalize_plu_code,
    parse_animal_uuid_from_qr_url,
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


def is_lan_printer_online(printer, timeout_seconds=None):
    """True if label printer last_seen_at is within timeout_seconds (heartbeat / inventory)."""
    if timeout_seconds is None:
        timeout_seconds = DEFAULT_CONNECTIVITY_TIMEOUT_SECONDS
    if not printer.last_seen_at:
        return False
    return (timezone.now() - printer.last_seen_at) <= timedelta(seconds=timeout_seconds)


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
        context["pending_batches"] = OrphanedBatch.objects.filter(status="pending", is_active=True).count()
        context["can_manage_tenant_ops"] = can_manage_tenant_users(self.request.user)
        return context


class AdminOnlyMixin(UserPassesTestMixin):
    """Restrict access to admins for operational management pages."""

    def test_func(self):
        return can_manage_tenant_users(self.request.user)


class EdgeManagementView(LoginRequiredMixin, AdminOnlyMixin, TemplateView):
    template_name = "scales/edge_management.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site_id = self.request.GET.get("site_id")
        edge_id = self.request.GET.get("edge_id")

        sites = Site.objects.filter(is_active=True).order_by("name")
        selected_site = sites.filter(id=site_id).first() if site_id else None
        edges = (
            EdgeDevice.objects.filter(is_active=True)
            .select_related("site")
            .annotate(
                in_flight_prints=db_models.Count(
                    "claimed_print_jobs",
                    filter=Q(claimed_print_jobs__status="dispatched"),
                )
            )
            .order_by("name", "created_at")
        )
        if selected_site:
            edges = edges.filter(site=selected_site)
        selected_edge = edges.filter(id=edge_id).first() if edge_id else None

        scale_devices = ScaleDevice.objects.filter(is_active=True).select_related("edge", "edge__site").order_by(
            "edge_id", "device_id"
        )
        label_printers = Printer.objects.filter(is_active=True).select_related("edge", "edge__site", "site").order_by(
            "edge_id", "priority", "local_printer_id"
        )
        if selected_edge:
            scale_devices = scale_devices.filter(edge=selected_edge)
            label_printers = label_printers.filter(edge=selected_edge)
        elif selected_site:
            scale_devices = scale_devices.filter(edge__site=selected_site)
            label_printers = label_printers.filter(site=selected_site)

        logs_qs = EdgeActivityLog.objects.select_related("site", "edge", "device").order_by("-created_at")
        if selected_site:
            logs_qs = logs_qs.filter(site=selected_site)
        if selected_edge:
            logs_qs = logs_qs.filter(edge=selected_edge)

        edges_list = list(edges[:100])
        for edge in edges_list:
            edge.is_online_computed = is_edge_online(edge)
            edge.last_seen_age_seconds = _age_seconds(edge.last_seen_at)
            edge.print_worker_pulse = get_edge_print_worker_pulse(edge.id)

        scale_devices_list = list(scale_devices[:100])
        for device in scale_devices_list:
            device.is_online_computed = is_device_online(device)
            device.last_heartbeat_age_seconds = _age_seconds(device.last_heartbeat_at)

        label_printers_list = list(label_printers[:100])
        for lan_printer in label_printers_list:
            lan_printer.is_online_computed = is_lan_printer_online(lan_printer)
            lan_printer.last_seen_age_seconds = _age_seconds(lan_printer.last_seen_at)

        log_paginator = Paginator(logs_qs, 25)
        log_page = log_paginator.get_page(self.request.GET.get("page") or 1)

        logs_params = self.request.GET.copy()
        logs_params.pop("page", None)
        logs_base_query = logs_params.urlencode()

        pending_jobs_qs = (
            PrintJob.objects.filter(
                status="pending",
                dispatch_mode="edge",
                site__is_active=True,
            )
            .select_related("site")
            .order_by("print_date")
        )
        if selected_site:
            pending_jobs_qs = pending_jobs_qs.filter(site=selected_site)
        pending_print_job_total = pending_jobs_qs.count()
        pending_print_jobs_preview = list(pending_jobs_qs[:20])

        dispatched_jobs_qs = (
            PrintJob.objects.filter(
                status="dispatched",
                dispatch_mode="edge",
                site__is_active=True,
            )
            .select_related("site", "claimed_by_edge")
            .order_by("edge_received_at", "print_date")
        )
        if selected_site:
            dispatched_jobs_qs = dispatched_jobs_qs.filter(site=selected_site)
        dispatched_print_job_total = dispatched_jobs_qs.count()
        dispatched_print_jobs_preview = list(dispatched_jobs_qs[:20])

        context.update(
            {
                "sites": sites,
                "edges": edges_list,
                "scale_devices": scale_devices_list,
                "label_printers": label_printers_list,
                "log_page": log_page,
                "logs_base_query": logs_base_query,
                "selected_site_id": str(selected_site.id) if selected_site else "",
                "selected_edge_id": str(selected_edge.id) if selected_edge else "",
                "pending_print_job_total": pending_print_job_total,
                "pending_print_jobs_preview": pending_print_jobs_preview,
                "dispatched_print_job_total": dispatched_print_job_total,
                "dispatched_print_jobs_preview": dispatched_print_jobs_preview,
            }
        )
        return context


class SiteListView(LoginRequiredMixin, AdminOnlyMixin, ListView):
    """List active sites (plants) for Edge and scale operations."""

    model = Site
    template_name = "scales/site_list.html"
    context_object_name = "sites"

    def get_queryset(self):
        return (
            Site.objects.filter(is_active=True)
            .annotate(active_edge_count=db_models.Count("edges", filter=Q(edges__is_active=True)))
            .order_by("name")
        )


class SiteCreateView(LoginRequiredMixin, AdminOnlyMixin, CreateView):
    model = Site
    form_class = SiteForm
    template_name = "scales/site_form.html"

    def get_success_url(self):
        return reverse("scales:site_list")

    def form_valid(self, form):
        messages.success(self.request, _("Site “%(name)s” was created.") % {"name": form.instance.name})
        return super().form_valid(form)


class SiteUpdateView(LoginRequiredMixin, AdminOnlyMixin, UpdateView):
    model = Site
    form_class = SiteForm
    template_name = "scales/site_form.html"

    def get_queryset(self):
        return Site.objects.filter(is_active=True)

    def get_success_url(self):
        return reverse("scales:site_list")

    def form_valid(self, form):
        messages.success(self.request, _("Site “%(name)s” was updated.") % {"name": form.instance.name})
        return super().form_valid(form)


class SiteDeactivateView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Soft-delete a site only when it has no active Edge devices."""

    def post(self, request, pk):
        site = get_object_or_404(Site, pk=pk, is_active=True)
        if EdgeDevice.objects.filter(site=site, is_active=True).exists():
            messages.error(
                request,
                _(
                    "This site still has active Edge devices. Remove them from Edge Management "
                    "before deactivating the site."
                ),
            )
            return redirect("scales:site_list")
        site.soft_delete()
        messages.success(request, _("Site “%(name)s” was deactivated.") % {"name": site.name})
        return redirect("scales:site_list")


class EdgeSetupCodeListView(LoginRequiredMixin, AdminOnlyMixin, ListView):
    """List all setup codes with status indicators."""

    model = EdgeSetupCode
    template_name = "scales/edge_setup_code_list.html"
    context_object_name = "setup_codes"
    paginate_by = 25

    def get_queryset(self):
        return (
            EdgeSetupCode.objects.filter(is_active=True)
            .select_related("site", "used_by_edge")
            .order_by("-created_at")
        )


class EdgeSetupCodeCreateView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Handle the 'Add Edge Device' form submission."""

    def get(self, request):
        sites = Site.objects.filter(is_active=True).order_by("name")
        printer_rows = list(
            Printer.objects.filter(is_active=True, enabled=True)
            .select_related("site", "edge")
            .order_by("site__name", "role", "priority")
            .values("id", "site_id", "display_name", "role", "host", "port")
        )
        for row in printer_rows:
            row["id"] = str(row["id"])
            row["site_id"] = str(row["site_id"])

        prefill_site = (request.GET.get("site_id") or "").strip()
        prefill_edge_name = (request.GET.get("edge_name") or "").strip()
        relink_from_edge = request.GET.get("relink") == "1"
        initial_site_id = ""
        initial_edge_name = ""
        relink_hint = False
        if relink_from_edge and prefill_site and Site.objects.filter(id=prefill_site, is_active=True).exists():
            initial_site_id = prefill_site
            initial_edge_name = prefill_edge_name
            relink_hint = True

        return render(
            request,
            "scales/edge_setup_code_create.html",
            {
                "sites": sites,
                "printers_json": printer_rows,
                "initial_site_id": initial_site_id,
                "initial_edge_name": initial_edge_name,
                "relink_hint": relink_hint,
            },
        )

    def post(self, request):
        site_id = request.POST.get("site_id")
        edge_name = (request.POST.get("edge_name") or "").strip()
        try:
            expiry_hours = int(request.POST.get("expiry_hours", 48))
        except (TypeError, ValueError):
            expiry_hours = 48
        if expiry_hours < 1:
            expiry_hours = 48

        if not site_id:
            messages.error(request, _("Please select a site."))
            return redirect("scales:edge_setup_code_create")

        try:
            site = Site.objects.get(id=site_id, is_active=True)
        except Site.DoesNotExist:
            messages.error(request, _("Site not found."))
            return redirect("scales:edge_setup_code_create")

        printers_config = []
        printer_ids = request.POST.getlist("printer_ids")
        for pid in printer_ids:
            try:
                printer = Printer.objects.get(id=pid, site=site, is_active=True)
                printers_config.append(
                    {
                        "localPrinterId": printer.local_printer_id,
                        "displayName": printer.display_name,
                        "role": printer.role,
                        "transport": printer.transport,
                        "host": printer.host,
                        "port": printer.port,
                        "model": printer.model,
                        "priority": printer.priority,
                    }
                )
            except (Printer.DoesNotExist, ValueError):
                continue

        manual_hosts = request.POST.getlist("manual_printer_host")
        manual_roles = request.POST.getlist("manual_printer_role")
        manual_names = request.POST.getlist("manual_printer_name")
        for i, host in enumerate(manual_hosts):
            host = host.strip()
            if not host:
                continue
            role = manual_roles[i].strip() if i < len(manual_roles) else "generic"
            name = manual_names[i].strip() if i < len(manual_names) else ""
            printers_config.append(
                {
                    "localPrinterId": f"{role}-{i + 1:02d}",
                    "displayName": name or f"{role.title()} Printer",
                    "role": role,
                    "transport": "tcp",
                    "host": host,
                    "port": 9100,
                    "model": "",
                    "priority": 100,
                }
            )

        setup_code = EdgeSetupCode.objects.create(
            site=site,
            edge_name=edge_name,
            printers_config=printers_config,
            expires_at=timezone.now() + timedelta(hours=expiry_hours),
        )

        return redirect("scales:edge_setup_code_detail", pk=setup_code.pk)


class EdgeSetupCodeDetailView(LoginRequiredMixin, AdminOnlyMixin, DetailView):
    """Show the setup code + instructions after creation."""

    model = EdgeSetupCode
    template_name = "scales/edge_setup_code_detail.html"
    context_object_name = "setup_code"

    def get_queryset(self):
        return EdgeSetupCode.objects.filter(is_active=True).select_related("site", "used_by_edge")

    def get_context_data(self, **kwargs):
        from django.conf import settings

        from tenants.tenant_helpers import get_tenant_site_url

        context = super().get_context_data(**kwargs)
        tenant_url = get_tenant_site_url()
        context["tenant_url"] = tenant_url

        base_domain = getattr(settings, "TENANT_BASE_DOMAIN", "localhost")
        if settings.DEBUG:
            public_api_base = f"http://api.{base_domain}:8000"
        else:
            public_api_base = f"https://api.{base_domain}"
        context["activate_url"] = f"{public_api_base}/api/v1/activate"

        sc = self.object
        if sc.used_by_edge_id:
            edge = sc.used_by_edge
            now = timezone.now()
            context["edge_connected"] = True
            context["edge_name"] = edge.name
            context["edge_online"] = (
                edge.is_online
                and edge.last_seen_at is not None
                and (now - edge.last_seen_at).total_seconds() < 120
            )
            context["edge_version"] = edge.version
            context["edge_health"] = edge.health
            context["edge_last_seen"] = edge.last_seen_at
            context["edge_printer_count"] = edge.printers.filter(is_active=True).count()
        else:
            context["edge_connected"] = False
        return context


class EdgeSetupCodeRevokeView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Revoke (soft-delete) an unused setup code."""

    def post(self, request, pk):
        try:
            setup_code = EdgeSetupCode.objects.get(pk=pk, is_active=True, used_at__isnull=True)
        except EdgeSetupCode.DoesNotExist:
            messages.error(request, _("Setup code not found or already used."))
            return redirect("scales:edge_setup_code_list")

        setup_code.soft_delete()
        messages.success(request, _("Setup code revoked successfully."))
        return redirect("scales:edge_setup_code_list")


def _redirect_edge_management_preserve_filter(request):
    """Return redirect to edge management, keeping ?site_id=&edge_id= when posted as `next`."""
    qs = (request.POST.get("next") or "").strip()
    if qs:
        return redirect(f"{reverse('scales:edge_management')}?{qs}")
    return redirect("scales:edge_management")


def _cancel_pending_print_jobs_for_edge_printers(edge: EdgeDevice) -> int:
    """
    Cancel pending edge print jobs that targeted a printer on this Edge.

    After soft-removing printers, those UUIDs no longer exist for inventory;
    leaving jobs pending would make a new Edge (after relink) try to drain a
    stale queue. Role-only jobs (no target_printer) are left for another Edge
    at the same site, if any.
    """
    printer_pks = list(Printer.objects.filter(edge=edge, is_active=True).values_list("pk", flat=True))
    if not printer_pks:
        return 0
    site_id = edge.site_id
    n = PrintJob.objects.filter(
        site_id=site_id,
        status="pending",
        dispatch_mode="edge",
        target_printer_id__in=printer_pks,
    ).update(
        status="cancelled",
        error_text=_("Target printer was removed with Edge; job cancelled."),
        updated_at=timezone.now(),
    )
    if n:
        _bump_edge_print_jobs_version(site_id)
    return n


def _cancel_all_pending_edge_print_jobs_for_site(site_id) -> int:
    """Cancel every pending edge-dispatched job for a site (used when re-pairing after reinstall)."""
    n = PrintJob.objects.filter(
        site_id=site_id,
        status="pending",
        dispatch_mode="edge",
    ).update(
        status="cancelled",
        error_text=_("Edge re-linked; pending queue cleared for this site."),
        updated_at=timezone.now(),
    )
    if n:
        _bump_edge_print_jobs_version(site_id)
    return n


def _release_dispatched_print_jobs_claimed_by_edge(edge: EdgeDevice) -> int:
    """Cancel in-flight (dispatched) jobs claimed by this worker before removing the Edge."""
    n = PrintJob.objects.filter(claimed_by_edge=edge, status="dispatched").update(
        status="cancelled",
        error_text=_("Edge removed or re-linked; in-flight print cleared."),
        updated_at=timezone.now(),
    )
    if n:
        _bump_edge_print_jobs_version(edge.site_id)
    return n


def _soft_remove_edge_device(edge: EdgeDevice) -> None:
    """Soft-delete an edge and its active scales/printers (Remove and Re-link flows)."""
    _release_dispatched_print_jobs_claimed_by_edge(edge)
    ScaleDevice.objects.filter(edge=edge, is_active=True).update(is_active=False)
    Printer.objects.filter(edge=edge, is_active=True).update(is_active=False, enabled=False)
    edge.soft_delete()


class EdgeDeviceRemoveView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Soft-delete an Edge device and its related scale devices and printers."""

    def post(self, request, pk):
        try:
            edge = EdgeDevice.objects.get(pk=pk, is_active=True)
        except EdgeDevice.DoesNotExist:
            messages.error(request, _("Edge device not found."))
            return _redirect_edge_management_preserve_filter(request)

        active_sessions = DisassemblySession.objects.filter(
            device__edge=edge,
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).count()
        if active_sessions > 0:
            messages.error(
                request,
                _("Cannot remove this edge — it has %(count)s active session(s). Close them first.")
                % {"count": active_sessions},
            )
            return _redirect_edge_management_preserve_filter(request)

        display = edge.name or str(edge.id)[:8]
        n_jobs = _cancel_pending_print_jobs_for_edge_printers(edge)
        _soft_remove_edge_device(edge)

        messages.success(
            request,
            _("Edge device '%(name)s' has been removed.") % {"name": display},
        )
        if n_jobs:
            messages.info(
                request,
                _("Cancelled %(n)s print job(s) that targeted this Edge's printers.") % {"n": n_jobs},
            )
        return _redirect_edge_management_preserve_filter(request)


class EdgePrepareRelinkView(LoginRequiredMixin, AdminOnlyMixin, View):
    """
    Clear cloud registration for an Edge (e.g. app uninstalled / data wiped) and open
    Add Edge Device with the same site and device name pre-filled so a new setup code
    can reconnect the physical PC to the current site.
    """

    def post(self, request, pk):
        try:
            edge = EdgeDevice.objects.select_related("site").get(pk=pk, is_active=True)
        except EdgeDevice.DoesNotExist:
            messages.error(request, _("Edge device not found."))
            return _redirect_edge_management_preserve_filter(request)

        active_sessions = DisassemblySession.objects.filter(
            device__edge=edge,
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).count()
        if active_sessions > 0:
            messages.error(
                request,
                _("Cannot re-link this edge — it has %(count)s active session(s). Close them first.")
                % {"count": active_sessions},
            )
            return _redirect_edge_management_preserve_filter(request)

        site = edge.site
        edge_name = (edge.name or "").strip()
        n_cleared = _cancel_all_pending_edge_print_jobs_for_site(site.id)
        _soft_remove_edge_device(edge)

        messages.success(
            request,
            _(
                "Registration cleared for this Edge. %(n)s pending print job(s) for %(site)s were cancelled "
                "so they will not all run at once after reinstall. Generate a new setup code on the next screen, "
                "then enter it in a fresh Edge install."
            )
            % {"site": site.name, "n": n_cleared},
        )
        q = urlencode(
            {
                "site_id": str(site.id),
                "edge_name": edge_name,
                "relink": "1",
            }
        )
        return redirect(f"{reverse('scales:edge_setup_code_create')}?{q}")


class ScaleDeviceRemoveView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Soft-delete a single scale device (e.g. stale registration). Blocked if sessions are open."""

    def post(self, request, pk):
        device = get_object_or_404(ScaleDevice, pk=pk, is_active=True)
        active_sessions = DisassemblySession.objects.filter(
            device=device,
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).count()
        if active_sessions > 0:
            messages.error(
                request,
                _("Cannot remove this scale — it has %(count)s active session(s). Close them first.")
                % {"count": active_sessions},
            )
            return _redirect_edge_management_preserve_filter(request)
        tag = device.device_id
        device.soft_delete()
        messages.success(
            request,
            _("Scale “%(id)s” was removed from the dashboard.") % {"id": tag},
        )
        return _redirect_edge_management_preserve_filter(request)


class PrinterRemoveView(LoginRequiredMixin, AdminOnlyMixin, View):
    """Soft-delete a label printer row (e.g. removed from LAN). Edge inventory may recreate it later."""

    def post(self, request, pk):
        printer = get_object_or_404(Printer, pk=pk, is_active=True)
        lid = printer.local_printer_id
        printer.enabled = False
        printer.soft_delete()
        messages.success(
            request,
            _("Printer “%(id)s” was removed from the dashboard.") % {"id": lid},
        )
        return _redirect_edge_management_preserve_filter(request)


class EdgeBySiteJsonView(LoginRequiredMixin, AdminOnlyMixin, View):
    def get(self, request):
        site_id = request.GET.get("site_id")
        if not site_id:
            return JsonResponse({"edges": []})
        site = Site.objects.filter(id=site_id).first()
        site_name = site.name if site else ""
        edges = (
            EdgeDevice.objects.filter(site_id=site_id, is_active=True)
            .annotate(
                in_flight_prints=db_models.Count(
                    "claimed_print_jobs",
                    filter=Q(claimed_print_jobs__status="dispatched"),
                )
            )
            .order_by("name", "created_at")
        )
        out = []
        for edge in edges:
            pulse = get_edge_print_worker_pulse(edge.id)
            out.append(
                {
                    "id": str(edge.id),
                    "name": edge.name or f"Edge {str(edge.id)[:8]}",
                    "site_name": site_name,
                    "is_online": is_edge_online(edge),
                    "last_seen_at": edge.last_seen_at.isoformat() if edge.last_seen_at else None,
                    "last_seen_age_seconds": _age_seconds(edge.last_seen_at),
                    "version": edge.version,
                    "in_flight_prints": edge.in_flight_prints,
                    "print_worker_pulse": pulse,
                }
            )
        return JsonResponse({"edges": out})


class PrintersByEdgeJsonView(LoginRequiredMixin, AdminOnlyMixin, View):
    """JSON for edge management: LAN label printers (Printer) + scale devices (ScaleDevice)."""

    def get(self, request):
        edge_id = request.GET.get("edge_id")
        site_id = request.GET.get("site_id")

        if edge_id:
            scales_qs = ScaleDevice.objects.filter(edge_id=edge_id, is_active=True).order_by("device_id")
            labels_qs = Printer.objects.filter(edge_id=edge_id, is_active=True).order_by("priority", "local_printer_id")
        elif site_id:
            scales_qs = ScaleDevice.objects.filter(edge__site_id=site_id, is_active=True).order_by(
                "edge_id", "device_id"
            )
            labels_qs = Printer.objects.filter(site_id=site_id, is_active=True).order_by(
                "edge_id", "priority", "local_printer_id"
            )
        else:
            return JsonResponse({"label_printers": [], "scale_devices": [], "printers": []})

        scale_out = []
        for device in scales_qs[:100]:
            scale_out.append(
                {
                    "id": str(device.id),
                    "device_id": device.device_id,
                    "global_device_id": device.global_device_id,
                    "device_type": device.device_type,
                    "status": device.status,
                    "is_online": is_device_online(device),
                    "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
                    "last_heartbeat_age_seconds": _age_seconds(device.last_heartbeat_at),
                    "last_event_at": device.last_event_at.isoformat() if device.last_event_at else None,
                }
            )

        label_out = []
        for lan_printer in labels_qs[:100]:
            label_out.append(
                {
                    "id": str(lan_printer.id),
                    "local_printer_id": lan_printer.local_printer_id,
                    "display_name": lan_printer.display_name or "",
                    "role": lan_printer.role,
                    "host": lan_printer.host,
                    "port": lan_printer.port,
                    "status": lan_printer.status,
                    "warnings": lan_printer.warnings,
                    "enabled": lan_printer.enabled,
                    "is_online": is_lan_printer_online(lan_printer),
                    "last_seen_at": lan_printer.last_seen_at.isoformat() if lan_printer.last_seen_at else None,
                    "last_seen_age_seconds": _age_seconds(lan_printer.last_seen_at),
                }
            )

        return JsonResponse(
            {
                "label_printers": label_out,
                "scale_devices": scale_out,
                "printers": scale_out,
            }
        )


class SessionListViewModel:
    """Shared queryset for session list."""

    @staticmethod
    def get_queryset(request):
        qs = (
            DisassemblySession.objects.filter(is_active=True)
            .select_related("device", "animal", "site")
            .prefetch_related("animals")
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
                ).values_list("device_id", flat=True)
            )
            self.fields["device"].queryset = (
                ScaleDevice.objects.filter(edge__site_id=site_id, is_active=True)
                .exclude(id__in=busy_device_ids)
                .select_related("edge")
            )
        for key, value in initial.items():
            if key in self.fields and value is not None:
                self.fields[key].initial = value


class SessionCreateAnimalSearchJsonView(LoginRequiredMixin, View):
    """Search animals eligible for scale session and disassembly (carcass_ready with hot weight, or disassembled)."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        if len(query) < 2:
            return JsonResponse({"animals": []})

        # Only animals eligible for disassembly: order includes disassembly, and either
        # disassembled or carcass_ready with hot_carcass_weight logged
        animals = (
            Animal.objects.filter(DISASSEMBLY_ELIGIBLE_FILTER)
            .filter(
                Q(identification_tag__icontains=query)
                | Q(slaughter_order__slaughter_order_no__icontains=query)
                | Q(slaughter_order__client__company_name__icontains=query)
                | Q(slaughter_order__client_name__icontains=query)
                | Q(animal_type__icontains=query)
            )
            .select_related("slaughter_order", "slaughter_order__client")
            .order_by("-slaughter_date")
            .distinct()[:30]
        )
        out = []
        for a in animals:
            client_info = _("Walk-in")
            if a.slaughter_order:
                if getattr(a.slaughter_order, "client", None):
                    client_info = (
                        a.slaughter_order.client.company_name
                        or (getattr(a.slaughter_order.client, "get_full_name", lambda: "")() or "")
                    ) or client_info
                else:
                    client_info = getattr(a.slaughter_order, "client_name", None) or client_info
            out.append(
                {
                    "id": str(a.pk),
                    "identification_tag": a.identification_tag or "",
                    "animal_type_display": a.get_animal_type_display(),
                    "order_number": a.slaughter_order.slaughter_order_no if a.slaughter_order else "",
                    "client_info": client_info,
                    "status": a.status,
                    "status_display": a.get_status_display(),
                }
            )
        return JsonResponse({"animals": out})


class SessionCreateView(LoginRequiredMixin, View):
    template_name = "scales/session_create.html"

    def _get_sites_and_selected_site_id(self, request):
        sites = Site.objects.filter(is_active=True)
        selected = request.GET.get("site_id") or request.POST.get("site_id")
        if selected:
            return sites, selected

        # Prefer site that currently has an online edge; then any site with an edge.
        preferred = sites.filter(edges__is_active=True, edges__is_online=True).distinct().first()
        if not preferred:
            preferred = sites.filter(edges__is_active=True).distinct().first()
        if not preferred:
            preferred = sites.first()
        return sites, (preferred.id if preferred else None)

    @staticmethod
    def _build_initial_animals(animal_ids):
        if not animal_ids:
            return []
        animals = list(Animal.objects.filter(pk__in=animal_ids).filter(DISASSEMBLY_ELIGIBLE_FILTER).distinct())
        return [{"id": str(a.pk), "identification_tag": a.identification_tag or str(a.pk)[:8]} for a in animals]

    def get(self, request):
        sites, site_id = self._get_sites_and_selected_site_id(request)
        requested_animal_ids = request.GET.getlist("animal_id")
        initial_animals = self._build_initial_animals(requested_animal_ids)

        # Validation: animal_id from QR scan but not eligible for disassembly
        included_ids = {a["id"] for a in initial_animals}
        for aid in requested_animal_ids:
            if aid not in included_ids:
                try:
                    animal = Animal.objects.get(pk=aid)
                    messages.error(
                        request,
                        _(
                            "Animal %(tag)s is not eligible for scale session. It must be carcass-ready with hot carcass weight."
                        )
                        % {"tag": animal.identification_tag or str(aid)[:8]},
                    )
                except Animal.DoesNotExist:
                    messages.error(
                        request,
                        _("Animal not found. The scanned QR code may be invalid."),
                    )

        # Support pasted QR URL: parse to animal UUID and redirect with current + new animal_id
        qr_url = request.GET.get("qr_url")
        if qr_url:
            logger.info("[QR] qr_url param received (len=%d, preview=%r)", len(qr_url), qr_url[:100])
            parsed_uuid = parse_animal_uuid_from_qr_url(qr_url)
            if parsed_uuid:
                try:
                    Animal.objects.filter(pk=parsed_uuid).filter(DISASSEMBLY_ELIGIBLE_FILTER).distinct().get()
                    existing_ids = request.GET.getlist("animal_id")
                    if str(parsed_uuid) not in existing_ids:
                        existing_ids.append(str(parsed_uuid))
                    qparams = [("site_id", site_id)]
                    for aid in existing_ids:
                        qparams.append(("animal_id", aid))
                    logger.info("[QR] qr_url redirect with animal_id uuid=%s", parsed_uuid)
                    return redirect(f"{request.path}?{urlencode(qparams)}")
                except Animal.DoesNotExist:
                    logger.warning("[QR] animal not found or not eligible uuid=%s", parsed_uuid)
                    try:
                        animal = Animal.objects.get(pk=parsed_uuid)
                        messages.error(
                            request,
                            _(
                                "Animal %(tag)s is not eligible for scale session. It must be carcass-ready with hot carcass weight."
                            )
                            % {"tag": animal.identification_tag or str(parsed_uuid)[:8]},
                        )
                    except Animal.DoesNotExist:
                        messages.error(
                            request,
                            _("Animal not found or not eligible for scale session."),
                        )
            else:
                logger.warning("[QR] qr_url parse failed, no UUID extracted (qr_url len=%d)", len(qr_url))
                messages.error(
                    request,
                    _("Could not find animal from this QR code."),
                )

        form = SessionCreateForm(site_id=site_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "sites": sites,
                "selected_site_id": site_id,
                "initial_animals": initial_animals,
            },
        )

    def post(self, request):
        site_id = request.POST.get("site_id") or request.GET.get("site_id")
        form = SessionCreateForm(request.POST, site_id=site_id)
        selected_animal_ids = request.POST.getlist("animal_ids")
        initial_animals = self._build_initial_animals(selected_animal_ids)
        if not form.is_valid():
            sites, selected_site_id = self._get_sites_and_selected_site_id(request)
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "sites": sites,
                    "selected_site_id": site_id,
                    "initial_animals": initial_animals,
                },
            )
        animal_ids = request.POST.getlist("animal_ids")
        if not animal_ids:
            sites, selected_site_id = self._get_sites_and_selected_site_id(request)
            messages.error(request, _("Select at least one animal."))
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "sites": sites,
                    "selected_site_id": site_id,
                    "initial_animals": initial_animals,
                },
            )
        animals = list(Animal.objects.filter(pk__in=animal_ids).filter(DISASSEMBLY_ELIGIBLE_FILTER).distinct())
        if len(animals) != len(animal_ids):
            sites, selected_site_id = self._get_sites_and_selected_site_id(request)
            messages.error(request, _("One or more selected animals are invalid or not eligible."))
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "sites": sites,
                    "selected_site_id": site_id,
                    "initial_animals": initial_animals,
                },
            )
        device = form.cleaned_data["device"]
        existing = DisassemblySession.objects.filter(
            device=device,
            status__in=["pending", "active", "paused"],
            is_active=True,
        ).first()
        if existing:
            primary = existing.get_primary_animal()
            tag_display = primary.identification_tag if primary else "—"
            messages.error(
                request,
                _(
                    "Device %(device)s already has an active session (animal: %(tag)s). Close it before starting a new one."
                )
                % {"device": device.device_id, "tag": tag_display},
            )
            sites, selected_site_id = self._get_sites_and_selected_site_id(request)
            form = SessionCreateForm(request.POST, site_id=site_id)
            form.fields["device"].queryset = ScaleDevice.objects.filter(
                edge__site_id=site_id, is_active=True
            ).select_related("edge")
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "sites": sites,
                    "selected_site_id": site_id,
                    "initial_animals": initial_animals,
                },
            )
        operator = request.user.get_full_name() or request.user.get_username() or str(request.user)
        site = device.edge.site
        session = DisassemblySession.objects.create(
            site=site,
            device=device,
            animal=animals[0],
            operator=operator,
            started_at=timezone.now(),
            status="pending",
        )
        session.animals.set(animals)
        if len(animals) == 1:
            messages.success(
                request,
                _("Session started for %(tag)s on %(device)s.")
                % {"tag": animals[0].identification_tag, "device": device.device_id},
            )
        else:
            messages.success(
                request,
                _("Session started for %(count)s animals on %(device)s.")
                % {"count": len(animals), "device": device.device_id},
            )
        return redirect("scales:session_detail", pk=session.id)


class SessionDetailView(LoginRequiredMixin, DetailView):
    model = DisassemblySession
    template_name = "scales/session_detail.html"
    context_object_name = "session"

    def get_queryset(self):
        return (
            DisassemblySession.objects.filter(is_active=True)
            .select_related(
                "device", "animal", "animal__slaughter_order", "animal__slaughter_order__service_package", "site"
            )
            .prefetch_related(
                "animal__individual_weight_logs",
                Prefetch(
                    "animals",
                    queryset=Animal.objects.select_related(
                        "slaughter_order", "slaughter_order__service_package"
                    ).prefetch_related("individual_weight_logs"),
                ),
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        events = list(
            WeighingEvent.objects.filter(session=self.object, is_active=True, deleted_at__isnull=True)
            .select_related("assigned_animal")
            .order_by("-scale_timestamp")[:100]
        )
        plu_codes = [e.plu_code for e in events]
        product_names = get_product_display_names(plu_codes, site=self.object.site)
        for e in events:
            if e.product_display_override:
                e.display_product_name = e.product_display_override
            else:
                resolved = product_names.get(e.plu_code)
                e.display_product_name = resolved if resolved else f"PLU {normalize_plu_code(e.plu_code)}"
        context["events"] = events
        return context


class SessionEventsJsonView(LoginRequiredMixin, View):
    """Return session events and summary as JSON for polling (e.g. from disassembly detail)."""

    def get(self, request, pk):
        session = get_object_or_404(DisassemblySession, pk=pk, is_active=True)
        events = list(
            WeighingEvent.objects.filter(session=session, is_active=True, deleted_at__isnull=True)
            .select_related("assigned_animal")
            .order_by("-scale_timestamp")[:100]
        )
        plu_codes = [e.plu_code for e in events]
        product_names = get_product_display_names(plu_codes, site=session.site)
        event_list = [
            {
                "id": str(e.id),
                "plu_code": e.plu_code,
                "product_name": (
                    e.product_display_override
                    or product_names.get(e.plu_code)
                    or f"PLU {normalize_plu_code(e.plu_code)}"
                ),
                "weight_grams": e.weight_grams,
                "scale_timestamp": e.scale_timestamp.isoformat() if e.scale_timestamp else None,
                "allocation_mode": e.allocation_mode,
                "assigned_animal_tag": (e.assigned_animal.identification_tag if e.assigned_animal else None),
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


class SessionEventEditView(LoginRequiredMixin, View):
    """Dedicated edit page for a weighing event (mobile-friendly): PLU select and weight.
    Allows editing inactive or soft-deleted events so users can fix weight and reactivate.
    """

    def get(self, request, session_pk, event_pk):
        session = get_object_or_404(DisassemblySession, pk=session_pk)
        event = get_object_or_404(WeighingEvent, pk=event_pk, session=session)
        product_names = get_product_display_names([event.plu_code], site=session.site)
        event.display_product_name = (
            event.product_display_override
            or product_names.get(event.plu_code)
            or f"PLU {normalize_plu_code(event.plu_code)}"
        )
        # Fetch all active PLUItems (catalog may be on Default site; session may use different site)
        plu_items = list(PLUItem.objects.filter(is_active=True).order_by("plu_code"))
        event_norm = normalize_plu_code(event.plu_code)
        selected_plu_code = event.plu_code
        for item in plu_items:
            if normalize_plu_code(item.plu_code) == event_norm:
                selected_plu_code = item.plu_code
                break
        weight_kg = round(event.weight_grams / 1000, 2)
        session_animals = list(session.animals.order_by("id"))
        if not session_animals and session.animal_id:
            session_animals = [session.animal]
        return render(
            request,
            "scales/session_event_edit.html",
            {
                "session": session,
                "event": event,
                "plu_items": plu_items,
                "selected_plu_code": selected_plu_code,
                "weight_kg": weight_kg,
                "session_animals": session_animals,
                "event_inactive": not event.is_active,
            },
        )


class SessionEventUpdateView(LoginRequiredMixin, View):
    """Update a weighing event (PLU/product, weight). Recalculates session total.
    Allows updating inactive/soft-deleted events and reactivates them on save.
    """

    def post(self, request, session_pk, event_pk):
        session = get_object_or_404(DisassemblySession, pk=session_pk)
        event = get_object_or_404(WeighingEvent, pk=event_pk, session=session)
        event_was_inactive = not event.is_active
        plu_code_post = (request.POST.get("plu_code") or "").strip()
        product_name = (request.POST.get("product_name") or "").strip()
        weight_str = request.POST.get("weight_grams", "").strip()
        weight_grams = None
        if weight_str:
            try:
                val = float(weight_str)
                if "." in weight_str or val < 100:
                    weight_grams = int(val * 1000)
                else:
                    weight_grams = int(val)
            except (ValueError, TypeError):
                pass

        update_fields = ["updated_at"]
        if plu_code_post:
            plu_norm = normalize_plu_code(plu_code_post)
            plu_items = list(PLUItem.objects.filter(is_active=True))
            plu_item = None
            for item in plu_items:
                if normalize_plu_code(item.plu_code) == plu_norm:
                    plu_item = item
                    break
            if plu_item:
                event.plu_code = plu_item.plu_code
                event.product_name = plu_item.name[:100]
                event.product_display_override = ""
                update_fields.extend(["plu_code", "product_name", "product_display_override"])
            elif "product_name" in request.POST:
                event.product_display_override = product_name[:100] if product_name else ""
                update_fields.append("product_display_override")
        elif "product_name" in request.POST:
            event.product_display_override = product_name[:100] if product_name else ""
            update_fields.append("product_display_override")

        if len(update_fields) > 1:
            event.save(update_fields=list(set(update_fields)))

        if weight_grams is not None and weight_grams >= 0:
            old_weight = event.weight_grams
            event.weight_grams = weight_grams
            event.save(update_fields=["weight_grams", "updated_at"])
            if event_was_inactive:
                session.total_weight_grams += weight_grams
                session.event_count = max(0, session.event_count) + 1
            else:
                session.total_weight_grams = session.total_weight_grams - old_weight + weight_grams
            session.save(update_fields=["total_weight_grams", "event_count", "updated_at"])

        assigned_animal_id = request.POST.get("assigned_animal_id", "").strip()
        session_animals = list(session.animals.order_by("id"))
        if not session_animals and session.animal_id:
            session_animals = [session.animal]
        valid_ids = {str(a.id) for a in session_animals}
        if assigned_animal_id and assigned_animal_id in valid_ids:
            event.assigned_animal_id = assigned_animal_id
            event.allocation_mode = "manual"
            event.allocated_weight_grams = event.weight_grams
        else:
            event.assigned_animal_id = None
            event.allocation_mode = "split"
            event.allocated_weight_grams = None
        update_fields_event = ["assigned_animal_id", "allocation_mode", "allocated_weight_grams", "updated_at"]
        if event_was_inactive:
            event.is_active = True
            event.deleted_at = None
            event.deleted_by = ""
            update_fields_event.extend(["is_active", "deleted_at", "deleted_by"])
        event.save(update_fields=update_fields_event)
        maybe_mark_event_animals_disassembled(event)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True})
        messages.success(request, _("Event updated."))
        if session.is_active:
            return redirect("scales:session_detail", pk=session.pk)
        return redirect("scales:session_list")


class SessionEventDeleteView(LoginRequiredMixin, View):
    """Soft-delete a weighing event; update session totals and set audit fields.
    If the event is already inactive (soft-deleted), redirect with info message instead of 404.
    """

    def post(self, request, session_pk, event_pk):
        session = get_object_or_404(DisassemblySession, pk=session_pk)
        event = get_object_or_404(WeighingEvent, pk=event_pk, session=session)
        if not event.is_active:
            messages.info(request, _("This event is already deleted."))
            if session.is_active:
                return redirect("scales:session_detail", pk=session.pk)
            return redirect("scales:session_list")
        event.deleted_at = timezone.now()
        event.deleted_by = ((request.user.get_full_name() or "").strip() or request.user.get_username())[:100]
        event.is_active = False
        event.save(update_fields=["deleted_at", "deleted_by", "is_active", "updated_at"])
        session.event_count = max(0, session.event_count - 1)
        session.total_weight_grams = max(0, session.total_weight_grams - event.weight_grams)
        session.save(update_fields=["event_count", "total_weight_grams", "updated_at"])
        messages.success(request, _("Event deleted."))
        if session.is_active:
            return redirect("scales:session_detail", pk=session.pk)
        return redirect("scales:session_list")


class SessionEventReactivateView(LoginRequiredMixin, View):
    """Reactivate a soft-deleted weighing event; add it back to session totals."""

    def post(self, request, session_pk, event_pk):
        session = get_object_or_404(DisassemblySession, pk=session_pk)
        event = get_object_or_404(WeighingEvent, pk=event_pk, session=session)
        if event.is_active:
            messages.info(request, _("This event is already active."))
        else:
            event.is_active = True
            event.deleted_at = None
            event.deleted_by = ""
            event.save(update_fields=["is_active", "deleted_at", "deleted_by", "updated_at"])
            session.event_count = (session.event_count or 0) + 1
            session.total_weight_grams = (session.total_weight_grams or 0) + event.weight_grams
            session.save(update_fields=["event_count", "total_weight_grams", "updated_at"])
            messages.success(request, _("Event reactivated."))
        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url:
            return redirect(next_url)
        if session.is_active:
            return redirect("scales:session_detail", pk=session.pk)
        return redirect("scales:session_list")


class SessionCloseView(LoginRequiredMixin, View):
    def post(self, request, pk):
        session = get_object_or_404(DisassemblySession, pk=pk, is_active=True)
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
        session = get_object_or_404(DisassemblySession, pk=pk, is_active=True)
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
            qs = qs.filter(db_models.Q(plu_code__icontains=search) | db_models.Q(name__icontains=search))
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
        events = WeighingEvent.objects.filter(offline_batch_id=batch.batch_id, is_active=True).order_by(
            "scale_timestamp"
        )[:200]
        animals = Animal.objects.filter(status__in=["carcass_ready", "disassembled", "slaughtered"]).order_by(
            "-slaughter_date"
        )[:100]
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
            session.animals.set([animal])
            reconciled_events = WeighingEvent.objects.filter(offline_batch_id=batch.batch_id, is_active=True)
            reconciled_events.update(session=session, animal=animal)
            first_reconciled_event = reconciled_events.select_related("session", "animal").first()
            if first_reconciled_event:
                maybe_mark_event_animals_disassembled(first_reconciled_event)
            batch.status = "reconciled"
            batch.reconciled_to_session = session
            batch.reconciled_at = timezone.now()
            batch.reconciled_by = request.user.get_full_name() or str(request.user)
            batch.save(
                update_fields=["status", "reconciled_to_session", "reconciled_at", "reconciled_by", "updated_at"]
            )
        messages.success(request, _("Batch reconciled to animal %(tag)s.") % {"tag": animal.identification_tag})
        return redirect("scales:orphaned_batch_list")
