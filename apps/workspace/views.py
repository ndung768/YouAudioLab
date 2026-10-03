"""Server-rendered Gate 4 screens. Forms work without JavaScript."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.core.errors import (
    DomainError,
    SegmentRevisionConflictError,
    SourceDuplicateError,
    ValidationError,
)
from apps.core.identity import clear_identity, set_identity_user
from apps.core.storage import get_storage
from apps.processing.enqueue import (
    enqueue_extract_segment_audio,
    enqueue_fetch_source_metadata,
    enqueue_transcribe_segment_audio,
)
from apps.processing.models import (
    ProcessingArtifact,
    ProcessingJob,
    SystemAiSettings,
    SystemAsrSettings,
    UserAiPreferences,
    UserAsrPreferences,
)
from apps.processing.services.ai_assist import AiAssistService
from apps.processing.services.ai_resolve import (
    effective_system_ai,
    is_ai_admin,
    resolve_ai_config,
)
from apps.processing.services.asr import AsrService
from apps.processing.services.asr_resolve import (
    effective_system_asr,
    format_asr_probe_flash,
    is_asr_admin,
    probe_asr_connection,
    resolve_asr_config,
)
from apps.processing.services.asr_secrets import encrypt_secret, secrets_key_configured
from apps.processing.services.job import JobService
from apps.workspace.models import AnnotationAssignment, AppUser, AudioSegment, Project
from apps.workspace.services import (
    AnnotationService,
    AssignmentService,
    ExportService,
    GoldService,
    IdentityService,
    LabelService,
    MembershipService,
    ProjectService,
    ProjectStatsService,
    QualityReportService,
    SegmentService,
    SourceService,
)


_CONFLICT_USER_MESSAGES = {
    "ACTIVE_JOB_EXISTS": "An active job already exists for this segment.",
    "LABEL_INACTIVE": "That label is inactive. Choose an active label.",
    "SOURCE_DUPLICATE": "This YouTube video is already imported in this project.",
    "PROJECT_ARCHIVED": "This project is archived and cannot be modified.",
    "SEGMENT_DELETED": "This segment was soft-deleted.",
}


def _require_identity(request: HttpRequest) -> AppUser | HttpResponseRedirect:
    user = getattr(request, "identity_user", None)
    if user is None:
        return redirect("identity")
    return user


def _role(project_id, user_id) -> str | None:
    membership = MembershipService().get_active_membership(project_id, user_id)
    return membership.role if membership else None


def _annotator_blind(role: str | None, project) -> bool:
    if role != "ANNOTATOR":
        return False
    settings = getattr(project, "settings", None)
    if settings is None:
        return True
    return bool(getattr(settings, "blind_annotators", True))


def _handle_domain(request: HttpRequest, exc: DomainError) -> None:
    if exc.code == "SEGMENT_REVISION_CONFLICT":
        current = exc.details.get("current_definition_revision")
        if current is not None:
            messages.error(
                request,
                _(
                    "Someone else updated this segment (now revision %(current)s). "
                    "Your save was not applied."
                )
                % {"current": current},
            )
        else:
            messages.error(
                request,
                _("Someone else updated this segment. Your save was not applied."),
            )
        return
    msg = _CONFLICT_USER_MESSAGES.get(exc.code)
    messages.error(request, _(msg) if msg else exc.message)


@require_http_methods(["GET", "POST"])
def identity(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "login":
                from apps.workspace.services.auth import AuthService

                user, _token = AuthService().login(
                    login_identifier=request.POST.get("login_identifier", ""),
                    password=request.POST.get("password", ""),
                )
                set_identity_user(request, user)
                messages.success(request, _("Signed in."))
                return redirect("project-list")
            if action == "register":
                from apps.workspace.services.auth import AuthService

                user, _token = AuthService().register(
                    display_name=request.POST.get("display_name", ""),
                    login_identifier=request.POST.get("login_identifier", ""),
                    password=request.POST.get("password", ""),
                )
                set_identity_user(request, user)
                messages.success(request, _("Account created."))
                return redirect("project-list")
            if action == "create":
                user = IdentityService().create_user(
                    display_name=request.POST.get("display_name", ""),
                    login_identifier=request.POST.get("login_identifier", ""),
                )
                set_identity_user(request, user)
                messages.success(request, _("Identity created."))
                return redirect("project-list")
            if action == "select":
                raw_id = (request.POST.get("user_id") or "").strip()
                try:
                    uuid.UUID(raw_id)
                except ValueError:
                    messages.error(
                        request,
                        _("Enter a valid user UUID (X-User-Id)."),
                    )
                    return redirect("identity")
                user = IdentityService().get(raw_id)
                if user.status != AppUser.Status.ACTIVE:
                    messages.error(request, _("Unknown or inactive user"))
                    return redirect("identity")
                set_identity_user(request, user)
                messages.success(request, _("Identity selected."))
                return redirect("project-list")
            if action == "clear":
                clear_identity(request)
                messages.info(request, _("Identity cleared."))
                return redirect("identity")
        except DomainError as exc:
            _handle_domain(request, exc)
            return redirect("identity")
    return render(request, "identity.html")


@require_http_methods(["GET", "POST"])
def project_list(request: HttpRequest) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    projects_svc = ProjectService()
    owned = projects_svc.list_owned_for_user(user.id)
    participated = projects_svc.list_participated_for_user(user.id)
    return render(
        request,
        "projects/list.html",
        {
            "owned_projects": owned,
            "participated_projects": participated,
            "owned_count": len(owned),
            "participated_count": len(participated),
            "total_count": len(owned) + len(participated),
        },
    )


@require_http_methods(["GET", "POST"])
def project_create(request: HttpRequest) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    if request.method == "POST":
        try:
            project = ProjectService().create(
                name=request.POST.get("name", ""),
                owner_user_id=user.id,
                description=request.POST.get("description") or None,
                language=request.POST.get("language") or "vi",
            )
            messages.success(request, _("Project created."))
            return redirect("project-overview", project_id=project.id)
        except DomainError as exc:
            _handle_domain(request, exc)
    return render(request, "projects/create.html")


def project_overview(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        stats_svc = ProjectStatsService()
        stats = stats_svc.get_stats(project_id)
        recent_sources = stats_svc.recent_sources(project_id)
        next_segment = stats_svc.next_labeling_segment(project_id, user_id=user.id)
        jobs = JobService(get_storage()).list_for_project(project_id)[:8]
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("project-list")
    return render(
        request,
        "projects/overview.html",
        {
            "project": project,
            "stats": stats,
            "recent_sources": recent_sources,
            "next_segment": next_segment,
            "jobs": jobs,
            "role": _role(project_id, user.id),
        },
    )


@require_http_methods(["GET", "POST"])
def project_work_queue(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        membership = MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        assign_svc = AssignmentService()
        role = membership.role
        status_filter = request.GET.get("status") or ""
        assignee_filter = request.GET.get("assignee") or ""
        source_filter = request.GET.get("source") or ""

        if request.method == "POST":
            action = request.POST.get("action")
            try:
                if action == "complete":
                    assign_svc.complete(
                        request.POST.get("assignment_id"),
                        project_id=project_id,
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Assignment marked complete."))
                elif role != "OWNER":
                    messages.error(request, _("Only project owners can manage the work queue."))
                elif action == "create_batch":
                    assignee_raw = request.POST.getlist("assignee_ids")
                    segment_raw = [x for x in request.POST.getlist("segment_ids") if x]
                    segment_ids = [uuid.UUID(x) for x in segment_raw] or None
                    assign_svc.create_batch(
                        project_id=project_id,
                        actor_user_id=user.id,
                        assignee_ids=[uuid.UUID(x) for x in assignee_raw if x],
                        source_id=None if segment_ids else (request.POST.get("source_id") or None),
                        segment_ids=segment_ids,
                        limit=(
                            None
                            if segment_ids
                            else (
                                int(request.POST["limit"]) if request.POST.get("limit") else None
                            )
                        ),
                        distribute=request.POST.get("distribute") or "split",
                        priority=int(request.POST.get("priority") or "0"),
                        name=request.POST.get("name") or None,
                        notes=request.POST.get("notes") or None,
                    )
                    messages.success(request, _("Assignments created."))
                elif action == "release":
                    assign_svc.release(
                        request.POST.get("assignment_id"),
                        project_id=project_id,
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Assignment released."))
                elif action == "reassign":
                    assign_svc.reassign(
                        request.POST.get("assignment_id"),
                        project_id=project_id,
                        actor_user_id=user.id,
                        new_assignee_id=request.POST.get("new_assignee_id"),
                    )
                    messages.success(request, _("Assignment reassigned."))
            except DomainError as exc:
                _handle_domain(request, exc)
            next_url = reverse("project-work-queue", kwargs={"project_id": project_id})
            query = request.GET.urlencode()
            if query:
                next_url = f"{next_url}?{query}"
            return redirect(next_url)

        if role == "OWNER":
            assignments = assign_svc.list_for_project(
                project_id,
                actor_user_id=user.id,
                status=status_filter or None,
                assignee_id=assignee_filter or None,
                source_id=source_filter or None,
            )
            workload = assign_svc.assignee_workload(project_id)
            members = MembershipService().list_active(project_id)
            annotators = [m for m in members if m.role == "ANNOTATOR"]
            sources = SourceService().list_for_project(project_id)
            segments = SegmentService().list_for_project(project_id)
        else:
            assignments = assign_svc.list_mine(
                project_id,
                actor_user_id=user.id,
                status=status_filter or None,
            )
            workload = []
            annotators = []
            sources = []
            segments = []
        next_assigned = assign_svc.next_assigned_segment(project_id, user_id=user.id)
        status_counts = assign_svc.assignment_status_counts(project_id)
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("project-list")
    return render(
        request,
        "projects/work_queue.html",
        {
            "project": project,
            "role": role,
            "assignments": assignments,
            "workload": workload,
            "annotators": annotators,
            "sources": sources,
            "segments": segments,
            "next_assigned": next_assigned,
            "status_counts": status_counts,
            "status_filter": status_filter,
            "assignee_filter": assignee_filter,
            "source_filter": source_filter,
            "active_statuses": AnnotationAssignment.ACTIVE_STATUSES,
        },
    )


@require_http_methods(["GET", "POST"])
def project_export(request: HttpRequest, project_id) -> HttpResponse:
    from apps.workspace.services.export_dataset import format_groups

    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_owner(project_id, user.id)
        project = ProjectService().get(project_id)
        if request.method == "POST":
            def _float(name: str, default: float) -> float:
                raw = (request.POST.get(name) or "").strip()
                if not raw:
                    return default
                try:
                    return float(raw)
                except ValueError:
                    return default

            def _int(name: str, default: int) -> int:
                raw = (request.POST.get(name) or "").strip()
                if not raw:
                    return default
                try:
                    return int(raw)
                except ValueError:
                    return default

            flags = {
                "source_id": request.POST.get("source_id") or None,
                "include_deleted_segments": "include_deleted_segments" in request.POST,
                "include_removed_annotations": "include_removed_annotations" in request.POST,
                "include_released_assignments": "include_released_assignments" in request.POST,
                "include_stale_asr": "include_stale_asr" in request.POST,
                "ready_only": "ready_only" in request.POST,
                "split_strategy": (request.POST.get("split_strategy") or "by_source").strip(),
                "split_seed": _int("split_seed", 42),
                "split_train": _float("split_train", 0.8),
                "split_val": _float("split_val", 0.1),
                "split_test": _float("split_test", 0.1),
                "supervision_policy": (
                    request.POST.get("supervision_policy") or "majority"
                ).strip(),
            }
            snapshot = ExportService().build_snapshot(
                project_id,
                actor_user_id=user.id,
                **flags,
            )
            body, meta = ExportService().render(
                snapshot, request.POST.get("export_format") or "json"
            )
            filename = f"{project.name[:40]}-{meta.key}{meta.extension}"
            response = HttpResponse(body, content_type=meta.content_type)
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
    except DomainError as exc:
        _handle_domain(request, exc)
        if request.method == "POST":
            return redirect("project-export", project_id=project_id)
        return redirect("project-overview", project_id=project_id)
    sources = SourceService().list_for_project(project_id)
    return render(
        request,
        "projects/export.html",
        {
            "project": project,
            "role": "OWNER",
            "sources": sources,
            "format_groups": format_groups(),
        },
    )


@require_http_methods(["GET", "POST"])
def project_progress(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        stats_svc = ProjectStatsService()
        stats = stats_svc.get_stats(project_id)
        annotators = stats_svc.annotator_progress(project_id)
        role = _role(project_id, user.id)
        iaa = None
        if role == "OWNER":
            from apps.workspace.services.agreement import AgreementService

            iaa = AgreementService().report(project_id)
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("project-list")
    return render(
        request,
        "projects/progress.html",
        {
            "project": project,
            "stats": stats,
            "annotators": annotators,
            "role": role,
            "iaa": iaa,
        },
    )


@require_http_methods(["GET"])
def project_quality(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_owner(project_id, user.id)
        project = ProjectService().get(project_id)
        report = QualityReportService().build(project_id, actor_user_id=user.id)
    except DomainError as exc:
        _handle_domain(request, exc)
        return redirect("project-progress", project_id=project_id)
    payload = report.to_dict()
    if (request.GET.get("format") or "").strip().lower() == "json":
        response = JsonResponse(payload)
        filename = f"{project.name[:40]}-quality.json"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    from apps.workspace.services.quality_report import COVERAGE_TABLE_LIMIT

    coverage = payload.get("coverage") or []
    hidden = max(0, len(coverage) - COVERAGE_TABLE_LIMIT)
    return render(
        request,
        "projects/quality.html",
        {
            "project": project,
            "role": "OWNER",
            "report": payload,
            "coverage_rows": coverage[:COVERAGE_TABLE_LIMIT],
            "coverage_hidden": hidden,
        },
    )


@require_http_methods(["POST"])
def archive_project(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        ProjectService().archive(project_id, actor_user_id=user.id)
        messages.success(request, _("Project archived."))
    except DomainError as exc:
        _handle_domain(request, exc)
    return redirect("project-overview", project_id=project_id)


@require_http_methods(["GET", "POST"])
def source_list(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        if request.method == "POST":
            try:
                source = SourceService().import_source(
                    project_id=project_id,
                    youtube_url=request.POST.get("youtube_url", ""),
                    actor_user_id=user.id,
                )
            except SourceDuplicateError as exc:
                messages.error(
                    request,
                    _(exc.message) if exc.message else _("This source already exists in the project."),
                )
                return redirect("source-list", project_id=project_id)
            enqueue_fetch_source_metadata(source.id)
            messages.success(
                request,
                _("Source imported (metadata pending). Fetch queued."),
            )
            return redirect("source-detail", project_id=project_id, source_id=source.id)
    except DomainError as exc:
        _handle_domain(request, exc)
        project = ProjectService().get(project_id)
    sources = SourceService().list_for_project(project_id)
    return render(
        request,
        "sources/list.html",
        {"project": project, "sources": sources, "role": _role(project_id, user.id)},
    )


@require_http_methods(["GET", "POST"])
def source_detail(request: HttpRequest, project_id, source_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        source = SourceService().get_for_project(project_id, source_id)
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "create_segment":
                if source.duration_seconds is None:
                    messages.error(
                        request,
                        _("Create Segment is unavailable until source duration is known."),
                    )
                    return redirect(
                        "source-detail",
                        project_id=project_id,
                        source_id=source_id,
                    )
                segment = SegmentService().create(
                    source_id=source_id,
                    start_seconds=float(request.POST.get("start_seconds", "0")),
                    end_seconds=float(request.POST.get("end_seconds", "0")),
                    actor_user_id=user.id,
                    transcript=request.POST.get("transcript") or None,
                )
                messages.success(request, _("Segment created."))
                return redirect(
                    "segment-workspace",
                    project_id=project_id,
                    segment_id=segment.id,
                )
            elif action == "refresh_metadata":
                SourceService().request_metadata_refresh(source_id, actor_user_id=user.id)
                enqueue_fetch_source_metadata(source_id)
                messages.success(request, _("Metadata refresh queued."))
            return redirect("source-detail", project_id=project_id, source_id=source_id)
    except DomainError as exc:
        _handle_domain(request, exc)
        return redirect("source-list", project_id=project_id)
    except (TypeError, ValueError):
        messages.error(request, _("Invalid segment bounds."))
        return redirect("source-detail", project_id=project_id, source_id=source_id)
    segments = SegmentService().list_for_source(source_id)
    from apps.workspace.services.readiness import ReadinessService

    readiness_map = ReadinessService().evaluate_many(segments, project_id=project_id)
    segment_rows = [
        {
            "segment": segment,
            "readiness": readiness_map[segment.id],
        }
        for segment in segments
    ]
    return render(
        request,
        "sources/detail.html",
        {
            "project": project,
            "source": source,
            "segments": segments,
            "segment_rows": segment_rows,
            "role": _role(project_id, user.id),
        },
    )


@require_http_methods(["GET", "POST"])
def segment_index(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)

        if request.method == "POST":
            if project.status == "ARCHIVED":
                messages.error(request, _("Project is archived."))
            else:
                action = request.POST.get("action")
                try:
                    if action == "assign_label":
                        AnnotationService().assign(
                            segment_id=request.POST.get("segment_id"),
                            label_id=request.POST.get("label_id"),
                            actor_user_id=user.id,
                        )
                        messages.success(request, _("Label assigned."))
                    elif action == "remove_annotation":
                        AnnotationService().remove(
                            request.POST.get("annotation_id"),
                            actor_user_id=user.id,
                        )
                        messages.success(request, _("Label removed."))
                    elif action == "save_transcript":
                        SegmentService().update(
                            request.POST.get("segment_id"),
                            actor_user_id=user.id,
                            expected_definition_revision=int(
                                request.POST.get("expected_definition_revision", "0")
                            ),
                            transcript=request.POST.get("transcript") or None,
                        )
                        messages.success(request, _("Transcript saved."))
                except DomainError as exc:
                    _handle_domain(request, exc)
                except (TypeError, ValueError):
                    messages.error(request, _("Invalid transcript values."))
            next_url = reverse("segment-index", kwargs={"project_id": project_id})
            query = request.GET.urlencode()
            if query:
                next_url = f"{next_url}?{query}"
            return redirect(next_url)

        source_filter = (request.GET.get("source") or "").strip()
        annotated_filter = (request.GET.get("annotated") or "").strip().lower()
        processing_filter = (request.GET.get("processing") or "").strip().upper()
        ready_filter = (request.GET.get("ready") or "").strip().lower()
        mine = request.GET.get("mine") == "1"
        editing_transcript_id = request.GET.get("edit_transcript") or ""
        if annotated_filter not in {"", "yes", "no"}:
            annotated_filter = ""
        if ready_filter not in {"", "yes", "no"}:
            ready_filter = ""
        allowed_processing = {
            AudioSegment.ProcessingStatus.PENDING,
            AudioSegment.ProcessingStatus.PROCESSING,
            AudioSegment.ProcessingStatus.COMPLETED,
            AudioSegment.ProcessingStatus.FAILED,
        }
        if processing_filter and processing_filter not in allowed_processing:
            processing_filter = ""
        source_id = None
        if source_filter:
            try:
                source_id = uuid.UUID(source_filter)
            except ValueError:
                source_filter = ""
                source_id = None
        sources = SourceService().list_for_project(project_id)
        project_labels = LabelService().list_for_project(project_id)
        role = _role(project_id, user.id)
        blind = _annotator_blind(role, project)
        rows = SegmentService().list_index_rows(
            project_id,
            actor_user_id=user.id,
            source_id=source_id,
            annotated=annotated_filter or None,
            mine=mine,
            processing=processing_filter or None,
            ready=ready_filter or None,
            project_labels=project_labels,
            blind=blind,
        )
        next_assigned = AssignmentService().next_assigned_segment(
            project_id, user_id=user.id
        )
    except DomainError as exc:
        messages.error(request, exc.message)
        return redirect("project-list")
    annotated_n = sum(1 for row in rows if row.active_annotation_count > 0)
    ready_n = sum(1 for row in rows if row.is_ready)
    from apps.workspace.services.segment import group_index_rows_by_source

    source_groups = group_index_rows_by_source(rows)
    return render(
        request,
        "segments/index.html",
        {
            "project": project,
            "rows": rows,
            "source_groups": source_groups,
            "sources": sources,
            "project_labels": project_labels,
            "role": role,
            "source_filter": source_filter,
            "annotated_filter": annotated_filter,
            "processing_filter": processing_filter,
            "ready_filter": ready_filter,
            "mine": mine,
            "editing_transcript_id": editing_transcript_id,
            "next_assigned": next_assigned,
            "total_count": len(rows),
            "annotated_count": annotated_n,
            "ready_count": ready_n,
            "source_group_count": len(source_groups),
            "blind": blind,
        },
    )


@require_http_methods(["GET", "POST"])
def segment_workspace(request: HttpRequest, project_id, segment_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    conflict = None
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        segment = SegmentService().get(segment_id)
        if segment.source.project_id != project_id:
            messages.error(request, _("Segment not found"))
            return redirect("segment-index", project_id=project_id)
        source = segment.source
        if request.method == "POST":
            action = request.POST.get("action")
            try:
                if action == "save_definition":
                    SegmentService().update(
                        segment_id,
                        actor_user_id=user.id,
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        start_seconds=float(request.POST.get("start_seconds")),
                        end_seconds=float(request.POST.get("end_seconds")),
                    )
                    messages.success(request, _("Saved."))
                elif action == "save_transcript":
                    SegmentService().update(
                        segment_id,
                        actor_user_id=user.id,
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        transcript=request.POST.get("transcript") or None,
                    )
                    messages.success(request, _("Transcript saved."))
                elif action == "delete_segment":
                    SegmentService().soft_delete(segment_id, actor_user_id=user.id)
                    messages.success(request, _("Segment deleted."))
                    return redirect("segment-index", project_id=project_id)
                elif action == "assign_label":
                    AnnotationService().assign(
                        segment_id=segment_id,
                        label_id=request.POST.get("label_id"),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Annotation assigned."))
                    if request.POST.get("advance") == "1":
                        _prev, nxt = SegmentService().neighbors(project_id, segment_id)
                        if nxt is not None:
                            return redirect(
                                "segment-workspace",
                                project_id=project_id,
                                segment_id=nxt.id,
                            )
                elif action == "advance_next":
                    nxt = AssignmentService().next_assigned_segment(
                        project_id, user_id=user.id
                    )
                    if nxt is None or str(nxt.id) == str(segment_id):
                        _prev, nxt = SegmentService().neighbors(project_id, segment_id)
                    if nxt is not None and str(nxt.id) != str(segment_id):
                        return redirect(
                            "segment-workspace",
                            project_id=project_id,
                            segment_id=nxt.id,
                        )
                    messages.info(request, _("No next segment."))
                elif action == "complete_assignment":
                    AssignmentService().complete(
                        request.POST.get("assignment_id"),
                        project_id=project_id,
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Assignment marked complete."))
                    if request.POST.get("advance") == "1":
                        nxt = AssignmentService().next_assigned_segment(
                            project_id, user_id=user.id
                        )
                        if nxt is None:
                            nxt_seg = ProjectStatsService().next_labeling_segment(
                                project_id, user_id=user.id
                            )
                            if nxt_seg is not None and str(nxt_seg.id) != str(segment_id):
                                return redirect(
                                    "segment-workspace",
                                    project_id=project_id,
                                    segment_id=nxt_seg.id,
                                )
                        elif str(nxt.id) != str(segment_id):
                            return redirect(
                                "segment-workspace",
                                project_id=project_id,
                                segment_id=nxt.id,
                            )
                elif action == "mark_audio_reviewed":
                    SegmentService().mark_audio_reviewed(
                        segment_id,
                        actor_user_id=user.id,
                        reviewed=True,
                    )
                    messages.success(request, _("Audio marked OK for review."))
                elif action == "clear_audio_reviewed":
                    SegmentService().mark_audio_reviewed(
                        segment_id,
                        actor_user_id=user.id,
                        reviewed=False,
                    )
                    messages.success(request, _("Audio review cleared."))
                elif action == "remove_annotation":
                    AnnotationService().remove(
                        request.POST.get("annotation_id"),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Annotation removed."))
                elif action == "save_gold":
                    GoldService().set_labels(
                        segment_id=segment_id,
                        label_ids=request.POST.getlist("gold_label_ids"),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Gold labels saved."))
                elif action == "adopt_gold_majority":
                    GoldService().adopt_majority(
                        segment_id=segment_id,
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Gold set from majority of active annotators."))
                elif action == "submit_job":
                    job = JobService(get_storage()).submit(
                        segment_id=segment_id,
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        actor_user_id=user.id,
                    )
                    enqueue_extract_segment_audio(job.id)
                    messages.success(request, _("Processing job queued."))
                elif action == "cancel_job":
                    JobService(get_storage()).cancel(
                        request.POST.get("job_id"),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Cancellation requested."))
                elif action == "retry_job":
                    job = JobService(get_storage()).retry(
                        request.POST.get("job_id"),
                        actor_user_id=user.id,
                    )
                    if job.job_type == ProcessingJob.JobType.TRANSCRIBE_SEGMENT_AUDIO:
                        enqueue_transcribe_segment_audio(job.id)
                    else:
                        enqueue_extract_segment_audio(job.id)
                    messages.success(request, _("Retry queued."))
                elif action == "submit_asr":
                    job, created = AsrService(get_storage()).submit(
                        segment_id=segment_id,
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        actor_user_id=user.id,
                        language=request.POST.get("language") or None,
                        force=request.POST.get("force") == "1",
                    )
                    if created:
                        enqueue_transcribe_segment_audio(job.id)
                        messages.success(request, _("ASR job queued."))
                    else:
                        messages.success(request, _("Reused equivalent ASR result."))
                elif action == "apply_asr":
                    AsrService(get_storage()).apply(
                        request.POST.get("asr_run_id"),
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("ASR text applied to transcript."))
                elif action == "create_ai_assist":
                    AiAssistService().create(
                        segment_id=segment_id,
                        actor_user_id=user.id,
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        kind=request.POST.get("kind") or "transcript_cleanup",
                    )
                    messages.success(request, _("AI assist candidate ready."))
                elif action == "apply_ai_assist":
                    AiAssistService().apply(
                        request.POST.get("assist_run_id"),
                        expected_definition_revision=int(
                            request.POST.get("expected_definition_revision", "0")
                        ),
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("AI assist applied."))
                return redirect(
                    "segment-workspace", project_id=project_id, segment_id=segment_id
                )
            except SegmentRevisionConflictError as exc:
                if action != "save_definition":
                    current = exc.details.get("current_definition_revision")
                    if current is not None:
                        base = _(
                            "Someone else updated this segment (now revision %(current)s). "
                            "Your save was not applied."
                        ) % {"current": current}
                    else:
                        base = _("Someone else updated this segment. Your save was not applied.")
                    messages.error(
                        request,
                        base
                        + " "
                        + _("Reload the workspace, then paste your transcript and Save again."),
                    )
                    return redirect(
                        "segment-workspace",
                        project_id=project_id,
                        segment_id=segment_id,
                    )
                segment = SegmentService().get(segment_id)
                source = segment.source
                conflict = {
                    "expected": exc.details.get("expected_definition_revision"),
                    "current": exc.details.get("current_definition_revision"),
                    "draft_start": float(request.POST.get("start_seconds")),
                    "draft_end": float(request.POST.get("end_seconds")),
                    "server_start": segment.start_seconds,
                    "server_end": segment.end_seconds,
                }
            except DomainError as exc:
                _handle_domain(request, exc)
                return redirect(
                    "segment-workspace", project_id=project_id, segment_id=segment_id
                )
            except (TypeError, ValueError):
                messages.error(request, _("Invalid form values."))
                return redirect(
                    "segment-workspace", project_id=project_id, segment_id=segment_id
                )
    except DomainError as exc:
        _handle_domain(request, exc)
        return redirect("segment-index", project_id=project_id)

    AssignmentService().mark_in_progress_for_workspace(
        project_id=project_id,
        segment_id=segment_id,
        actor_user_id=user.id,
    )
    my_assignments = AssignmentService().list_mine(project_id, actor_user_id=user.id)
    segment_assignments = [
        a
        for a in my_assignments
        if str(a.segment_id) == str(segment_id)
        and a.status in AnnotationAssignment.ACTIVE_STATUSES
    ]

    role = _role(project_id, user.id)
    blind = _annotator_blind(role, project)
    # Blind protocol: ANNOTATOR sees only their own episodes when enabled.
    if blind:
        ann_scope = "mine"
    else:
        ann_scope = request.GET.get("scope", "everyone")
    include_removed = request.GET.get("include_removed") == "1"
    annotations = AnnotationService().list_for_segment(
        segment_id,
        actor_user_id=user.id,
        include_removed=include_removed,
        annotator_id=user.id if ann_scope == "mine" else None,
    )
    labels = LabelService().list_for_project(project_id)
    gold_rows = GoldService().list_for_segment(segment_id) if role == "OWNER" else []
    gold_label_ids = {row.label_id for row in gold_rows}
    jobs = JobService(get_storage()).list_for_segment(segment_id)
    active_annotations = [a for a in annotations if a.removed_at is None]
    removed_annotations = [a for a in annotations if a.removed_at is not None]
    active_labels = labels
    mine_by_label = {
        a.label_id: a
        for a in AnnotationService().list_for_segment(
            segment_id,
            actor_user_id=user.id,
            include_removed=False,
            annotator_id=user.id,
        )
        if a.removed_at is None
    }
    label_chips = []
    for index, label in enumerate(active_labels[:9], start=1):
        label_chips.append(
            {
                "label": label,
                "hotkey": str(index),
                "mine": mine_by_label.get(label.id),
            }
        )
    for label in active_labels[9:]:
        label_chips.append({"label": label, "hotkey": None, "mine": mine_by_label.get(label.id)})
    prev_segment, next_segment = SegmentService().neighbors(project_id, segment.id)
    next_assigned = AssignmentService().next_assigned_segment(
        project_id, user_id=user.id
    )
    has_active_job = any(job.status in {"QUEUED", "RUNNING"} for job in jobs)
    asr = AsrService(get_storage())
    asr_jobs = asr.list_asr_jobs_for_segment(segment_id, actor_user_id=user.id)
    asr_runs = asr.list_runs_for_segment(segment_id, actor_user_id=user.id)
    has_active_asr = any(job.status in {"QUEUED", "RUNNING"} for job in asr_jobs)
    asr_latest_run = asr_runs[0] if asr_runs else None
    # Only surface failure when the newest ASR job failed — ignore older failures
    # after a later success (otherwise the banner stays stale).
    asr_latest_job = asr_jobs[0] if asr_jobs else None
    asr_latest_failed_job = (
        asr_latest_job
        if asr_latest_job is not None and asr_latest_job.status == "FAILED"
        else None
    )
    asr_defaults = effective_system_asr()
    asr_prefs = UserAsrPreferences.objects.filter(pk=user.id).first()
    try:
        asr_resolved = resolve_asr_config(
            actor_user_id=user.id,
            language_requested=(project.language or "vi"),
            project_id=project.id,
        )
        asr_display = {
            "provider": asr_resolved.provider,
            "engine": asr_resolved.engine,
            "model": asr_resolved.model,
            "source": (
                "project"
                if project.settings.asr_provider
                else ("prefs" if not asr_resolved.use_system_defaults else asr_defaults["source"])
            ),
        }
    except DomainError:
        asr_display = {
            "provider": asr_defaults["provider"],
            "engine": "—",
            "model": asr_defaults["local_model"],
            "source": asr_defaults["source"],
        }
    current_artifact = None
    current_artifact_job_id = None
    if segment.current_artifact_id:
        current_artifact = (
            ProcessingArtifact.objects.filter(pk=segment.current_artifact_id)
            .select_related("job")
            .first()
        )
        if current_artifact is not None:
            current_artifact_job_id = current_artifact.job_id

    from apps.workspace.services.readiness import ReadinessService

    readiness = ReadinessService().evaluate(segment)

    return render(
        request,
        "segments/workspace.html",
        {
            "project": project,
            "source": source,
            "segment": segment,
            "segment_assignments": segment_assignments,
            "annotations": annotations,
            "active_annotations": active_annotations,
            "removed_annotations": removed_annotations,
            "labels": labels,
            "active_labels": active_labels,
            "gold_rows": gold_rows,
            "gold_label_ids": gold_label_ids,
            "mine_by_label": mine_by_label,
            "label_chips": label_chips,
            "prev_segment": prev_segment,
            "next_segment": next_segment,
            "next_assigned": next_assigned,
            "jobs": jobs,
            "has_active_job": has_active_job,
            "asr_jobs": asr_jobs,
            "asr_runs": asr_runs,
            "asr_latest_run": asr_latest_run,
            "asr_latest_failed_job": asr_latest_failed_job,
            "has_active_asr": has_active_asr,
            "asr_display": asr_display,
            "asr_defaults": asr_defaults,
            "asr_prefs": asr_prefs,
            "is_asr_admin": is_asr_admin(user.id),
            "ai_assists": AiAssistService().list_for_segment(segment_id),
            "ai_defaults": effective_system_ai(),
            "ai_resolved": resolve_ai_config(
                actor_user_id=user.id, project_id=project.id
            ),
            "project_settings": project.settings,
            "is_ai_admin": is_ai_admin(user.id),
            "ann_scope": ann_scope,
            "include_removed": include_removed,
            "current_artifact": current_artifact,
            "current_artifact_job_id": current_artifact_job_id,
            "readiness": readiness,
            "role": role,
            "blind": blind,
            "actor": user,
            "conflict": conflict,
            "draft_start": conflict["draft_start"] if conflict else None,
            "draft_end": conflict["draft_end"] if conflict else None,
        },
    )


@require_http_methods(["GET", "POST"])
def labels_page(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    label_service = LabelService()
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "add_label":
                label_service.add_to_project(
                    project_id=project_id,
                    label_id=request.POST.get("label_id"),
                    actor_user_id=user.id,
                )
                messages.success(request, _("Label added to project."))
            elif action == "remove_label":
                label_service.remove_from_project(
                    request.POST.get("project_label_id"),
                    actor_user_id=user.id,
                )
                messages.success(request, _("Label removed from project."))
            elif action == "add_custom_label":
                label_service.create(
                    project_id=project_id,
                    name=request.POST.get("name", ""),
                    actor_user_id=user.id,
                    description=request.POST.get("description") or None,
                    color=request.POST.get("color") or None,
                    sort_order=int(request.POST.get("sort_order") or "0"),
                )
                messages.success(request, _("Label created and added to project."))
            elif action == "update_override":
                label_service.update_project_label(
                    request.POST.get("project_label_id"),
                    actor_user_id=user.id,
                    override_name=request.POST.get("override_name") or None,
                    override_description=request.POST.get("override_description") or None,
                    override_include_guidance=request.POST.get("override_include_guidance")
                    or None,
                    override_exclude_guidance=request.POST.get("override_exclude_guidance")
                    or None,
                    override_color=request.POST.get("override_color") or None,
                    sort_order=int(request.POST.get("sort_order") or "0"),
                )
                messages.success(request, _("Label updated."))
            return redirect("labels", project_id=project_id)
    except DomainError as exc:
        _handle_domain(request, exc)
        project = ProjectService().get(project_id)
    except (TypeError, ValueError):
        messages.error(request, _("Invalid label values."))
        return redirect("labels", project_id=project_id)

    project_labels = label_service.list_for_project(project_id)
    available_labels = (
        label_service.list_available_for_project(project_id)
        if _role(project_id, user.id) == "OWNER"
        else []
    )
    from apps.workspace.models import SegmentAnnotation

    usage_counts: dict = {}
    pl_ids = [pl.id for pl in project_labels]
    if pl_ids:
        rows = (
            SegmentAnnotation.objects.filter(label_id__in=pl_ids, removed_at__isnull=True)
            .values("label_id")
            .annotate(n=Count("id"))
        )
        usage_counts = {row["label_id"]: row["n"] for row in rows}

    for pl in project_labels:
        pl.usage_count = usage_counts.get(pl.id, 0)

    editing_id = request.GET.get("edit")
    return render(
        request,
        "labels/list.html",
        {
            "project": project,
            "project_labels": project_labels,
            "available_labels": available_labels,
            "role": _role(project_id, user.id),
            "editing_id": editing_id,
        },
    )


@require_http_methods(["GET", "POST"])
def members_page(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "add":
                memberships = MembershipService()
                target = memberships.resolve_user_ref(
                    request.POST.get("user_ref") or request.POST.get("user_id") or ""
                )
                memberships.add_member(
                    project_id=project_id,
                    user_id=target.id,
                    role=request.POST.get("role") or "ANNOTATOR",
                    actor_user_id=user.id,
                )
                messages.success(request, _("Member added."))
            elif action == "revoke":
                target = request.POST.get("user_id")
                if str(target) == str(user.id):
                    messages.error(request, _("Cannot revoke your own membership in the UI."))
                else:
                    MembershipService().revoke_member(
                        project_id=project_id,
                        user_id=target,
                        actor_user_id=user.id,
                    )
                    messages.success(request, _("Member revoked."))
            return redirect("members", project_id=project_id)
    except DomainError as exc:
        _handle_domain(request, exc)
        project = ProjectService().get(project_id)
    members = MembershipService().list_active(project_id)
    return render(
        request,
        "members/list.html",
        {
            "project": project,
            "members": members,
            "role": _role(project_id, user.id),
            "actor": user,
        },
    )


@require_http_methods(["GET", "POST"])
def settings_page(request: HttpRequest, project_id) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    try:
        MembershipService().require_member(project_id, user.id)
        project = ProjectService().get(project_id)
        settings = ProjectService().get_settings(project_id)
        if request.method == "POST":
            action = request.POST.get("action") or "save_settings"
            if action == "archive":
                ProjectService().archive(project_id, actor_user_id=user.id)
                messages.success(request, _("Project archived."))
                return redirect("project-overview", project_id=project_id)
            ai_enabled_raw = (request.POST.get("ai_enabled") or "").strip()
            if ai_enabled_raw == "on":
                ai_enabled_val: bool | None = True
            elif ai_enabled_raw == "off":
                ai_enabled_val = False
            else:
                ai_enabled_val = None
            ProjectService().update(
                project_id,
                actor_user_id=user.id,
                license=request.POST.get("license") or None,
                consent_notes=request.POST.get("consent_notes") or None,
            )
            ProjectService().update_settings(
                project_id,
                actor_user_id=user.id,
                output_format=request.POST.get("output_format", "WAV"),
                encoding=request.POST.get("encoding", "PCM"),
                sample_rate_hz=int(request.POST.get("sample_rate_hz", "16000")),
                channels=int(request.POST.get("channels", "1")),
                loudness_normalization=request.POST.get("loudness_normalization") == "on",
                naming_convention=request.POST.get("naming_convention") or None,
                require_audio_review=request.POST.get("require_audio_review") == "on",
                require_transcript=request.POST.get("require_transcript") == "on",
                require_annotation=request.POST.get("require_annotation") == "on",
                blind_annotators=request.POST.get("blind_annotators") == "on",
                asr_provider=request.POST.get("asr_provider"),
                asr_model=request.POST.get("asr_model"),
                ai_enabled=ai_enabled_val,
                ai_provider=request.POST.get("ai_provider"),
                ai_ollama_base_url=request.POST.get("ai_ollama_base_url"),
                ai_ollama_model=request.POST.get("ai_ollama_model"),
                apply_asr_protocol=True,
                apply_ai_protocol=True,
            )
            messages.success(request, _("Settings saved. Existing jobs keep their snapshots."))
            return redirect("settings", project_id=project_id)
    except DomainError as exc:
        _handle_domain(request, exc)
        return redirect("project-overview", project_id=project_id)
    except (TypeError, ValueError):
        messages.error(request, _("Invalid settings values."))
        return redirect("settings", project_id=project_id)
    return render(
        request,
        "settings/form.html",
        {
            "project": project,
            "settings": settings,
            "role": _role(project_id, user.id),
        },
    )


def _settings_redirect(tab: str) -> HttpResponseRedirect:
    return redirect(f"{reverse('account-settings')}?tab={tab}")


@require_http_methods(["GET", "POST"])
def global_labels_page(request: HttpRequest) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user
    label_service = LabelService()
    try:
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "create":
                label_service.create_global(
                    owner_user_id=user.id,
                    name=request.POST.get("name", ""),
                    description=request.POST.get("description") or None,
                    include_guidance=request.POST.get("include_guidance") or None,
                    exclude_guidance=request.POST.get("exclude_guidance") or None,
                    color=request.POST.get("color") or None,
                )
                messages.success(request, _("Label created."))
            elif action == "update":
                is_active = request.POST.get("is_active") == "on"
                label_service.update_canonical(
                    request.POST.get("label_id"),
                    actor_user_id=user.id,
                    name=request.POST.get("name"),
                    description=request.POST.get("description") or None,
                    include_guidance=request.POST.get("include_guidance") or None,
                    exclude_guidance=request.POST.get("exclude_guidance") or None,
                    color=request.POST.get("color") or None,
                    is_active=is_active,
                )
                messages.success(request, _("Label saved."))
            elif action == "deactivate":
                label_service.deactivate_canonical(
                    request.POST.get("label_id"),
                    actor_user_id=user.id,
                )
                messages.success(request, _("Label deactivated."))
            elif action == "activate":
                label_service.activate_canonical(
                    request.POST.get("label_id"),
                    actor_user_id=user.id,
                )
                messages.success(request, _("Label activated."))
            elif action == "delete":
                label_service.delete_canonical(
                    request.POST.get("label_id"),
                    actor_user_id=user.id,
                )
                messages.success(request, _("Label deleted."))
            return redirect("global-labels")
    except DomainError as exc:
        _handle_domain(request, exc)
    except (TypeError, ValueError):
        messages.error(request, _("Invalid label values."))
        return redirect("global-labels")

    labels = label_service.list_owned(user.id)
    for label in labels:
        label.is_used = (label.usage_count or 0) > 0
        label.usage_count_val = label.usage_count or 0
    editing_id = request.GET.get("edit")
    return render(
        request,
        "labels/global_list.html",
        {
            "labels": labels,
            "editing_id": editing_id,
            "actor": user,
        },
    )


@require_http_methods(["GET", "POST"])
def account_settings_page(
    request: HttpRequest,
    *,
    default_tab: str | None = None,
) -> HttpResponse:
    user = _require_identity(request)
    if not isinstance(user, AppUser):
        return user

    tab = (
        request.GET.get("tab")
        or request.POST.get("settings_tab")
        or default_tab
        or "account"
    )
    valid_tabs = {"account", "asr", "ai", "system-asr", "system-ai"}
    if tab not in valid_tabs:
        tab = "account"

    asr_prefs = UserAsrPreferences.objects.filter(pk=user.id).first()
    ai_prefs = UserAiPreferences.objects.filter(pk=user.id).first()
    asr_defaults = effective_system_asr()
    ai_defaults = effective_system_ai()
    asr_admin = is_asr_admin(user.id)
    ai_admin = is_ai_admin(user.id)
    asr_resolved = None
    asr_resolve_error = None
    try:
        asr_resolved = resolve_asr_config(
            actor_user_id=user.id,
            language_requested="en",
        )
    except ValidationError as exc:
        asr_resolve_error = exc.message

    if request.method == "POST":
        action = request.POST.get("action") or "save"
        try:
            if tab == "asr":
                if action == "test":
                    probe = probe_asr_connection(actor_user_id=user.id)
                    level, text = format_asr_probe_flash(probe)
                    getattr(messages, level)(request, text)
                    return _settings_redirect("asr")
                if asr_prefs is None:
                    asr_prefs = UserAsrPreferences(user_id=user.id)
                mode = request.POST.get("mode") or "system"
                asr_prefs.use_system_defaults = mode == "system"
                if mode == "custom":
                    asr_prefs.provider = (request.POST.get("provider") or "local").strip().lower()
                    asr_prefs.local_model = request.POST.get("local_model") or None
                    asr_prefs.local_device = request.POST.get("local_device") or None
                    asr_prefs.local_compute_type = request.POST.get("local_compute_type") or None
                    asr_prefs.openai_model = request.POST.get("openai_model") or None
                if request.POST.get("clear_openai_api_key") == "on":
                    asr_prefs.openai_api_key_encrypted = None
                elif request.POST.get("openai_api_key"):
                    asr_prefs.openai_api_key_encrypted = encrypt_secret(
                        request.POST.get("openai_api_key").strip()
                    )
                asr_prefs.save()
                messages.success(request, _("ASR preferences saved."))
                return _settings_redirect("asr")

            if tab == "ai":
                if action == "test":
                    resolved = resolve_ai_config(actor_user_id=user.id)
                    if not resolved.enabled:
                        messages.error(request, _("AI provider is disabled."))
                    else:
                        messages.success(
                            request,
                            _("Resolved %(provider)s · %(model)s @ %(url)s")
                            % {
                                "provider": resolved.provider,
                                "model": resolved.ollama_model,
                                "url": resolved.ollama_base_url,
                            },
                        )
                    return _settings_redirect("ai")
                if ai_prefs is None:
                    ai_prefs = UserAiPreferences(user_id=user.id)
                mode = request.POST.get("mode") or "system"
                ai_prefs.use_system_defaults = mode == "system"
                if mode == "custom":
                    ai_prefs.provider = (request.POST.get("provider") or "ollama").strip().lower()
                    ai_prefs.ollama_base_url = request.POST.get("ollama_base_url") or None
                    ai_prefs.ollama_model = request.POST.get("ollama_model") or None
                ai_prefs.save()
                messages.success(request, _("AI preferences saved."))
                return _settings_redirect("ai")

            if tab == "system-asr":
                if not asr_admin:
                    messages.error(request, _("Only ASR admins can update system defaults."))
                    return _settings_redirect("system-asr")
                if action == "reset":
                    SystemAsrSettings.objects.filter(pk=1).delete()
                    messages.success(request, _("System ASR reset to environment defaults."))
                    return _settings_redirect("system-asr")
                if action == "test":
                    probe = probe_asr_connection(
                        actor_user_id=user.id, system_only=True
                    )
                    level, text = format_asr_probe_flash(probe)
                    getattr(messages, level)(request, text)
                    return _settings_redirect("system-asr")
                row, _created = SystemAsrSettings.objects.get_or_create(pk=1)
                row.provider = (request.POST.get("provider") or "").strip() or None
                row.local_model = request.POST.get("local_model") or None
                row.local_device = request.POST.get("local_device") or None
                row.local_compute_type = request.POST.get("local_compute_type") or None
                enabled = request.POST.get("openai_enabled")
                if enabled == "on":
                    row.openai_enabled = True
                elif enabled == "off":
                    row.openai_enabled = False
                row.openai_default_model = request.POST.get("openai_default_model") or None
                row.openai_base_url = request.POST.get("openai_base_url") or None
                if request.POST.get("clear_openai_api_key") == "on":
                    row.openai_api_key_encrypted = None
                elif request.POST.get("openai_api_key"):
                    row.openai_api_key_encrypted = encrypt_secret(
                        request.POST.get("openai_api_key").strip()
                    )
                row.updated_by_user_id = user.id
                row.save()
                messages.success(request, _("System ASR defaults saved."))
                return _settings_redirect("system-asr")

            if tab == "system-ai":
                if not ai_admin:
                    messages.error(request, _("Only AI admins can update system defaults."))
                    return _settings_redirect("system-ai")
                if action == "reset":
                    SystemAiSettings.objects.filter(pk=1).delete()
                    messages.success(request, _("System AI reset to environment defaults."))
                    return _settings_redirect("system-ai")
                row, _created = SystemAiSettings.objects.get_or_create(pk=1)
                enabled = request.POST.get("enabled")
                if enabled == "on":
                    row.enabled = True
                elif enabled == "off":
                    row.enabled = False
                row.provider = (request.POST.get("provider") or "").strip() or None
                row.ollama_base_url = request.POST.get("ollama_base_url") or None
                row.ollama_default_model = request.POST.get("ollama_default_model") or None
                row.updated_by_user_id = user.id
                row.save()
                messages.success(request, _("System AI defaults saved."))
                return _settings_redirect("system-ai")
        except DomainError as exc:
            _handle_domain(request, exc)
            return _settings_redirect(tab)

    return render(
        request,
        "account/settings.html",
        {
            "tab": tab,
            "actor": user,
            "asr_prefs": asr_prefs,
            "asr_defaults": asr_defaults,
            "asr_resolved": asr_resolved,
            "asr_resolve_error": asr_resolve_error,
            "asr_secrets_configured": secrets_key_configured(),
            "ai_prefs": ai_prefs,
            "ai_defaults": ai_defaults,
            "is_asr_admin": asr_admin,
            "is_ai_admin": ai_admin,
            "asr_editable": asr_admin,
            "ai_editable": ai_admin,
        },
    )


@require_http_methods(["GET", "POST"])
def asr_preferences_page(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return _settings_redirect("asr")
    return account_settings_page(request, default_tab="asr")


@require_http_methods(["GET", "POST"])
def system_asr_page(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return _settings_redirect("system-asr")
    return account_settings_page(request, default_tab="system-asr")


@require_http_methods(["GET", "POST"])
def ai_preferences_page(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return _settings_redirect("ai")
    return account_settings_page(request, default_tab="ai")


@require_http_methods(["GET", "POST"])
def system_ai_page(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return _settings_redirect("system-ai")
    return account_settings_page(request, default_tab="system-ai")


def home(request: HttpRequest) -> HttpResponse:
    if getattr(request, "identity_user", None) is None:
        return redirect("identity")
    return redirect("project-list")
