from django.urls import path

from apps.workspace import views

urlpatterns = [
    path("", views.home, name="home"),
    path("identity/", views.identity, name="identity"),
    path("labels/", views.global_labels_page, name="global-labels"),
    path("settings/", views.account_settings_page, name="account-settings"),
    path("asr-preferences/", views.asr_preferences_page, name="asr-preferences"),
    path("system/asr/", views.system_asr_page, name="system-asr"),
    path("ai-preferences/", views.ai_preferences_page, name="ai-preferences"),
    path("system/ai/", views.system_ai_page, name="system-ai"),
    path("projects/", views.project_list, name="project-list"),
    path("projects/new/", views.project_create, name="project-create"),
    path("projects/<uuid:project_id>/", views.project_overview, name="project-overview"),
    path("projects/<uuid:project_id>/progress/", views.project_progress, name="project-progress"),
    path("projects/<uuid:project_id>/quality/", views.project_quality, name="project-quality"),
    path(
        "projects/<uuid:project_id>/work-queue/",
        views.project_work_queue,
        name="project-work-queue",
    ),
    path("projects/<uuid:project_id>/archive/", views.archive_project, name="project-archive"),
    path("projects/<uuid:project_id>/sources/", views.source_list, name="source-list"),
    path(
        "projects/<uuid:project_id>/sources/<uuid:source_id>/",
        views.source_detail,
        name="source-detail",
    ),
    path("projects/<uuid:project_id>/segments/", views.segment_index, name="segment-index"),
    path(
        "projects/<uuid:project_id>/segments/<uuid:segment_id>/",
        views.segment_workspace,
        name="segment-workspace",
    ),
    path("projects/<uuid:project_id>/labels/", views.labels_page, name="labels"),
    path("projects/<uuid:project_id>/members/", views.members_page, name="members"),
    path("projects/<uuid:project_id>/settings/", views.settings_page, name="settings"),
    path("projects/<uuid:project_id>/export/", views.project_export, name="project-export"),
]
