from django.urls import path

from . import views

app_name = "labeling"

urlpatterns = [
    # Animal Label Management
    path("animals/<uuid:animal_id>/labels/", views.AnimalLabelListView.as_view(), name="animal_label_list"),
    path(
        "animals/<uuid:animal_id>/generate-label/",
        views.GenerateAnimalLabelView.as_view(),
        name="generate_animal_label",
    ),
    path(
        "animals/<uuid:animal_id>/preview-label/", views.PreviewAnimalLabelView.as_view(), name="preview_animal_label"
    ),
    path("animals/<uuid:animal_id>/test-prn/", views.TestPRNGenerationView.as_view(), name="test_prn_generation"),
    path("cuts/<uuid:cut_id>/generate-label/", views.GenerateCutLabelView.as_view(), name="generate_cut_label"),
    # Label Detail and Download
    path("labels/<uuid:pk>/", views.AnimalLabelDetailView.as_view(), name="animal_label_detail"),
    path(
        "labels/<uuid:label_id>/download/<str:format_type>/",
        views.DownloadAnimalLabelView.as_view(),
        name="download_animal_label",
    ),
    path("labels/<uuid:label_id>/delete/", views.delete_animal_label, name="delete_animal_label"),
    # Batch Operations
    path(
        "orders/<uuid:order_id>/batch-generate/", views.BatchGenerateLabelsView.as_view(), name="batch_generate_labels"
    ),
    # Label Templates
    path("templates/", views.LabelTemplateListView.as_view(), name="label_template_list"),
    path("templates/<uuid:pk>/", views.LabelTemplateDetailView.as_view(), name="label_template_detail"),
]
