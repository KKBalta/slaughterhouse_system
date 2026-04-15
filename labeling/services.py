from django.db import transaction

from .models import AnimalLabel, CustomLabel

LABEL_TYPE_TO_ROLE = {
    "hot_carcass": "carcass",
    "cold_carcass": "carcass",
    "final": "meat_cut",
    "cut": "meat_cut",
}
_LABEL_TYPE_TO_ROLE = LABEL_TYPE_TO_ROLE


def resolve_target_role(
    *, animal_label=None, custom_label=None, target_role: str = ""
) -> str:
    """Match enqueue_print_job role resolution (explicit target_role wins)."""
    if target_role:
        return target_role
    if animal_label:
        return LABEL_TYPE_TO_ROLE.get(animal_label.label_type, "carcass")
    if custom_label:
        return "carcass"
    return ""


def printers_for_role(site, role: str):
    """Printers assigned to role at site (all statuses; inactive/disabled excluded)."""
    from scales.models import Printer

    return Printer.objects.filter(
        site=site, role=role, is_active=True, enabled=True
    ).order_by("priority", "display_name", "local_printer_id")


def enqueue_print_job(
    *,
    site,
    prn_content: str,
    target_role: str = "",
    target_printer=None,
    animal_label=None,
    custom_label=None,
    printed_by=None,
) -> "PrintJob":
    """
    Create a PrintJob for edge dispatch.

    The edge polls GET /api/v1/edge/print-jobs/pending and picks this up
    on its next 5-second cycle. No files are written to disk.
    """
    from labeling.models import PrintJob

    resolved_role = resolve_target_role(
        animal_label=animal_label,
        custom_label=custom_label,
        target_role=target_role,
    )

    item_type = ""
    item_id = None
    if animal_label:
        item_type = resolved_role or "carcass"
        item_id = animal_label.animal_id
    elif custom_label:
        item_type = "animal"
        item_id = custom_label.id

    return PrintJob.objects.create(
        site=site,
        target_printer=target_printer,
        target_role=resolved_role,
        prn_content=prn_content,
        dispatch_mode="edge",
        status="pending",
        item_type=item_type,
        item_id=item_id,
        printed_by=printed_by,
    )


def get_default_label_site():
    """First active Site in the tenant (matches Edge / print job routing)."""
    from scales.models import Site

    return Site.objects.filter(is_active=True).order_by("name").first()


def site_has_dispatchable_printer(site) -> bool:
    """True if an active Edge has at least one enabled printer at this site."""
    from scales.models import EdgeDevice, Printer

    if site is None:
        return False
    edge_ids = EdgeDevice.objects.filter(site=site, is_active=True).values_list("id", flat=True)
    return Printer.objects.filter(edge_id__in=edge_ids, is_active=True, enabled=True).exists()


def get_latest_edge_print_job_for_animal_label(animal_label: AnimalLabel):
    """Most recent edge PrintJob whose TSPL payload matches this label (for UI status)."""
    from labeling.models import PrintJob

    prn = (animal_label.prn_content or "").strip()
    if not prn:
        return None
    return (
        PrintJob.objects.filter(prn_content=prn, dispatch_mode="edge").order_by("-print_date").first()
    )


def get_latest_edge_print_job_for_custom_label(custom_label: CustomLabel):
    from labeling.models import PrintJob

    return (
        PrintJob.objects.filter(item_id=custom_label.pk, item_type="animal", dispatch_mode="edge")
        .order_by("-print_date")
        .first()
    )


def archive_animal_label_record(animal_label: AnimalLabel) -> None:
    animal_label.soft_delete()


def _delete_pdf_file(file_field) -> None:
    if file_field:
        file_field.delete(save=False)


def delete_animal_label_record(animal_label: AnimalLabel) -> None:
    _delete_pdf_file(animal_label.pdf_file)
    animal_label.delete()


def delete_custom_label_record(custom_label: CustomLabel) -> None:
    _delete_pdf_file(custom_label.pdf_file)
    custom_label.delete()


@transaction.atomic
def archive_destination_sensitive_order_labels(order) -> int:
    """
    Archive animal labels that embed order destination data.

    The record and generated files are retained for auditability, but the
    label is hidden from the normal user-facing label history and ignored by
    regeneration checks. Cut labels are excluded because their payload does
    not include the slaughter order destination.
    """
    labels = list(
        AnimalLabel.objects.filter(
            animal__slaughter_order=order,
            cut__isnull=True,
            is_active=True,
        )
    )

    archived_count = 0
    for animal_label in labels:
        archive_animal_label_record(animal_label)
        archived_count += 1

    return archived_count
