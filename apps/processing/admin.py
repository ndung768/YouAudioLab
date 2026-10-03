from django.contrib import admin

from apps.processing.models import (
    IdempotencyRecord,
    ProcessingArtifact,
    ProcessingJob,
    SourceMediaCache,
)


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "segment",
        "status",
        "expected_revision",
        "attempt_n",
        "cancel_requested_at",
        "error_code",
    )
    list_filter = ("status",)
    readonly_fields = ("config_snapshot",)


@admin.register(ProcessingArtifact)
class ProcessingArtifactAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "verified", "format", "sample_rate_hz", "file_size_bytes")
    list_filter = ("verified",)


@admin.register(SourceMediaCache)
class SourceMediaCacheAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "storage_key", "file_size_bytes")


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "actor_user", "method", "route", "key", "status")
    list_filter = ("status", "method")
