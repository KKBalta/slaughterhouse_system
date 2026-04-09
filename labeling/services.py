from django.db import transaction

from .models import AnimalLabel, CustomLabel


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
