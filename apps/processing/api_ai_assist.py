"""AI assist API — Gate W8.2/W8.3 (candidate + human Apply)."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.errors import NotFoundError, ValidationError
from apps.core.serializers import (
    AiAssistApplySerializer,
    AiAssistCreateSerializer,
    ai_assist_run_out,
    list_out,
    segment_out,
)
from apps.processing.services.ai_assist import SUPPORTED_KINDS, AiAssistService
from apps.workspace.services import MembershipService, SegmentService, SourceService


def _principal(request):
    return request.user


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def segment_ai_assists(request, segment_id):
    principal = _principal(request)
    assists = AiAssistService()
    if request.method == "GET":
        segment = SegmentService().get(segment_id)
        if segment.deleted_at is not None:
            raise NotFoundError("Segment not found", details={"segment_id": str(segment_id)})
        source = SourceService().get(segment.source_id)
        MembershipService().require_member(source.project_id, principal.user_id)
        items = [ai_assist_run_out(r) for r in assists.list_for_segment(segment_id)]
        return Response(list_out(items))

    ser = AiAssistCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    kind = (data.get("kind") or "transcript_cleanup").strip().lower()
    if kind not in SUPPORTED_KINDS:
        raise ValidationError(
            "Unsupported AI assist kind",
            details={
                "fields": [
                    {
                        "field": "kind",
                        "code": "INVALID",
                        "allowed": sorted(SUPPORTED_KINDS),
                    }
                ]
            },
        )
    run = assists.create(
        segment_id=segment_id,
        actor_user_id=principal.user_id,
        expected_definition_revision=data["expected_definition_revision"],
        kind=kind,
    )
    return Response(ai_assist_run_out(run), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsIdentified])
def apply_ai_assist(request, segment_id, assist_run_id):
    principal = _principal(request)
    ser = AiAssistApplySerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    assists = AiAssistService()
    run = assists.get(assist_run_id)
    if run.segment_id != segment_id:
        raise NotFoundError(
            "AI assist run not found",
            details={"assist_run_id": str(assist_run_id)},
        )
    segment = assists.apply(
        assist_run_id,
        expected_definition_revision=ser.validated_data["expected_definition_revision"],
        actor_user_id=principal.user_id,
    )
    return Response(segment_out(segment, segment.source.project_id))
