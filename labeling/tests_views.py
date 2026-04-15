from io import BytesIO
from types import SimpleNamespace

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import FileResponse
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from labeling.models import AnimalLabel, CustomLabel, PrintJob
from labeling.views import LabelAppHomeView, TestPRNGenerationView as PRNGenerationView
from processing.models import DisassemblyCut
from scales.models import EdgeDevice, Printer, Site

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


def test_animal_label_list_view_hides_archived_labels(auth_client, animal_label):
    animal_label.soft_delete()

    response = auth_client.get(reverse("labeling:animal_label_list", kwargs={"animal_id": animal_label.animal_id}))

    assert response.status_code == 200
    assert list(response.context["labels"]) == []


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
    assert "edge_dispatch_available" in response.context
    assert "edge_print_job" in response.context


@pytest.fixture
def site_with_carcass_printers_for_hint(db):
    site = Site.objects.create(name="Hint Site", address="")
    edge = EdgeDevice.objects.create(site=site, name="HintEdge", is_active=True)
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="c-low",
        host="192.168.1.1",
        port=9100,
        role="carcass",
        priority=100,
        enabled=True,
        is_active=True,
        status="online",
    )
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="c-high",
        host="192.168.1.2",
        port=9100,
        role="carcass",
        priority=200,
        enabled=True,
        is_active=True,
        status="online",
    )
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="meat",
        host="192.168.1.3",
        port=9100,
        role="meat_cut",
        priority=10,
        enabled=True,
        is_active=True,
    )
    return site


def test_animal_label_detail_target_role_printers_context(
    auth_client, animal_label, site_with_carcass_printers_for_hint, mocker
):
    mocker.patch(
        "labeling.views.get_default_label_site", return_value=site_with_carcass_printers_for_hint
    )
    response = auth_client.get(reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk}))
    assert response.status_code == 200
    assert response.context["target_role"] == "carcass"
    printers = response.context["target_role_printers"]
    assert len(printers) == 2
    assert printers[0].priority == 100
    assert printers[0].local_printer_id == "c-low"


def test_animal_label_detail_empty_target_role_printers(auth_client, animal_label, mocker):
    site = Site.objects.create(name="No Carcass Printers", address="")
    edge = EdgeDevice.objects.create(site=site, name="E-hint", is_active=True)
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="x",
        host="1.1.1.1",
        port=9100,
        role="meat_cut",
        enabled=True,
        is_active=True,
    )
    mocker.patch("labeling.views.get_default_label_site", return_value=site)
    response = auth_client.get(reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk}))
    assert response.context["target_role_printers"] == []


@pytest.fixture
def site_with_edge_printer(db):
    site = Site.objects.create(name="Print Site", address="")
    edge = EdgeDevice.objects.create(site=site, name="E1", is_active=True)
    Printer.objects.create(
        edge=edge,
        site=site,
        local_printer_id="p1",
        host="192.168.1.10",
        port=9100,
        role="carcass",
        enabled=True,
        is_active=True,
    )
    return site


def test_print_animal_label_to_edge_queues_job(auth_client, animal_label, site_with_edge_printer, mocker):
    mocker.patch("labeling.views.get_default_label_site", return_value=site_with_edge_printer)
    animal_label.prn_content = "TSPL-LINE-1"
    animal_label.save(update_fields=["prn_content"])

    response = auth_client.post(reverse("labeling:print_animal_label", kwargs={"pk": animal_label.pk}))

    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk})
    job = PrintJob.objects.get()
    assert job.site_id == site_with_edge_printer.id
    assert job.prn_content == "TSPL-LINE-1"
    assert job.status == "pending"


def test_print_animal_label_to_edge_requires_printer(auth_client, animal_label, db):
    Site.objects.create(name="Lonely", address="")
    animal_label.prn_content = "X"
    animal_label.save(update_fields=["prn_content"])

    response = auth_client.post(reverse("labeling:print_animal_label", kwargs={"pk": animal_label.pk}))

    assert response.status_code == 302
    assert PrintJob.objects.count() == 0


def test_print_custom_label_to_edge_queues_job(auth_client, admin_user, site_with_edge_printer, mocker):
    mocker.patch("labeling.views.get_default_label_site", return_value=site_with_edge_printer)
    label = _create_custom_label(admin_user)
    label.prn_content = "CUSTOM-TSPL"
    label.save(update_fields=["prn_content"])

    response = auth_client.post(reverse("labeling:print_custom_label", kwargs={"pk": label.pk}))

    assert response.status_code == 302
    job = PrintJob.objects.get()
    assert job.item_id == label.pk
    assert job.prn_content == "CUSTOM-TSPL"
    assert job.target_role == "carcass"


def test_download_animal_label_non_pdf_redirects(auth_client, animal_label):
    response = auth_client.get(
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "prn"})
    )
    assert response.status_code == 302
    assert response.url == reverse("labeling:animal_label_detail", kwargs={"pk": animal_label.pk})


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
        reverse("labeling:download_animal_label", kwargs={"label_id": animal_label.pk, "format_type": "pdf"})
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


def test_batch_generate_labels_enqueues_print_when_edge_ready(
    auth_client, admin_user, slaughter_order_factory, animal_factory, mocker, site_with_edge_printer
):
    mocker.patch("labeling.views.get_default_label_site", return_value=site_with_edge_printer)
    order = slaughter_order_factory()
    second = animal_factory(slaughter_order=order, animal_type="cattle", status="slaughtered")

    def fake_create(*, animal, label_type, user):
        return AnimalLabel.objects.create(
            animal=animal,
            label_type=label_type,
            prn_content="BATCH-PRN",
            bat_content="",
            printed_by=user,
        )

    mocker.patch("labeling.views.create_animal_label", side_effect=fake_create)
    enqueue_mock = mocker.patch("labeling.views.enqueue_print_job")

    response = auth_client.post(
        reverse("labeling:batch_generate_labels", kwargs={"order_id": order.pk}),
        {"animal_ids": [str(second.pk)], "label_type": "cold_carcass"},
    )
    assert response.status_code == 302
    enqueue_mock.assert_called_once()
    assert enqueue_mock.call_args.kwargs["site"] == site_with_edge_printer
    assert enqueue_mock.call_args.kwargs["prn_content"] == "BATCH-PRN"


def test_batch_generate_labels_ignores_archived_existing_label(
    auth_client, admin_user, slaughter_order_factory, animal_factory, mocker
):
    order = slaughter_order_factory()
    animal = animal_factory(slaughter_order=order, animal_type="cattle")
    archived_label = AnimalLabel.objects.create(
        animal=animal,
        label_type="hot_carcass",
        prn_content="OLD",
        bat_content="OLD",
    )
    archived_label.soft_delete()

    replacement = AnimalLabel.objects.create(
        animal=animal,
        label_type="cold_carcass",
        prn_content="NEW",
        bat_content="NEW",
    )
    mock_create = mocker.patch("labeling.views.create_animal_label", return_value=replacement)

    response = auth_client.post(
        reverse("labeling:batch_generate_labels", kwargs={"order_id": order.pk}),
        {"animal_ids": [str(animal.pk)], "label_type": "hot_carcass"},
    )

    assert response.status_code == 302
    assert response.url == reverse("reception:slaughter_order_detail", kwargs={"pk": order.pk})
    mock_create.assert_called_once_with(animal=animal, label_type="hot_carcass", user=admin_user)


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


def test_custom_label_list_redirects_to_label_app(auth_client):
    response = auth_client.get(reverse("labeling:custom_label_list"))
    assert response.status_code == 302
    assert response.url == reverse("labeling:label_app")


def test_label_app_requires_login(client):
    response = client.get(reverse("labeling:label_app"))
    assert response.status_code == 302
    assert "login" in response.url


def test_label_app_lists_custom_and_animal_labels(auth_client, admin_user, animal_label):
    custom = _create_custom_label(admin_user)

    response = auth_client.get(reverse("labeling:label_app"))
    assert response.status_code == 200
    ctx = response.context
    rows = ctx["label_rows"]
    animal_pks = {r["label"].pk for r in rows if r["kind"] == "animal"}
    custom_pks = {r["label"].pk for r in rows if r["kind"] == "custom"}
    assert animal_label.pk in animal_pks
    assert custom.pk in custom_pks
    assert ctx["label_rows_total"] >= 2
    page_obj = ctx["page_obj"]
    assert page_obj.paginator.count == ctx["label_rows_total"]
    assert page_obj.paginator.per_page == LabelAppHomeView.label_table_per_page
    assert "pending_print_jobs" in ctx
    assert "dispatched_print_jobs" in ctx
    assert "completed_print_jobs" in ctx
    assert "completed_print_job_total" in ctx
    assert "edge_dispatch_available" in ctx
    assert "can_manage_edge" in ctx


def test_label_app_label_table_pagination(auth_client, admin_user, animal_label, mocker):
    mocker.patch.object(LabelAppHomeView, "label_table_per_page", 1)
    _create_custom_label(admin_user)
    _create_custom_label(admin_user)

    response = auth_client.get(reverse("labeling:label_app"), {"page": 2})
    assert response.status_code == 200
    ctx = response.context
    assert len(ctx["label_rows"]) == 1
    assert ctx["page_obj"].number == 2
    assert ctx["page_obj"].paginator.num_pages == 3


def test_cancel_pending_print_job_post(auth_client, site_with_edge_printer):
    job = PrintJob.objects.create(
        site=site_with_edge_printer,
        status="pending",
        dispatch_mode="edge",
        prn_content="q",
        target_role="carcass",
    )
    response = auth_client.post(
        reverse("labeling:cancel_pending_print_job", kwargs={"pk": job.pk}),
    )
    assert response.status_code == 302
    assert response.url == f"{reverse('labeling:label_app')}#print-queue"
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_cancel_pending_print_job_rejects_non_pending(auth_client, site_with_edge_printer):
    job = PrintJob.objects.create(
        site=site_with_edge_printer,
        status="completed",
        dispatch_mode="edge",
        prn_content="q",
    )
    response = auth_client.post(
        reverse("labeling:cancel_pending_print_job", kwargs={"pk": job.pk}),
    )
    assert response.status_code == 302
    assert response.url == f"{reverse('labeling:label_app')}#print-queue"
    job.refresh_from_db()
    assert job.status == "completed"


def test_cancel_pending_print_job_respects_safe_next(auth_client, site_with_edge_printer):
    job = PrintJob.objects.create(
        site=site_with_edge_printer,
        status="pending",
        dispatch_mode="edge",
        prn_content="q",
        target_role="carcass",
    )
    next_path = f"{reverse('scales:edge_management')}?site_id=1#cloud-print-queue"
    response = auth_client.post(
        reverse("labeling:cancel_pending_print_job", kwargs={"pk": job.pk}),
        {"next": next_path},
    )
    assert response.status_code == 302
    assert response.url == next_path


def test_cancel_pending_print_job_ignores_unsafe_next(auth_client, site_with_edge_printer):
    job = PrintJob.objects.create(
        site=site_with_edge_printer,
        status="pending",
        dispatch_mode="edge",
        prn_content="q",
        target_role="carcass",
    )
    response = auth_client.post(
        reverse("labeling:cancel_pending_print_job", kwargs={"pk": job.pk}),
        {"next": "https://evil.example/phish"},
    )
    assert response.status_code == 302
    assert response.url == f"{reverse('labeling:label_app')}#print-queue"
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_custom_label_detail_view(auth_client, admin_user):
    label = _create_custom_label(admin_user)

    response = auth_client.get(reverse("labeling:custom_label_detail", kwargs={"pk": label.pk}))
    assert response.status_code == 200
    assert response.context["label"] == label
    assert "edge_dispatch_available" in response.context


def test_custom_label_detail_target_role_printers_context(
    auth_client, admin_user, site_with_carcass_printers_for_hint, mocker
):
    mocker.patch(
        "labeling.views.get_default_label_site", return_value=site_with_carcass_printers_for_hint
    )
    label = _create_custom_label(admin_user)
    response = auth_client.get(reverse("labeling:custom_label_detail", kwargs={"pk": label.pk}))
    assert response.status_code == 200
    assert response.context["target_role"] == "carcass"
    assert len(response.context["target_role_printers"]) == 2
    assert response.context["target_role_printers"][0].priority == 100


def test_download_custom_label_handles_formats_and_errors(auth_client, admin_user, mocker):
    label = _create_custom_label(admin_user)
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "prn"}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:custom_label_detail", kwargs={"pk": label.pk})

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
    response = auth_client.get(reverse("labeling:download_custom_label", kwargs={"pk": label.pk, "format_type": "pdf"}))
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
    assert response.url == reverse("labeling:label_app")
    delete_mock.assert_called_once()
    assert delete_mock.call_args.args[0] == "custom_labels/pdf/delete-me.pdf"
    assert not CustomLabel.objects.filter(pk=label.pk).exists()

    label = _create_custom_label(admin_user)
    mocker.patch.object(CustomLabel, "delete", side_effect=Exception("delete failed"))
    response = auth_client.post(reverse("labeling:delete_custom_label", kwargs={"pk": label.pk}))
    assert response.status_code == 302
    assert response.url == reverse("labeling:label_app")
