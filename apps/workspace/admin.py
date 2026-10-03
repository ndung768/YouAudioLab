from django.contrib import admin

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
    VideoSource,
)


@admin.register(AppUser)
class AppUserAdmin(admin.ModelAdmin):
    list_display = ("id", "display_name", "login_identifier", "status")
    search_fields = ("display_name", "login_identifier")


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
