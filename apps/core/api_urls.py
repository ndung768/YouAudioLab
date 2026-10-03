from django.urls import path
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.processing import api as processing_api
from apps.processing import api_ai_assist as ai_assist_api
from apps.processing import api_ai_prefs as ai_prefs_api
from apps.processing import api_asr as asr_api
from apps.processing import api_asr_prefs as asr_prefs_api
from apps.workspace import api as workspace_api
from apps.workspace import api_auth as auth_api


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def api_health(_request):
    return Response({"status": "ok", "api": "v1"})


urlpatterns = [
    path("health", api_health, name="api-health"),
    path("auth/register", auth_api.auth_register, name="api-auth-register"),
    path("auth/login", auth_api.auth_login, name="api-auth-login"),
    path("users", workspace_api.create_user, name="api-users-create"),
    path("me", workspace_api.me, name="api-me"),
    path("projects", workspace_api.projects, name="api-projects"),
    path("projects/<uuid:project_id>", workspace_api.project_detail, name="api-project-detail"),
    path(
        "projects/<uuid:project_id>/archive",
        workspace_api.archive_project,
        name="api-project-archive",
    ),
    path(
        "projects/<uuid:project_id>/settings",
        workspace_api.project_settings,
        name="api-project-settings",
    ),
    path(
        "projects/<uuid:project_id>/members",
        workspace_api.project_members,
        name="api-project-members",
    ),
    path("export-formats", workspace_api.export_formats, name="api-export-formats"),
    path(
        "projects/<uuid:project_id>/export",
        workspace_api.project_export,
        name="api-project-export",
    ),
    path(
        "projects/<uuid:project_id>/quality-report",
        workspace_api.project_quality_report,
        name="api-project-quality-report",
    ),
    path(
        "projects/<uuid:project_id>/assignments",
        workspace_api.project_assignments,
        name="api-project-assignments",
    ),
    path(
        "projects/<uuid:project_id>/assignments/mine",
        workspace_api.project_assignments_mine,
        name="api-project-assignments-mine",
    ),
    path(
        "projects/<uuid:project_id>/assignments/<uuid:assignment_id>/release",
        workspace_api.assignment_release,
        name="api-assignment-release",
    ),
    path(
        "projects/<uuid:project_id>/assignments/<uuid:assignment_id>/start",
        workspace_api.assignment_start,
        name="api-assignment-start",
    ),
    path(
        "projects/<uuid:project_id>/assignments/<uuid:assignment_id>/complete",
        workspace_api.assignment_complete,
        name="api-assignment-complete",
    ),
    path(
        "projects/<uuid:project_id>/assignments/<uuid:assignment_id>/reassign",
        workspace_api.assignment_reassign,
        name="api-assignment-reassign",
    ),
    path(
        "projects/<uuid:project_id>/members/<uuid:user_id>",
        workspace_api.revoke_member,
        name="api-project-member-revoke",
    ),
    path(
        "projects/<uuid:project_id>/sources",
        workspace_api.project_sources,
        name="api-project-sources",
    ),
    path(
        "projects/<uuid:project_id>/sources/<uuid:source_id>",
        workspace_api.source_detail,
        name="api-source-detail",
    ),
    path(
        "projects/<uuid:project_id>/sources/<uuid:source_id>/refresh-metadata",
        workspace_api.refresh_metadata,
        name="api-source-refresh-metadata",
    ),
    path(
        "projects/<uuid:project_id>/sources/<uuid:source_id>/segments",
        workspace_api.source_segments,
        name="api-source-segments",
    ),
    path("segments/<uuid:segment_id>", workspace_api.segment_detail, name="api-segment-detail"),
    path(
        "projects/<uuid:project_id>/labels",
        workspace_api.project_labels,
        name="api-project-labels",
    ),
    path(
        "projects/<uuid:project_id>/labels/<uuid:label_id>",
        workspace_api.label_detail,
        name="api-label-detail",
    ),
    path(
        "projects/<uuid:project_id>/labels/<uuid:label_id>/deactivate",
        workspace_api.deactivate_label,
        name="api-label-deactivate",
    ),
    path(
        "projects/<uuid:project_id>/labels/<uuid:label_id>/activate",
        workspace_api.activate_label,
        name="api-label-activate",
    ),
    path(
        "segments/<uuid:segment_id>/annotations",
        workspace_api.segment_annotations,
        name="api-segment-annotations",
    ),
    path(
        "annotations/<uuid:annotation_id>",
        workspace_api.remove_annotation,
        name="api-annotation-remove",
    ),
    path(
        "segments/<uuid:segment_id>/jobs",
        processing_api.segment_jobs,
        name="api-segment-jobs",
    ),
    path(
        "projects/<uuid:project_id>/jobs",
        processing_api.project_jobs,
        name="api-project-jobs",
    ),
    path("jobs/<uuid:job_id>", processing_api.job_detail, name="api-job-detail"),
    path("jobs/<uuid:job_id>/cancel", processing_api.cancel_job, name="api-job-cancel"),
    path("jobs/<uuid:job_id>/retry", processing_api.retry_job, name="api-job-retry"),
    path(
        "artifacts/<uuid:artifact_id>",
        processing_api.artifact_detail,
        name="api-artifact-detail",
    ),
    path(
        "artifacts/<uuid:artifact_id>/content",
        processing_api.artifact_content,
        name="api-artifact-content",
    ),
    path(
        "segments/<uuid:segment_id>/asr/jobs",
        asr_api.segment_asr_jobs,
        name="api-segment-asr-jobs",
    ),
    path(
        "segments/<uuid:segment_id>/asr/runs",
        asr_api.segment_asr_runs,
        name="api-segment-asr-runs",
    ),
    path(
        "asr/runs/<uuid:asr_run_id>",
        asr_api.asr_run_detail,
        name="api-asr-run-detail",
    ),
    path(
        "asr/runs/<uuid:asr_run_id>/apply",
        asr_api.apply_asr_run,
        name="api-asr-run-apply",
    ),
    path(
        "system/asr/defaults",
        asr_prefs_api.system_asr_defaults,
        name="api-system-asr-defaults",
    ),
    path(
        "me/asr-preferences",
        asr_prefs_api.me_asr_preferences,
        name="api-me-asr-preferences",
    ),
    path(
        "me/asr-preferences/test-connection",
        asr_prefs_api.me_asr_test_connection,
        name="api-me-asr-test-connection",
    ),
    path(
        "system/ai/defaults",
        ai_prefs_api.system_ai_defaults,
        name="api-system-ai-defaults",
    ),
    path(
        "me/ai-preferences",
        ai_prefs_api.me_ai_preferences,
        name="api-me-ai-preferences",
    ),
    path(
        "me/ai-preferences/test-connection",
        ai_prefs_api.me_ai_test_connection,
        name="api-me-ai-test-connection",
    ),
    path(
        "segments/<uuid:segment_id>/ai/assists",
        ai_assist_api.segment_ai_assists,
        name="api-segment-ai-assists",
    ),
    path(
        "segments/<uuid:segment_id>/ai/assists/<uuid:assist_run_id>/apply",
        ai_assist_api.apply_ai_assist,
        name="api-ai-assist-apply",
    ),
]
