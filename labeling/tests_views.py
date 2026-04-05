from io import BytesIO
from types import SimpleNamespace

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import FileResponse
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from labeling.models import AnimalLabel, CustomLabel
from labeling.views import TestPRNGenerationView as PRNGenerationView
from processing.models import DisassemblyCut

pytestmark = pytest.mark.django_db


def _auth_get_request(user, path="/", query_data=None):
    factory = RequestFactory()
    request = factory.get(path, query_data or {})
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@pytest.fixture
def auth_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def slaughtered_animal(animal_factory):
    animal = animal_factory(animal_type="cattle", status="received")
    animal.perform_slaughter()
    animal.save()
    return animal


@pytest.fixture
def animal_label(admin_user, slaughtered_animal):
    return AnimalLabel.objects.create(
        animal=slaughtered_animal,
        label_type="hot_carcass",
        printed_by=admin_user,
        prn_content="PRN-CONTENT",
        bat_content="BAT-CONTENT",
    )


def _create_custom_label(admin_user):
    today = timezone.now().date()
    return CustomLabel.objects.create(
        uretici="Acme",
        kupe_no="TR-001",
        kesim_tarihi=today,
        stt=today,
        cinsi="SIGIR",
        weight="123.45",
        sakatat_status="0.51",
        printed_by=admin_user,
        prn_content="PRN-CUSTOM",
        bat_content="BAT-CUSTOM",
    )


def test_animal_label_list_view_filters_by_animal(auth_client, animal_factory, animal_label):
    other = animal_factory(animal_type="sheep")
    AnimalLabel.objects.create(animal=other, label_type="hot_carcass", prn_content="OTHER", bat_content="OTHER")

    response = auth_client.get(reverse("labeling:animal_label_list", kwargs={"animal_id": animal_label.animal_id}))

    assert response.status_code == 200
    assert response.context["animal"] == animal_label.animal
    labels = list(response.context["labels"])
    assert labels == [animal_label]


def test_generate_animal_label_rejects_received_animals(auth_client, animal_factory):
    animal = animal_factory(animal_type="cattle", status="received")

    response = auth_client.post(reverse("labeling:generate_animal_label", kwargs={"animal_id": animal.pk}))

    assert response.status_code == 302
    assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal.pk})


def test_generate_animal_label_success_redirects_to_detail(auth_client, slaughtered_animal, mocker):
    mock_label = SimpleNamespace(pk="00000000-0000-0000-0000-000000000111")
    mock_create = mocker.patch("labeling.views.create_animal_label", return_value=mock_label)

    response = auth_client.post(
        reverse("labeling:generate_animal_label", kwargs={"animal_id": slaughtered_animal.pk}),
        {"label_type": "hot_carcass"},
    )

    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": mock_label.pk})
    mock_create.assert_called_once()


def test_generate_animal_label_error_redirects_back(auth_client, slaughtered_animal, mocker):
    mocker.patch("labeling.views.create_animal_label", side_effect=Exception("printer failed"))

    response = auth_client.post(reverse("labeling:generate_animal_label", kwargs={"animal_id": slaughtered_animal.pk}))

    assert response.status_code == 302
    assert response.url == reverse("processing:animal_detail", kwargs={"pk": slaughtered_animal.pk})


def test_generate_cut_label_success_and_error(auth_client, slaughtered_animal, mocker):
    cut = DisassemblyCut.objects.create(animal=slaughtered_animal, cut_name="ANTREKOT", weight_kg="5.00")
    mock_label = SimpleNamespace(pk="00000000-0000-0000-0000-000000000222")
    mock_create = mocker.patch("labeling.utils.create_cut_label", return_value=mock_label)

    response = auth_client.post(reverse("labeling:generate_cut_label", kwargs={"cut_id": cut.pk}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": mock_label.pk})
    mock_create.assert_called_once()

    mocker.patch("labeling.utils.create_cut_label", side_effect=Exception("cut failed"))
    response = auth_client.post(reverse("labeling:generate_cut_label", kwargs={"cut_id": cut.pk}))
    assert response.status_code == 302
    assert response.url == reverse("processing:animal_detail", kwargs={"pk": slaughtered_animal.pk})


def test_animal_label_detail_view_exposes_animal(auth_client, animal_label):
    response = auth_client.get(reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk}))

    assert response.status_code == 200
    assert response.context["label"] == animal_label
    assert response.context["animal"] == animal_label.animal


def test_download_animal_label_enhanced_bat_returns_file(auth_client, animal_label, mocker):
    mocker.patch("labeling.views.generate_enhanced_printer_config_bat", return_value="ENHANCED-BAT")

    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "bat"}),
        {"enhanced": "true"},
    )

    assert response.status_code == 200
    assert response.content == b"ENHANCED-BAT"
    assert "enhanced_print_label" in response["Content-Disposition"]


def test_download_animal_label_standard_download_formats(auth_client, animal_label, mocker):
    mocker.patch(
        "labeling.views.get_animal_label_download_data",
        return_value={
            "content": "PRN-DATA",
            "content_type": "application/octet-stream",
            "filename": "label.prn",
        },
    )

    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "prn"})
    )

    assert response.status_code == 200
    assert response.content == b"PRN-DATA"
    assert response["Content-Disposition"] == 'attachment; filename="label.prn"'


def test_download_animal_label_pdf_returns_file_response(auth_client, animal_label, mocker):
    animal_label.pdf_file = "animal_labels/pdf/test.pdf"
    animal_label.save(update_fields=["pdf_file"])
    mocker.patch(
        "labeling.views.get_animal_label_download_data",
        return_value={
            "content_type": "application/pdf",
            "filename": "label.pdf",
        },
    )
    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=True)
    mocker.patch("django.core.files.storage.FileSystemStorage.open", return_value=BytesIO(b"%PDF-1.4"))

    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "pdf"})
    )

    assert isinstance(response, FileResponse)
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="label.pdf"'


def test_download_animal_label_pdf_missing_or_error_redirects(auth_client, animal_label, mocker):
    animal_label.pdf_file = "animal_labels/pdf/missing.pdf"
    animal_label.save(update_fields=["pdf_file"])
    mocker.patch(
        "labeling.views.get_animal_label_download_data",
        return_value={
            "content_type": "application/pdf",
            "filename": "label.pdf",
        },
    )
    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=False)

    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "pdf"})
    )
    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk})

    mocker.patch("labeling.views.get_animal_label_download_data", side_effect=Exception("boom"))
    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "prn"})
    )
    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk})


def test_preview_animal_label_supports_prn_pdf_and_errors(auth_client, slaughtered_animal, mocker):
    mocker.patch("labeling.views.generate_tspl_prn_label", return_value="PRN-PREVIEW")
    response = auth_client.get(
        reverse("labeling:preview_animal_label", kwargs={"animal_id": slaughtered_animal.pk}),
        {"format": "prn"},
    )
    assert response.status_code == 200
    assert response.content == b"PRN-PREVIEW"

    mocker.patch("labeling.views.generate_pdf_label", return_value=BytesIO(b"%PDF-preview"))
    response = auth_client.get(
        reverse("labeling:preview_animal_label", kwargs={"animal_id": slaughtered_animal.pk}),
        {"format": "pdf"},
    )
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("inline; filename=")

    response = auth_client.get(
        reverse("labeling:preview_animal_label", kwargs={"animal_id": slaughtered_animal.pk}),
        {"format": "svg"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Unsupported format"

    mocker.patch("labeling.views.generate_tspl_prn_label", side_effect=Exception("preview failed"))
    response = auth_client.get(
        reverse("labeling:preview_animal_label", kwargs={"animal_id": slaughtered_animal.pk}),
        {"format": "prn"},
    )
    assert response.status_code == 500
    assert response.json()["error"] == "preview failed"


def test_batch_generate_labels_handles_empty_success_and_errors(
    auth_client, admin_user, slaughter_order_factory, animal_factory, mocker
):
    order = slaughter_order_factory()
    first = animal_factory(slaughter_order=order, animal_type="cattle", status="slaughtered")
    second = animal_factory(slaughter_order=order, animal_type="cattle", status="slaughtered")
    wrong_order_animal = animal_factory(animal_type="sheep", status="slaughtered")
    existing = AnimalLabel.objects.create(
        animal=first, label_type="hot_carcass", prn_content="EXIST", bat_content="EXIST"
    )
    mock_new_label = AnimalLabel.objects.create(
        animal=second,
        label_type="cold_carcass",
        prn_content="NEW",
        bat_content="NEW",
    )
    mock_create = mocker.patch("labeling.views.create_animal_label", return_value=mock_new_label)

    response = auth_client.post(reverse("labeling:batch_generate_labels", kwargs={"order_id": order.pk}), {})
    assert response.status_code == 302
    assert response.url == reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk})

    response = auth_client.post(
        reverse("labeling:batch_generate_labels", kwargs={"order_id": order.pk}),
        {"animal_ids": [str(first.pk), str(second.pk)], "label_type": "hot_carcass"},
    )
    assert response.status_code == 302
    assert response.url == reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk})
    mock_create.assert_called_once_with(animal=second, label_type="hot_carcass", user=admin_user)
    assert existing.pk

    mocker.patch("labeling.views.create_animal_label", side_effect=Exception("batch failed"))
    response = auth_client.post(
        reverse("labeling:batch_generate_labels", kwargs={"order_id": order.pk}),
        {"animal_ids": [str(second.pk), str(wrong_order_animal.pk)], "label_type": "cold_carcass"},
    )
    assert response.status_code == 302
    assert response.url == reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk})


def test_delete_animal_label_handles_success_and_error(auth_client, animal_label, mocker):
    animal_label.pdf_file = "animal_labels/pdf/delete-me.pdf"
    animal_label.save(update_fields=["pdf_file"])
    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=True)
    delete_mock = mocker.patch("django.core.files.storage.FileSystemStorage.delete")

    response = auth_client.post(reverse("labeling:delete_animal_label", kwargs={"label_id": animal_label.pk}))

    assert response.status_code == 302
    assert response.url == reverse("processing:animal_detail", kwargs={"pk": animal_label.animal.pk})
    delete_mock.assert_called_once()
    assert delete_mock.call_args.args[0] == "animal_labels/pdf/delete-me.pdf"
    assert not AnimalLabel.objects.filter(pk=animal_label.pk).exists()

    error_label = AnimalLabel.objects.create(
        animal=animal_label.animal, label_type="cold_carcass", prn_content="X", bat_content="Y"
    )
    mocker.patch.object(AnimalLabel, "delete", side_effect=Exception("delete failed"))
    response = auth_client.post(reverse("labeling:delete_animal_label", kwargs={"label_id": error_label.pk}))
    assert response.status_code == 302
    assert response.url == reverse("processing:animal_detail", kwargs={"pk": error_label.animal.pk})


def test_test_prn_generation_view_success_and_error(admin_user, slaughtered_animal, mocker):
    request = _auth_get_request(admin_user)
    mocker.patch(
        "labeling.utils.generate_animal_label_data",
        return_value={"bowels_status": "good", "siparis_no": "123", "kupe_no": "TAG", "kesim_tarihi": "today"},
    )
    mocker.patch("labeling.views.generate_tspl_prn_label", return_value="PRN-BODY")

    response = PRNGenerationView.as_view()(request, animal_id=slaughtered_animal.pk)

    assert response.status_code == 200
    assert b"PRN GENERATION TEST" in response.content

    request = _auth_get_request(admin_user)
    mocker.patch("labeling.utils.generate_animal_label_data", side_effect=Exception("broken"))
    response = PRNGenerationView.as_view()(request, animal_id=slaughtered_animal.pk)
    assert response.status_code == 200
    assert b"Traceback" in response.content


def test_custom_label_create_view_get_and_post_paths(auth_client, mocker):
    response = auth_client.get(reverse("labeling:custom_label_create"))
    assert response.status_code == 200
    assert "form" in response.context

    mock_label = SimpleNamespace(pk="00000000-0000-0000-0000-000000000333")
    mocker.patch("labeling.views.create_custom_label", return_value=mock_label)
    response = auth_client.post(
        reverse("labeling:custom_label_create"),
        {
            "uretici": "Acme",
            "kupe_no": "TR-123",
            "tuccar": "",
            "kesim_tarihi": "2026-04-01",
            "stt": "2026-04-11",
            "siparis_no": "S-1",
            "cinsi": "SIGIR",
            "weight": "123.45",
            "sakatat_status": "0.51",
            "qr_data": "",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_detail", kwargs={"pk": mock_label.pk})

    mocker.patch("labeling.views.create_custom_label", side_effect=Exception("custom failed"))
    response = auth_client.post(
        reverse("labeling:custom_label_create"),
        {
            "uretici": "Acme",
            "kupe_no": "TR-123",
            "tuccar": "",
            "kesim_tarihi": "2026-04-01",
            "stt": "2026-04-11",
            "siparis_no": "S-1",
            "cinsi": "SIGIR",
            "weight": "123.45",
            "sakatat_status": "0.51",
            "qr_data": "",
        },
    )
    assert response.status_code == 200

    response = auth_client.post(
        reverse("labeling:custom_label_create"),
        {
            "uretici": "",
            "kupe_no": "",
            "kesim_tarihi": "2026-04-11",
            "stt": "2026-04-01",
            "cinsi": "SIGIR",
            "weight": "-1",
        },
    )
    assert response.status_code == 200
    assert response.context["form"].errors


def test_custom_label_list_and_detail_views(auth_client, admin_user):
    label = _create_custom_label(admin_user)

    response = auth_client.get(reverse("labeling:custom_label_list"))
    assert response.status_code == 200
    assert label in list(response.context["labels"])

    response = auth_client.get(reverse("labeling:custom_label_detail", kwargs={"pk": label.pk}))
    assert response.status_code == 200
    assert response.context["label"] == label


def test_download_custom_label_handles_formats_and_errors(auth_client, admin_user, mocker):
    label = _create_custom_label(admin_user)
    mocker.patch(
        "labeling.views.get_custom_label_download_data",
        return_value={
            "content": "CUSTOM-PRN",
            "content_type": "application/octet-stream",
            "filename": "custom.prn",
        },
    )
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "prn"}))
    assert response.status_code == 200
    assert response.content == b"CUSTOM-PRN"

    label.pdf_file = "custom_labels/pdf/test.pdf"
    label.save(update_fields=["pdf_file"])
    mocker.patch(
        "labeling.views.get_custom_label_download_data",
        return_value={
            "content_type": "application/pdf",
            "filename": "custom.pdf",
        },
    )
    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=True)
    mocker.patch("django.core.files.storage.FileSystemStorage.open", return_value=BytesIO(b"%PDF-custom"))
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "pdf"}))
    assert isinstance(response, FileResponse)
    assert response.status_code == 200

    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=False)
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "pdf"}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_detail", kwargs={"pk": label.pk})

    mocker.patch("labeling.views.get_custom_label_download_data", side_effect=Exception("custom boom"))
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "bat"}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_detail", kwargs={"pk": label.pk})


def test_delete_custom_label_handles_success_and_error(auth_client, admin_user, mocker):
    label = _create_custom_label(admin_user)
    label.pdf_file = "custom_labels/pdf/delete-me.pdf"
    label.save(update_fields=["pdf_file"])
    delete_mock = mocker.patch("django.core.files.storage.FileSystemStorage.delete")
    mocker.patch("django.core.files.storage.FileSystemStorage.exists", return_value=True)

    response = auth_client.post(reverse("labeling:delete_custom_label", kwargs={"pk": label.pk}))

    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_list")
    delete_mock.assert_called_once()
    assert delete_mock.call_args.args[0] == "custom_labels/pdf/delete-me.pdf"
    assert not CustomLabel.objects.filter(pk=label.pk).exists()

    label = _create_custom_label(admin_user)
    mocker.patch.object(CustomLabel, "delete", side_effect=Exception("delete failed"))
    response = auth_client.post(reverse("labeling:delete_custom_label", kwargs={"pk": label.pk}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_list")
