"""DRF endpoints for ASR jobs and runs (Phase 2 W2–W5)."""

from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.serializers import (
    AsrJobSubmitSerializer,
    AsrRunApplySerializer,
    asr_run_out,
    job_out,
    list_out,
    segment_out,
)
from apps.core.storage import get_storage
from apps.processing.enqueue import enqueue_transcribe_segment_audio
from apps.processing.services.asr import AsrService
from apps.processing.services.idempotency import IdempotencyService, fingerprint_payload
from apps.workspace.services import MembershipService, SegmentService


def _principal(request):
    return request.user


def _asr() -> AsrService:
    return AsrService(get_storage())


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def segment_asr_jobs(request, segment_id):
    principal = _principal(request)
    asr = _asr()
    if request.method == "GET":
        items = [
            job_out(j)
            for j in asr.list_asr_jobs_for_segment(
                segment_id, actor_user_id=principal.user_id
            )
        ]
        return Response(list_out(items))

    ser = AsrJobSubmitSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    idem_key = request.headers.get("Idempotency-Key")
    idem = IdempotencyService()
    record = None
    route = request.path
    payload_hash = fingerprint_payload(
        {
            "segment_id": str(segment_id),
            "expected_definition_revision": data["expected_definition_revision"],
            "language": data.get("language"),
            "model_size": data.get("model_size"),
            "provider": data.get("provider"),
            "model": data.get("model"),
            "force": data.get("force", False),
            "job_type": "TRANSCRIBE_SEGMENT_AUDIO",
        }
    )
    with transaction.atomic():
        if idem_key:
            outcome = idem.begin(
                actor_user_id=principal.user_id,
                method="POST",
                route=route,
                key=idem_key,
                request_hash=payload_hash,
            )
            if outcome.kind == "replay":
                return Response(outcome.record.response_body, status=status.HTTP_200_OK)
            record = outcome.record
        job, created = asr.submit(
            segment_id=segment_id,
            expected_definition_revision=data["expected_definition_revision"],
            actor_user_id=principal.user_id,
            language=data.get("language"),
            model_size=data.get("model_size"),
            provider=data.get("provider"),
            model=data.get("model"),
            force=bool(data.get("force", False)),
            idempotency_key=idem_key,
        )
        body = job_out(job)
        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        if record is not None:
            idem.complete(record, response_status=http_status, response_body=body)
        if created:
            enqueue_transcribe_segment_audio(job.id)
        return Response(body, status=http_status)


@api_view(["GET"])
@permission_classes([IsIdentified])
def segment_asr_runs(request, segment_id):
    principal = _principal(request)
    items = [
        asr_run_out(r)
        for r in _asr().list_runs_for_segment(segment_id, actor_user_id=principal.user_id)
    ]
    return Response(list_out(items))


@api_view(["GET"])
@permission_classes([IsIdentified])
def asr_run_detail(request, asr_run_id):
    principal = _principal(request)
    run = _asr().get_run(asr_run_id)
    MembershipService().require_member(run.project_id, principal.user_id)
    segment = SegmentService().get(run.segment_id)
    if segment.deleted_at is not None:
        from apps.core.errors import NotFoundError

        raise NotFoundError("ASR run not found", details={"asr_run_id": str(asr_run_id)})
    return Response(asr_run_out(run))


@api_view(["POST"])
@permission_classes([IsIdentified])
def apply_asr_run(request, asr_run_id):
    principal = _principal(request)
    ser = AsrRunApplySerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    segment = _asr().apply(
        asr_run_id,
        expected_definition_revision=ser.validated_data["expected_definition_revision"],
        actor_user_id=principal.user_id,
    )
    return Response(segment_out(segment, segment.source.project_id))
