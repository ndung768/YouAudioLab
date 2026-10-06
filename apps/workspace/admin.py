from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.workspace.models import (
    AppUser,
    AudioSegment,
    Label,
    Project,
    ProjectLabel,
    ProjectMembership,
    ProjectSettings,
    SegmentAnnotation,
    SegmentGoldLabel,
    TranscriptSpan,
    VideoSource,
)


@admin.register(AppUser)
class AppUserAdmin(DjangoUserAdmin):
    ordering = ("login_identifier",)
    list_display = (
        "login_identifier",
        "display_name",
        "status",
        "is_staff",
        "is_superuser",
        "is_active",
    )
    search_fields = ("display_name", "login_identifier")
    list_filter = ("status", "is_staff", "is_superuser", "is_active")
    fieldsets = (
        (None, {"fields": ("login_identifier", "password")}),
        ("Profile", {"fields": ("display_name", "status")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "login_identifier",
                    "display_name",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                    "status",
                ),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")
    filter_horizontal = ("groups", "user_permissions")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "language", "license", "status")
    list_filter = ("status",)


@admin.register(ProjectSettings)
class ProjectSettingsAdmin(admin.ModelAdmin):
    list_display = ("project", "output_format", "sample_rate_hz", "blind_annotators")


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "user", "role", "revoked_at")
    list_filter = ("role",)


@admin.register(VideoSource)
class VideoSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "youtube_video_id", "title", "source_status")
    list_filter = ("source_status",)


@admin.register(AudioSegment)
class AudioSegmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source",
        "segment_index",
        "start_seconds",
        "end_seconds",
        "definition_revision",
        "processing_status",
        "deleted_at",
    )
    list_filter = ("processing_status",)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "name", "is_active")
    list_filter = ("is_active",)


@admin.register(ProjectLabel)
class ProjectLabelAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "label", "sort_order")


@admin.register(SegmentAnnotation)
class SegmentAnnotationAdmin(admin.ModelAdmin):
    list_display = ("id", "segment", "label", "annotator", "removed_at")


@admin.register(SegmentGoldLabel)
class SegmentGoldLabelAdmin(admin.ModelAdmin):
    list_display = ("id", "segment", "label", "adjudicated_by", "created_at")


@admin.register(TranscriptSpan)
class TranscriptSpanAdmin(admin.ModelAdmin):
    list_display = ("id", "segment", "label", "quote", "annotator", "stale", "removed_at")
