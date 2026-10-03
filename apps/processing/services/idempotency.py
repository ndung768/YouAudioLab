"""HTTP idempotency service — advisory lock + scoped unique row."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from django.db import IntegrityError, connection, transaction

from apps.core.errors import (
    IdempotencyInProgressError,
    IdempotencyKeyReuseMismatchError,
    ValidationError,
)
from apps.processing.models import IdempotencyRecord

OutcomeKind = Literal["new", "replay"]


@dataclass
class IdempotencyOutcome:
    kind: OutcomeKind
    record: IdempotencyRecord


def fingerprint_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _advisory_lock_key(
    actor_user_id: uuid.UUID,
    method: str,
    route: str,
    key: str,
) -> int:
    digest = hashlib.sha256(
        f"{actor_user_id}|{method}|{route}|{key}".encode("utf-8")
    ).hexdigest()
    return int(digest[:16], 16) % (2**63)


class IdempotencyService:
    def begin(
        self,
        *,
        actor_user_id: uuid.UUID,
        method: str,
        route: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyOutcome:
        if not key or len(key) > 128:
            raise ValidationError(
                "Idempotency-Key must be 1..128 characters",
                details={"fields": [{"field": "Idempotency-Key", "code": "INVALID"}]},
            )

        lock_id = _advisory_lock_key(actor_user_id, method.upper(), route, key)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])

        existing = IdempotencyRecord.objects.filter(
            actor_user_id=actor_user_id,
            method=method.upper(),
            route=route,
            key=key,
        ).first()

        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReuseMismatchError(
                    "Idempotency-Key reused with a different request payload",
                    details={
                        "key": key,
                        "route": route,
                        "method": method.upper(),
                    },
                )
            if (
                existing.status == IdempotencyRecord.Status.COMPLETED
                and existing.response_status is not None
            ):
                return IdempotencyOutcome(kind="replay", record=existing)
            if existing.status == IdempotencyRecord.Status.IN_PROGRESS:
                raise IdempotencyInProgressError(
                    "Idempotent request is still in progress",
                    details={"key": key, "route": route},
                )
            if existing.status == IdempotencyRecord.Status.FAILED:
                existing.status = IdempotencyRecord.Status.IN_PROGRESS
                existing.request_hash = request_hash
                existing.response_status = None
                existing.response_body = None
                existing.completed_at = None
                existing.save()
                return IdempotencyOutcome(kind="new", record=existing)

        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    actor_user_id=actor_user_id,
                    method=method.upper(),
                    route=route,
                    key=key,
                    request_hash=request_hash,
                    status=IdempotencyRecord.Status.IN_PROGRESS,
                )
        except IntegrityError as exc:
            existing = IdempotencyRecord.objects.filter(
                actor_user_id=actor_user_id,
                method=method.upper(),
                route=route,
                key=key,
            ).first()
            if existing is None:
                raise
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReuseMismatchError(
                    "Idempotency-Key reused with a different request payload",
                    details={"key": key},
                ) from exc
            if existing.status == IdempotencyRecord.Status.COMPLETED:
                return IdempotencyOutcome(kind="replay", record=existing)
            raise IdempotencyInProgressError(
                "Idempotent request is still in progress",
                details={"key": key},
            ) from exc

        return IdempotencyOutcome(kind="new", record=record)

    def complete(
        self,
        record: IdempotencyRecord,
        *,
        response_status: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        record.status = IdempotencyRecord.Status.COMPLETED
        record.response_status = response_status
        record.response_body = response_body
        record.completed_at = datetime.now(timezone.utc)
        record.save()
        return record

    def fail(self, record: IdempotencyRecord) -> None:
        record.status = IdempotencyRecord.Status.FAILED
        record.response_status = None
        record.response_body = None
        record.completed_at = datetime.now(timezone.utc)
        record.save()
