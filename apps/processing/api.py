"""DRF endpoints for jobs and artifacts."""

from __future__ import annotations

from django.db import transaction
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.core.api_permissions import IsIdentified
from apps.core.errors import ArtifactNotVerifiedError, DomainError, NotFoundError
from apps.core.serializers import JobSubmitSerializer, artifact_out, job_out, list_out
from apps.core.storage import get_storage
from apps.processing.enqueue import enqueue_extract_segment_audio
from apps.processing.services.idempotency import IdempotencyService, fingerprint_payload
from apps.processing.services.job import JobService
from apps.workspace.services import MembershipService, SegmentService, SourceService


def _principal(request):
    return request.user


def _jobs() -> JobService:
    return JobService(get_storage())


@api_view(["GET", "POST"])
@permission_classes([IsIdentified])
def segment_jobs(request, segment_id):
    principal = _principal(request)
    jobs = _jobs()
    segments = SegmentService()
    sources = SourceService()
    memberships = MembershipService()
    segment = segments.get(segment_id)
    source = sources.get(segment.source_id)
    memberships.require_member(source.project_id, principal.user_id)

    if request.method == "GET":
        items = [job_out(j) for j in jobs.list_for_segment(segment_id)]
        return Response(list_out(items))

    ser = JobSubmitSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    idem_key = request.headers.get("Idempotency-Key")
    idem = IdempotencyService()
    record = None
    route = request.path
    payload_hash = fingerprint_payload(
        {
            "segment_id": str(segment_id),
            "expected_definition_revision": ser.validated_data["expected_definition_revision"],
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
        try:
            job = jobs.submit(
                segment_id=segment_id,
                expected_definition_revision=ser.validated_data["expected_definition_revision"],
                actor_user_id=principal.user_id,
                idempotency_key=idem_key,
            )
            body = job_out(job)
            if record is not None:
                idem.complete(record, response_status=201, response_body=body)
            enqueue_extract_segment_audio(job.id)
            return Response(body, status=status.HTTP_201_CREATED)
        except DomainError:
            if record is not None:
                idem.fail(record)
            raise
        except Exception:
            if record is not None:
                idem.fail(record)
            raise


@api_view(["GET"])
@permission_classes([IsIdentified])
def project_jobs(request, project_id):
    MembershipService().require_member(project_id, _principal(request).user_id)
    items = [job_out(j) for j in _jobs().list_for_project(project_id)]
    return Response(list_out(items))


@api_view(["GET"])
@permission_classes([IsIdentified])
def job_detail(request, job_id):
    jobs = _jobs()
    job = jobs.get(job_id)
    MembershipService().require_member(job.project_id, _principal(request).user_id)
    return Response(job_out(job))


@api_view(["POST"])
@permission_classes([IsIdentified])
def cancel_job(request, job_id):
    job = _jobs().cancel(job_id, actor_user_id=_principal(request).user_id)
    return Response(job_out(job))


@api_view(["POST"])
@permission_classes([IsIdentified])
def retry_job(request, job_id):
    principal = _principal(request)
    jobs = _jobs()
    idem_key = request.headers.get("Idempotency-Key")
    idem = IdempotencyService()
    record = None
    route = request.path
    payload_hash = fingerprint_payload({"job_id": str(job_id), "op": "retry"})

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
        try:
            job = jobs.retry(
                job_id,
                actor_user_id=principal.user_id,
                idempotency_key=idem_key,
            )
            body = job_out(job)
            if record is not None:
                idem.complete(record, response_status=201, response_body=body)
            if job.job_type == "TRANSCRIBE_SEGMENT_AUDIO":
                from apps.processing.enqueue import enqueue_transcribe_segment_audio

                enqueue_transcribe_segment_audio(job.id)
            else:
                enqueue_extract_segment_audio(job.id)
            return Response(body, status=status.HTTP_201_CREATED)
        except DomainError:
            if record is not None:
                idem.fail(record)
            raise
        except Exception:
            if record is not None:
                idem.fail(record)
            raise


@api_view(["GET"])
@permission_classes([IsIdentified])
def artifact_detail(request, artifact_id):
    jobs = _jobs()
    artifact = jobs.get_artifact(artifact_id)
    job = jobs.get(artifact.job_id)
    MembershipService().require_member(job.project_id, _principal(request).user_id)
    return Response(artifact_out(artifact, job.segment_id))


@api_view(["GET"])
@permission_classes([IsIdentified])
def artifact_content(request, artifact_id):
    jobs = _jobs()
    storage = get_storage()
    artifact = jobs.get_artifact(artifact_id)
    job = jobs.get(artifact.job_id)
    MembershipService().require_member(job.project_id, _principal(request).user_id)
    if not artifact.verified:
        raise ArtifactNotVerifiedError(
            "Artifact not verified",
            details={"artifact_id": str(artifact_id)},
        )
    if not storage.exists(artifact.storage_key):
        raise NotFoundError(
            "Artifact content missing",
            details={"artifact_id": str(artifact_id)},
        )
    data = storage.get(artifact.storage_key)
    media_type = "audio/wav" if artifact.format.upper() == "WAV" else "application/octet-stream"
    response = HttpResponse(data, content_type=media_type)
    response["Content-Disposition"] = (
        f'attachment; filename="{artifact_id}.{artifact.format.lower()}"'
    )
    return response
