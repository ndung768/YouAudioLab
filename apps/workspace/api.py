"""DRF endpoints for users, projects, sources, segments, labels, annotations."""

from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.serializers import (
    AnnotationCreateSerializer,
    AssignmentBatchCreateSerializer,
    AssignmentReassignSerializer,
    LabelCreateSerializer,
    LabelUpdateSerializer,
    MemberCreateSerializer,
    ProjectCreateSerializer,
    ProjectSettingsUpdateSerializer,
    ProjectUpdateSerializer,
    SegmentCreateSerializer,
    SegmentUpdateSerializer,
    SourceCreateSerializer,
    SourceUpdateSerializer,
    UserCreateSerializer,
    annotation_out,
    assignment_batch_out,
    assignment_out,
    label_out,
    list_out,
    member_out,
    project_out,
    segment_out,
    settings_out,
    source_out,
    user_out,
)
from apps.processing.enqueue import enqueue_fetch_source_metadata
from apps.workspace.services import (
    AnnotationService,
    AssignmentService,
    ExportService,
    IdentityService,
    LabelService,
    MembershipService,
    ProjectService,
    QualityReportService,
    SegmentService,
    SourceService,
)


def _principal(request):
    return request.user


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def create_user(request):
    """Passwordless bootstrap — development/test only (Gate A1)."""
    from django.conf import settings

    from apps.core.errors import ForbiddenError

    env = (getattr(settings, "ENVIRONMENT", "development") or "").strip().lower()
    if env not in {"development", "test"}:
        raise ForbiddenError(
            "Passwordless user bootstrap is disabled outside development/test",
            details={"code": "BOOTSTRAP_DISABLED"},
        )
    ser = UserCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = IdentityService().create_user(**ser.validated_data)
    return Response(user_out(user), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsIdentified])
def me(request):
    principal = _principal(request)
    return Response(
        {
            "user_id": str(principal.user_id),
            "display_name": principal.display_name,
            "login_identifier": principal.login_identifier,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def projects(request):
    principal = _principal(request)
    projects_svc = ProjectService()
    if request.method == "GET":
        items = [project_out(p) for p in projects_svc.list_for_user(principal.user_id)]
        return Response(list_out(items))
    ser = ProjectCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    project = projects_svc.create(
        name=data["name"],
        owner_user_id=principal.user_id,
        description=data.get("description"),
        language=data.get("language", "vi"),
    )
    return Response(project_out(project), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def project_detail(request, project_id):
    principal = _principal(request)
    memberships = MembershipService()
    projects_svc = ProjectService()
    memberships.require_member(project_id, principal.user_id)
    if request.method == "GET":
        return Response(project_out(projects_svc.get(project_id)))
    ser = ProjectUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    kwargs = dict(ser.validated_data)
    if "description" not in request.data:
        kwargs.pop("description", None)
        project = projects_svc.update(
            project_id,
            actor_user_id=principal.user_id,
            **kwargs,
        )
    else:
        project = projects_svc.update(
            project_id,
            actor_user_id=principal.user_id,
            **kwargs,
        )
    return Response(project_out(project))


@api_view(["POST"])
@permission_classes([IsIdentified])
def archive_project(request, project_id):
    project = ProjectService().archive(project_id, actor_user_id=_principal(request).user_id)
    return Response(project_out(project))


@api_view(["GET", "PUT"])
@permission_classes([IsIdentified])
def project_settings(request, project_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    projects_svc = ProjectService()
    if request.method == "GET":
        return Response(settings_out(projects_svc.get_settings(project_id)))
    ser = ProjectSettingsUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = dict(ser.validated_data)
    apply_asr = any(k in request.data for k in ("asr_provider", "asr_model"))
    apply_ai = any(
        k in request.data
        for k in ("ai_enabled", "ai_provider", "ai_ollama_base_url", "ai_ollama_model")
    )
    settings = projects_svc.update_settings(
        project_id,
        actor_user_id=principal.user_id,
        apply_asr_protocol=apply_asr,
        apply_ai_protocol=apply_ai,
        **data,
    )
    return Response(settings_out(settings))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def project_members(request, project_id):
    principal = _principal(request)
    memberships = MembershipService()
    memberships.require_member(project_id, principal.user_id)
    if request.method == "GET":
        items = [member_out(m) for m in memberships.list_active(project_id)]
        return Response(list_out(items))
    ser = MemberCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    member = memberships.add_member(
        project_id=project_id,
        user_id=ser.validated_data["user_id"],
        role=ser.validated_data.get("role", "ANNOTATOR"),
        actor_user_id=principal.user_id,
    )
    return Response(member_out(member), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsIdentified])
def revoke_member(request, project_id, user_id):
    member = MembershipService().revoke_member(
        project_id=project_id,
        user_id=user_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(member_out(member))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def project_sources(request, project_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    sources = SourceService()
    if request.method == "GET":
        items = [source_out(s) for s in sources.list_for_project(project_id)]
        return Response(list_out(items))
    ser = SourceCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    with transaction.atomic():
        source = sources.import_source(
            project_id=project_id,
            youtube_url=ser.validated_data["youtube_url"],
            actor_user_id=principal.user_id,
        )
        enqueue_fetch_source_metadata(source.id)
    return Response(source_out(source), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def source_detail(request, project_id, source_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    sources = SourceService()
    source = sources.get_for_project(project_id, source_id)
    if request.method == "GET":
        return Response(source_out(source))
    ser = SourceUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    kwargs = {}
    if "title" in request.data:
        kwargs["title"] = ser.validated_data.get("title")
    if "channel_name" in request.data:
        kwargs["channel_name"] = ser.validated_data.get("channel_name")
    source = sources.update_display_metadata(
        source_id,
        actor_user_id=principal.user_id,
        **kwargs,
    )
    return Response(source_out(source))


@api_view(["POST"])
@permission_classes([IsIdentified])
def refresh_metadata(request, project_id, source_id):
    sources = SourceService()
    sources.get_for_project(project_id, source_id)
    with transaction.atomic():
        source = sources.request_metadata_refresh(
            source_id,
            actor_user_id=_principal(request).user_id,
        )
        enqueue_fetch_source_metadata(source.id)
    return Response(source_out(source))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def source_segments(request, project_id, source_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    sources = SourceService()
    source = sources.get_for_project(project_id, source_id)
    segments = SegmentService()
    if request.method == "GET":
        include_deleted = str(request.query_params.get("include_deleted", "")).lower() == "true"
        items = [
            segment_out(s, source.project_id)
            for s in segments.list_for_source(source_id, include_deleted=include_deleted)
        ]
        return Response(list_out(items))
    ser = SegmentCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    segment = segments.create(
        source_id=source_id,
        actor_user_id=principal.user_id,
        **ser.validated_data,
    )
    return Response(segment_out(segment, source.project_id), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsIdentified])
def segment_detail(request, segment_id):
    principal = _principal(request)
    segments = SegmentService()
    segment = segments.get(segment_id)
    MembershipService().require_member(segment.source.project_id, principal.user_id)
    if request.method == "GET":
        return Response(segment_out(segment, segment.source.project_id))
    if request.method == "DELETE":
        segment = segments.soft_delete(segment_id, actor_user_id=principal.user_id)
        return Response(segment_out(segment, segment.source.project_id))
    ser = SegmentUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = dict(ser.validated_data)
    expected = data.pop("expected_definition_revision")
    kwargs = {"expected_definition_revision": expected}
    if "start_seconds" in data:
        kwargs["start_seconds"] = data["start_seconds"]
    if "end_seconds" in data:
        kwargs["end_seconds"] = data["end_seconds"]
    if "transcript" in request.data:
        kwargs["transcript"] = data.get("transcript")
    segment = segments.update(segment_id, actor_user_id=principal.user_id, **kwargs)
    return Response(segment_out(segment, segment.source.project_id))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def project_labels(request, project_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    labels = LabelService()
    if request.method == "GET":
        raw = request.query_params.get("is_active")
        active_only = None
        if raw is not None:
            active_only = str(raw).lower() == "true"
        items = [label_out(lbl) for lbl in labels.list_for_project(project_id, active_only=active_only)]
        return Response(list_out(items))
    ser = LabelCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    label = labels.create(
        project_id=project_id,
        actor_user_id=principal.user_id,
        **ser.validated_data,
    )
    return Response(label_out(label), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
@permission_classes([IsIdentified])
def label_detail(request, project_id, label_id):
    principal = _principal(request)
    MembershipService().require_member(project_id, principal.user_id)
    labels = LabelService()
    label = labels.get_for_project(project_id, label_id)
    if request.method == "GET":
        return Response(label_out(label))
    ser = LabelUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    kwargs = {}
    if "name" in request.data:
        kwargs["name"] = ser.validated_data.get("name")
    if "description" in request.data:
        kwargs["description"] = ser.validated_data.get("description")
    if "color" in request.data:
        kwargs["color"] = ser.validated_data.get("color")
    if "sort_order" in request.data:
        kwargs["sort_order"] = ser.validated_data.get("sort_order")
    label = labels.update(label_id, actor_user_id=principal.user_id, **kwargs)
    return Response(label_out(label))


@api_view(["POST"])
@permission_classes([IsIdentified])
def deactivate_label(request, project_id, label_id):
    LabelService().get_for_project(project_id, label_id)
    label = LabelService().deactivate(label_id, actor_user_id=_principal(request).user_id)
    return Response(label_out(label))


@api_view(["POST"])
@permission_classes([IsIdentified])
def activate_label(request, project_id, label_id):
    LabelService().get_for_project(project_id, label_id)
    label = LabelService().activate(label_id, actor_user_id=_principal(request).user_id)
    return Response(label_out(label))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def segment_annotations(request, segment_id):
    principal = _principal(request)
    annotations = AnnotationService()
    if request.method == "GET":
        segment = SegmentService().get(segment_id)
        membership = MembershipService().require_member(
            segment.source.project_id, principal.user_id
        )
        include_removed = str(request.query_params.get("include_removed", "")).lower() == "true"
        settings = ProjectService().get_settings(segment.source.project_id)
        annotator_id = (
            principal.user_id
            if membership.role == "ANNOTATOR" and settings.blind_annotators
            else None
        )
        items = [
            annotation_out(a)
            for a in annotations.list_for_segment(
                segment_id,
                actor_user_id=principal.user_id,
                include_removed=include_removed,
                annotator_id=annotator_id,
            )
        ]
        return Response(list_out(items))
    ser = AnnotationCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    ann = annotations.assign(
        segment_id=segment_id,
        label_id=ser.validated_data["label_id"],
        actor_user_id=principal.user_id,
    )
    return Response(annotation_out(ann), status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsIdentified])
def remove_annotation(request, annotation_id):
    ann = AnnotationService().remove(
        annotation_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(annotation_out(ann))


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def project_assignments(request, project_id):
    principal = _principal(request)
    svc = AssignmentService()
    if request.method == "GET":
        status_filter = request.query_params.get("status") or None
        assignee_raw = request.query_params.get("assignee_id")
        source_raw = request.query_params.get("source_id")
        items = [
            assignment_out(a)
            for a in svc.list_for_project(
                project_id,
                actor_user_id=principal.user_id,
                status=status_filter,
                assignee_id=assignee_raw,
                source_id=source_raw,
            )
        ]
        return Response(list_out(items))
    ser = AssignmentBatchCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    batch, created = svc.create_batch(
        project_id=project_id,
        actor_user_id=principal.user_id,
        assignee_ids=data["assignee_ids"],
        source_id=data.get("source_id"),
        segment_ids=data.get("segment_ids"),
        limit=data.get("limit"),
        distribute=data.get("distribute", "split"),
        priority=data.get("priority", 0),
        name=data.get("name") or None,
        notes=data.get("notes") or None,
        assignment_group_id=data.get("assignment_group_id"),
    )
    hydrated = [svc.get(a.id) for a in created]
    return Response(
        assignment_batch_out(batch, hydrated),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsIdentified])
def project_assignments_mine(request, project_id):
    principal = _principal(request)
    status_filter = request.query_params.get("status") or None
    items = [
        assignment_out(a)
        for a in AssignmentService().list_mine(
            project_id,
            actor_user_id=principal.user_id,
            status=status_filter,
        )
    ]
    return Response(list_out(items))


@api_view(["POST"])
@permission_classes([IsIdentified])
def assignment_release(request, project_id, assignment_id):
    assignment = AssignmentService().release(
        assignment_id,
        project_id=project_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(assignment_out(assignment))


@api_view(["POST"])
@permission_classes([IsIdentified])
def assignment_start(request, project_id, assignment_id):
    assignment = AssignmentService().start(
        assignment_id,
        project_id=project_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(assignment_out(assignment))


@api_view(["POST"])
@permission_classes([IsIdentified])
def assignment_complete(request, project_id, assignment_id):
    assignment = AssignmentService().complete(
        assignment_id,
        project_id=project_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(assignment_out(assignment))


@api_view(["POST"])
@permission_classes([IsIdentified])
def assignment_reassign(request, project_id, assignment_id):
    ser = AssignmentReassignSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    assignment = AssignmentService().reassign(
        assignment_id,
        project_id=project_id,
        actor_user_id=_principal(request).user_id,
        new_assignee_id=ser.validated_data["new_assignee_id"],
    )
    created = assignment.created_at and str(assignment.id) != str(assignment_id)
    return Response(
        assignment_out(assignment),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def _query_flag(params, name: str, default: bool) -> bool:
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).lower() in {"1", "true", "on", "yes"}


@api_view(["GET"])
@permission_classes([IsIdentified])
def export_formats(request):
    from apps.workspace.services.export_dataset import FORMATS

    return Response(
        {
            "items": [
                {
                    "key": item.key,
                    "label": item.label,
                    "group": item.group,
                    "extension": item.extension,
                    "description": item.description,
                }
                for item in FORMATS.values()
            ]
        }
    )


@api_view(["GET"])
@permission_classes([IsIdentified])
def project_export(request, project_id):
    from django.http import HttpResponse

    export_format = request.query_params.get("export_format") or "json"
    source_raw = request.query_params.get("source_id") or None

    def _qfloat(name: str, default: float) -> float:
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _qint(name: str, default: int) -> int:
        raw = request.query_params.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    snapshot = ExportService().build_snapshot(
        project_id,
        actor_user_id=_principal(request).user_id,
        source_id=source_raw,
        include_deleted_segments=_query_flag(request.query_params, "include_deleted_segments", False),
        include_removed_annotations=_query_flag(
            request.query_params, "include_removed_annotations", True
        ),
        include_released_assignments=_query_flag(
            request.query_params, "include_released_assignments", True
        ),
        include_stale_asr=_query_flag(request.query_params, "include_stale_asr", True),
        ready_only=_query_flag(request.query_params, "ready_only", False),
        split_strategy=(request.query_params.get("split_strategy") or "by_source").strip(),
        split_seed=_qint("split_seed", 42),
        split_train=_qfloat("split_train", 0.8),
        split_val=_qfloat("split_val", 0.1),
        split_test=_qfloat("split_test", 0.1),
        supervision_policy=(
            request.query_params.get("supervision_policy") or "majority"
        ).strip(),
    )
    body, meta = ExportService().render(snapshot, export_format)
    response = HttpResponse(body, content_type=meta.content_type)
    response["Content-Disposition"] = f'attachment; filename="export-{meta.key}{meta.extension}"'
    return response


@api_view(["GET"])
@permission_classes([IsIdentified])
def project_quality_report(request, project_id):
    report = QualityReportService().build(
        project_id,
        actor_user_id=_principal(request).user_id,
    )
    return Response(report.to_dict())
