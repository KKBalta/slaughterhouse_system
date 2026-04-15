from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import DetailView, ListView, TemplateView, View

from processing.models import Animal
from scales.models import Printer

from .models import AnimalLabel, CustomLabel, LabelTemplate, PrintJob
from .services import (
    delete_animal_label_record,
    delete_custom_label_record,
    enqueue_print_job,
    get_default_label_site,
    get_latest_edge_print_job_for_animal_label,
    get_latest_edge_print_job_for_custom_label,
    printers_for_role,
    resolve_target_role,
    site_has_dispatchable_printer,
)
from .utils import (
    create_animal_label,
    create_custom_label,
    generate_pdf_label,
    generate_tspl_prn_label,
    get_animal_label_download_data,
    get_custom_label_download_data,
)


class LabelAppHomeView(LoginRequiredMixin, TemplateView):
    """Unified labels hub: Edge print queue, then all labels (animal + custom) by date."""

    template_name = "labeling/label_app.html"
    label_table_per_page = 25

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        animal_active = AnimalLabel.objects.filter(is_active=True)
        custom_all = CustomLabel.objects.all()
        context["animal_label_total"] = animal_active.count()
        context["custom_label_total"] = custom_all.count()

        merged = [
            ("animal", pk, print_date)
            for pk, print_date in animal_active.values_list("pk", "print_date")
        ] + [
            ("custom", pk, print_date)
            for pk, print_date in custom_all.values_list("pk", "print_date")
        ]
        merged.sort(key=lambda row: row[2], reverse=True)
        context["label_rows_total"] = len(merged)

        paginator = Paginator(merged, self.label_table_per_page)
        page_obj = paginator.get_page(self.request.GET.get("page"))
        page_slice = list(page_obj.object_list)

        animal_ids = [pk for kind, pk, _ in page_slice if kind == "animal"]
        custom_ids = [pk for kind, pk, _ in page_slice if kind == "custom"]
        animal_map = {
            al.pk: al
            for al in AnimalLabel.objects.filter(pk__in=animal_ids).select_related("animal", "cut")
        }
        custom_map = {cl.pk: cl for cl in CustomLabel.objects.filter(pk__in=custom_ids)}

        label_rows = []
        for kind, pk, dt in page_slice:
            if kind == "animal":
                label_rows.append({"kind": "animal", "label": animal_map[pk], "sort_date": dt})
            else:
                label_rows.append({"kind": "custom", "label": custom_map[pk], "sort_date": dt})
        context["label_rows"] = label_rows
        context["page_obj"] = page_obj

        pj_pending = (
            PrintJob.objects.filter(status="pending", dispatch_mode="edge", site__is_active=True)
            .select_related("site")
            .order_by("print_date")
        )
        pj_dispatched = (
            PrintJob.objects.filter(status="dispatched", dispatch_mode="edge", site__is_active=True)
            .select_related("site", "claimed_by_edge")
            .order_by("-edge_received_at", "print_date")
        )
        context["pending_print_jobs"] = list(pj_pending[:25])
        context["pending_print_job_total"] = pj_pending.count()
        context["dispatched_print_jobs"] = list(pj_dispatched[:25])
        context["dispatched_print_job_total"] = pj_dispatched.count()

        site = get_default_label_site()
        context["label_site"] = site
        context["edge_dispatch_available"] = site_has_dispatchable_printer(site)

        from users.policies import can_manage_tenant_users

        context["can_manage_edge"] = can_manage_tenant_users(self.request.user)
        return context


class CustomLabelListRedirectView(LoginRequiredMixin, View):
    """Backward-compatible URL: /labeling/custom/ → labels hub (queue + merged table)."""

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(reverse("labeling:label_app"))


class AnimalLabelListView(LoginRequiredMixin, ListView):
    """List all animal labels for a specific animal."""

    model = AnimalLabel
    template_name = "labeling/animal_label_list.html"
    context_object_name = "labels"

    def get_queryset(self):
        animal_id = self.kwargs.get("animal_id")
        return AnimalLabel.objects.filter(animal_id=animal_id, is_active=True).order_by("-print_date")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        animal_id = self.kwargs.get("animal_id")
        context["animal"] = get_object_or_404(Animal, id=animal_id)
        return context


class GenerateAnimalLabelView(LoginRequiredMixin, View):
    """Generate and create a new animal label with PRN and BAT file support."""

    def post(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        label_type = request.POST.get("label_type", "hot_carcass")

        # Check if animal has been slaughtered for hot carcass labels
        if label_type == "hot_carcass" and animal.status not in [
            "slaughtered",
            "carcass_ready",
            "disassembled",
            "packaged",
            "delivered",
        ]:
            messages.error(request, _("Hot carcass labels can only be generated for slaughtered animals."))
            return redirect("processing:animal_detail", pk=animal.pk)

        try:
            # Create the label with default printer settings
            animal_label = create_animal_label(animal=animal, label_type=label_type, user=request.user)

            messages.success(
                request,
                _("Label created. Use “Print via Edge” on the label page to send it to your site printer."),
            )
            return redirect("labeling:animal_label_detail", pk=animal_label.pk)

        except Exception as e:
            messages.error(request, _("Error generating label: %(error)s") % {"error": str(e)})
            return redirect("processing:animal_detail", pk=animal.pk)


class GenerateCutLabelView(LoginRequiredMixin, View):
    """Generate and create a new label for a disassembly cut."""

    def post(self, request, cut_id):
        from processing.models import DisassemblyCut

        cut = get_object_or_404(DisassemblyCut, id=cut_id)

        try:
            # Create the label with default printer settings
            # We reuse create_animal_label but adapted for cuts?
            # Actually create_animal_label is specific to Animal model.
            # We should probably create a create_cut_label function in utils or handle it here.
            # Let's check utils.py again. create_animal_label creates an AnimalLabel.
            # We might need a CutLabel model or reuse AnimalLabel if it can link to a cut?
            # The AnimalLabel model likely has a ForeignKey to Animal.
            # If we want to use AnimalLabel, we might need to add a foreign key to DisassemblyCut or make it generic.
            # However, looking at the existing code, AnimalLabel is tied to Animal.
            # For now, let's assume we are generating a label that is associated with the Animal but contains Cut info.
            # Or maybe we should create a new function create_cut_label in utils.py that creates an AnimalLabel
            # but stores the cut info in the PRN content.

            # Let's implement create_cut_label in utils.py first or here.
            # But wait, I missed checking if AnimalLabel supports cuts.
            # Let's assume for now we will use AnimalLabel and just store the cut-specific PRN content.
            # The label_type can be 'cut'.

            from .utils import create_cut_label

            animal_label = create_cut_label(cut=cut, user=request.user)

            messages.success(request, _("Cut label generated successfully!"))
            return redirect("labeling:animal_label_detail", pk=animal_label.pk)

        except Exception as e:
            messages.error(request, _("Error generating label: %(error)s") % {"error": str(e)})
            return redirect("processing:animal_detail", pk=cut.animal.pk)


class AnimalLabelDetailView(LoginRequiredMixin, DetailView):
    """Display details of a specific animal label."""

    model = AnimalLabel
    template_name = "labeling/animal_label_detail.html"
    context_object_name = "label"

    def get_queryset(self):
        return AnimalLabel.objects.filter(is_active=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["animal"] = self.object.animal
        site = get_default_label_site()
        context["label_site"] = site
        context["edge_dispatch_available"] = site_has_dispatchable_printer(site)
        context["edge_print_job"] = get_latest_edge_print_job_for_animal_label(self.object)
        target_role = resolve_target_role(animal_label=self.object)
        context["target_role"] = target_role
        context["target_role_display"] = dict(Printer.ROLE_CHOICES).get(target_role, target_role)
        context["target_role_printers"] = (
            list(printers_for_role(site, target_role)) if site else []
        )
        return context


class PrintAnimalLabelToEdgeView(LoginRequiredMixin, View):
    """Queue a PrintJob for the site's Edge device (TSPL payload only; no file download)."""

    def post(self, request, pk):
        label = get_object_or_404(AnimalLabel, pk=pk, is_active=True)
        site = get_default_label_site()
        if not site:
            messages.error(request, _("No site is configured for this tenant."))
            return redirect("labeling:animal_label_detail", pk=pk)
        if not site_has_dispatchable_printer(site):
            messages.error(
                request,
                _(
                    "No Edge printer is available. Register printers from the Edge device first "
                    "(printer inventory sync)."
                ),
            )
            return redirect("labeling:animal_label_detail", pk=pk)
        if not (label.prn_content or "").strip():
            messages.error(request, _("This label has no printable data."))
            return redirect("labeling:animal_label_detail", pk=pk)
        enqueue_print_job(
            site=site,
            prn_content=label.prn_content,
            animal_label=label,
            printed_by=request.user,
        )
        messages.success(request, _("Print job queued. The Edge device will pick it up shortly."))
        return redirect("labeling:animal_label_detail", pk=pk)


class DownloadAnimalLabelView(LoginRequiredMixin, View):
    """Download animal label PDF only (printing is via Edge)."""

    def get(self, request, label_id, format_type="pdf"):
        animal_label = get_object_or_404(AnimalLabel, id=label_id, is_active=True)
        fmt = (format_type or "pdf").lower()
        if fmt != "pdf":
            messages.error(
                request,
                _("Only PDF download is available. Use “Print via Edge” to print at the site."),
            )
            return redirect("labeling:animal_label_detail", pk=label_id)

        try:
            download_data = get_animal_label_download_data(animal_label, "pdf")
            if animal_label.pdf_file and default_storage.exists(animal_label.pdf_file.name):
                response = FileResponse(
                    default_storage.open(animal_label.pdf_file.name, "rb"),
                    content_type=download_data["content_type"],
                )
                response["Content-Disposition"] = f'attachment; filename="{download_data["filename"]}"'
                return response
            messages.error(request, _("PDF file not found."))
            return redirect("labeling:animal_label_detail", pk=label_id)

        except Exception as e:
            messages.error(request, _("Error downloading label: %(error)s") % {"error": str(e)})
            return redirect("labeling:animal_label_detail", pk=label_id)


class PreviewAnimalLabelView(LoginRequiredMixin, View):
    """Preview animal label without creating a permanent record."""

    def get(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        label_type = request.GET.get("label_type", "hot_carcass")
        format_type = request.GET.get("format", "prn")

        try:
            if format_type.lower() in ["bat", "prn"]:
                prn_content = generate_tspl_prn_label(animal, label_type)
                return HttpResponse(prn_content, content_type="text/plain")
            elif format_type.lower() == "pdf":
                pdf_buffer = generate_pdf_label(animal, label_type)
                response = HttpResponse(pdf_buffer.getvalue(), content_type="application/pdf")
                response["Content-Disposition"] = (
                    f'inline; filename="preview_{animal.identification_tag}_{label_type}.pdf"'
                )
                return response
            else:
                return JsonResponse({"error": "Unsupported format"}, status=400)

        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


class BatchGenerateLabelsView(LoginRequiredMixin, View):
    """Generate labels for multiple animals in a slaughter order."""

    def post(self, request, order_id):
        from reception.models import SlaughterOrder

        order = get_object_or_404(SlaughterOrder, id=order_id)
        label_type = request.POST.get("label_type", "hot_carcass")
        animal_ids = request.POST.getlist("animal_ids")

        if not animal_ids:
            messages.error(request, _("Please select at least one animal."))
            return redirect("reception:slaughter_order_detail", pk=order_id)

        created_labels = []
        errors = []

        for animal_id in animal_ids:
            try:
                animal = Animal.objects.get(id=animal_id, slaughter_order=order)

                # Check if label already exists
                existing_label = AnimalLabel.objects.filter(
                    animal=animal,
                    label_type=label_type,
                    is_active=True,
                ).first()

                if existing_label:
                    created_labels.append(existing_label)
                else:
                    # Create new label
                    animal_label = create_animal_label(animal=animal, label_type=label_type, user=request.user)
                    created_labels.append(animal_label)
                    site = get_default_label_site()
                    if (
                        site
                        and site_has_dispatchable_printer(site)
                        and (animal_label.prn_content or "").strip()
                    ):
                        enqueue_print_job(
                            site=site,
                            prn_content=animal_label.prn_content,
                            animal_label=animal_label,
                            printed_by=request.user,
                        )

            except Animal.DoesNotExist:
                errors.append(f"Animal {animal_id} not found")
            except Exception as e:
                errors.append(f"Error creating label for animal {animal_id}: {str(e)}")

        if created_labels:
            messages.success(request, _("Successfully generated %(count)s labels.") % {"count": len(created_labels)})

        if errors:
            messages.warning(request, _("Some errors occurred: %(errors)s") % {"errors": "; ".join(errors)})

        return redirect("reception:slaughter_order_detail", pk=order_id)


@login_required
def delete_animal_label(request, label_id):
    """Delete an animal label."""
    animal_label = get_object_or_404(AnimalLabel, id=label_id, is_active=True)
    animal_id = animal_label.animal.id

    try:
        delete_animal_label_record(animal_label)
        messages.success(request, _("Label deleted successfully."))

    except Exception as e:
        messages.error(request, _("Error deleting label: %(error)s") % {"error": str(e)})

    return redirect("processing:animal_detail", pk=animal_id)


class LabelTemplateListView(LoginRequiredMixin, ListView):
    """List all available label templates."""

    model = LabelTemplate
    template_name = "labeling/label_template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        return LabelTemplate.objects.filter(target_item_type="animal")


class LabelTemplateDetailView(LoginRequiredMixin, DetailView):
    """Display details of a label template."""

    model = LabelTemplate
    template_name = "labeling/label_template_detail.html"
    context_object_name = "template"


class TestPRNGenerationView(LoginRequiredMixin, View):
    """Test view for PRN generation - for development/testing purposes."""

    def get(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)

        try:
            from .utils import generate_animal_label_data

            # Generate label data
            label_data = generate_animal_label_data(animal)

            # Generate PRN content
            prn_content = generate_tspl_prn_label(animal)

            # Create response with debug info
            debug_info = f"""
=== PRN GENERATION TEST ===
Animal: {animal}
Label Data Fields: {list(label_data.keys())}

Key Values:
- bowels_status: {label_data.get("bowels_status", "N/A")}
- siparis_no (Process No): {label_data.get("siparis_no", "N/A")}
- kupe_no: {label_data.get("kupe_no", "N/A")}
- uretici: {label_data.get("uretici", "N/A")}
- kesim_tarihi: {label_data.get("kesim_tarihi", "N/A")}

PRN Content Length: {len(prn_content)} characters

Checks:
- Contains 'Proses No': {"Proses No" in prn_content}
- Contains 'İşletme No': {"İşletme No" in prn_content}
- Contains bowels_status value: {str(label_data.get("bowels_status", "")) in prn_content}
- Contains siparis_no value: {str(label_data.get("siparis_no", "")) in prn_content}

=== PRN CONTENT (First 1000 chars) ===
{prn_content[:1000]}
...
"""

            return HttpResponse(debug_info, content_type="text/plain")

        except Exception as e:
            import traceback

            error_info = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            return HttpResponse(error_info, content_type="text/plain")


# ============================================
# Custom Label Views
# ============================================


class CustomLabelCreateView(LoginRequiredMixin, View):
    """Create a new custom label with manual data entry."""

    def get(self, request):
        from .forms import CustomLabelForm

        form = CustomLabelForm()
        return self._render_form(request, form)

    def post(self, request):
        from .forms import CustomLabelForm

        form = CustomLabelForm(request.POST)

        if form.is_valid():
            try:
                label_data = {
                    "uretici": form.cleaned_data["uretici"],
                    "kupe_no": form.cleaned_data["kupe_no"],
                    "tuccar": form.cleaned_data.get("tuccar", ""),
                    "kesim_tarihi": form.cleaned_data["kesim_tarihi"],
                    "stt": form.cleaned_data["stt"],
                    "siparis_no": form.cleaned_data.get("siparis_no", ""),
                    "cinsi": form.cleaned_data["cinsi"],
                    "weight": form.cleaned_data["weight"],
                    "sakatat_status": form.cleaned_data.get("sakatat_status", "0.51"),
                    "qr_data": form.cleaned_data.get("qr_data", ""),
                }

                custom_label = create_custom_label(label_data=label_data, user=request.user)

                messages.success(
                    request,
                    _("Custom label created. Use “Print via Edge” on the label page to print at the site."),
                )
                return redirect("labeling:custom_label_detail", pk=custom_label.pk)

            except Exception as e:
                messages.error(request, _("Error creating label: %(error)s") % {"error": str(e)})
                return self._render_form(request, form)

        return self._render_form(request, form)

    def _render_form(self, request, form):
        from django.shortcuts import render

        return render(request, "labeling/custom_label_form.html", {"form": form})


class CustomLabelDetailView(LoginRequiredMixin, DetailView):
    """Display details of a custom label with download options."""

    model = CustomLabel
    template_name = "labeling/custom_label_detail.html"
    context_object_name = "label"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        site = get_default_label_site()
        context["label_site"] = site
        context["edge_dispatch_available"] = site_has_dispatchable_printer(site)
        context["edge_print_job"] = get_latest_edge_print_job_for_custom_label(self.object)
        target_role = resolve_target_role(custom_label=self.object)
        context["target_role"] = target_role
        context["target_role_display"] = dict(Printer.ROLE_CHOICES).get(target_role, target_role)
        context["target_role_printers"] = (
            list(printers_for_role(site, target_role)) if site else []
        )
        return context


class PrintCustomLabelToEdgeView(LoginRequiredMixin, View):
    """Queue a PrintJob for a custom label."""

    def post(self, request, pk):
        label = get_object_or_404(CustomLabel, pk=pk)
        site = get_default_label_site()
        if not site:
            messages.error(request, _("No site is configured for this tenant."))
            return redirect("labeling:custom_label_detail", pk=pk)
        if not site_has_dispatchable_printer(site):
            messages.error(
                request,
                _(
                    "No Edge printer is available. Register printers from the Edge device first "
                    "(printer inventory sync)."
                ),
            )
            return redirect("labeling:custom_label_detail", pk=pk)
        if not (label.prn_content or "").strip():
            messages.error(request, _("This label has no printable data."))
            return redirect("labeling:custom_label_detail", pk=pk)
        enqueue_print_job(
            site=site,
            prn_content=label.prn_content,
            custom_label=label,
            printed_by=request.user,
        )
        messages.success(request, _("Print job queued. The Edge device will pick it up shortly."))
        return redirect("labeling:custom_label_detail", pk=pk)


class DownloadCustomLabelView(LoginRequiredMixin, View):
    """Download custom label PDF only (printing is via Edge)."""

    def get(self, request, pk, format_type="pdf"):
        custom_label = get_object_or_404(CustomLabel, id=pk)
        fmt = (format_type or "pdf").lower()
        if fmt != "pdf":
            messages.error(
                request,
                _("Only PDF download is available. Use “Print via Edge” to print at the site."),
            )
            return redirect("labeling:custom_label_detail", pk=pk)

        try:
            download_data = get_custom_label_download_data(custom_label, "pdf")
            if custom_label.pdf_file and default_storage.exists(custom_label.pdf_file.name):
                response = FileResponse(
                    default_storage.open(custom_label.pdf_file.name, "rb"),
                    content_type=download_data["content_type"],
                )
                response["Content-Disposition"] = f'attachment; filename="{download_data["filename"]}"'
                return response
            messages.error(request, _("PDF file not found."))
            return redirect("labeling:custom_label_detail", pk=pk)

        except Exception as e:
            messages.error(request, _("Error downloading label: %(error)s") % {"error": str(e)})
            return redirect("labeling:custom_label_detail", pk=pk)


@login_required
def delete_custom_label(request, pk):
    """Delete a custom label."""
    custom_label = get_object_or_404(CustomLabel, id=pk)

    try:
        delete_custom_label_record(custom_label)
        messages.success(request, _("Custom label deleted successfully."))

    except Exception as e:
        messages.error(request, _("Error deleting label: %(error)s") % {"error": str(e)})

    return redirect("labeling:label_app")
