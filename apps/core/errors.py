"""Domain service errors — codes align with Gate 2 API envelope."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base domain error with stable machine code."""

    code: str = "DOMAIN_ERROR"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    http_status = 404


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    http_status = 422


class ConflictError(DomainError):
    code = "CONFLICT"
    http_status = 409


class ForbiddenError(DomainError):
    code = "FORBIDDEN"
    http_status = 403


class UnauthorizedError(DomainError):
    code = "UNAUTHORIZED"
    http_status = 401


class ProjectArchivedError(ConflictError):
    code = "PROJECT_ARCHIVED"


class SegmentDeletedError(ConflictError):
    code = "SEGMENT_DELETED"


class SegmentRevisionConflictError(ConflictError):
    code = "SEGMENT_REVISION_CONFLICT"


class SourceDuplicateError(ConflictError):
    code = "SOURCE_DUPLICATE"


class ActiveJobExistsError(ConflictError):
    code = "ACTIVE_JOB_EXISTS"


class LabelInactiveError(ConflictError):
    code = "LABEL_INACTIVE"


class InvalidStateTransitionError(ConflictError):
    code = "INVALID_STATE_TRANSITION"


class ArtifactNotVerifiedError(ConflictError):
    code = "ARTIFACT_NOT_VERIFIED"


class ArtifactRequiredError(ValidationError):
    code = "ARTIFACT_REQUIRED"
    http_status = 422


class AsrLimitExceededError(ValidationError):
    code = "ASR_LIMIT_EXCEEDED"
    http_status = 422


class AsrProviderMisconfiguredError(ValidationError):
    code = "ASR_PROVIDER_MISCONFIGURED"
    http_status = 422


class AsrRunNotCurrentError(ConflictError):
    code = "ASR_RUN_NOT_CURRENT"


class IdempotencyKeyReuseMismatchError(ConflictError):
    code = "IDEMPOTENCY_KEY_REUSE_MISMATCH"


class IdempotencyInProgressError(ConflictError):
    code = "IDEMPOTENCY_IN_PROGRESS"
