from django.db import transaction

from .models import AnimalLabel, CustomLabel

_LABEL_TYPE_TO_ROLE = {
    "hot_carcass": "carcass",
    "cold_carcass": "carcass",
    "final": "meat_cut",
    "cut": "meat_cut",
}


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

    resolved_role = target_role
    if not resolved_role and animal_label:
        resolved_role = _LABEL_TYPE_TO_ROLE.get(animal_label.label_type, "carcass")

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
