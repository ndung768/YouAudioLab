"""AnnotaHub-style labels: user-owned Label + project assignment via ProjectLabel."""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower

from apps.core.errors import NotFoundError, ValidationError
from apps.workspace.models import Label, ProjectLabel, ProjectMembership
from apps.workspace.services.membership import MembershipService


class LabelService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    def _owner_id_for_project(self, project_id: uuid.UUID) -> uuid.UUID:
        membership = (
            ProjectMembership.objects.filter(
                project_id=project_id,
                role=ProjectMembership.Role.OWNER,
                revoked_at__isnull=True,
            )
            .order_by("created_at")
            .first()
        )
        if membership is None:
            raise NotFoundError(
                "Project owner not found",
                details={"project_id": str(project_id)},
            )
        return membership.user_id

    def get_canonical(self, label_id: uuid.UUID) -> Label:
        try:
            return Label.objects.get(pk=label_id)
        except Label.DoesNotExist as exc:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(label_id)},
            ) from exc

    def get(self, project_label_id: uuid.UUID) -> ProjectLabel:
        try:
            return ProjectLabel.objects.select_related("label", "project").get(pk=project_label_id)
        except ProjectLabel.DoesNotExist as exc:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(project_label_id)},
            ) from exc

    def get_for_project(self, project_id: uuid.UUID, project_label_id: uuid.UUID) -> ProjectLabel:
        pl = self.get(project_label_id)
        if pl.project_id != project_id:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(project_label_id)},
            )
        return pl

    def list_owned(
        self,
        user_id: uuid.UUID,
        *,
        active_only: bool | None = None,
    ) -> list[Label]:
        qs = Label.objects.filter(owner_id=user_id).annotate(
            project_count=Count("project_labels", distinct=True),
            usage_count=Count(
                "project_labels__annotations",
                filter=Q(project_labels__annotations__removed_at__isnull=True),
                distinct=True,
            ),
        ).order_by("name")
        if active_only is True:
            qs = qs.filter(is_active=True)
        elif active_only is False:
            qs = qs.filter(is_active=False)
        return list(qs)

    def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        active_only: bool | None = None,
        scope: str | None = None,
    ) -> list[ProjectLabel]:
        qs = (
            ProjectLabel.objects.filter(project_id=project_id)
            .select_related("label")
            .order_by("sort_order", "label__name")
        )
        if scope == "segment":
            qs = qs.filter(scope__in=ProjectLabel.SEGMENT_SCOPES)
        elif scope == "span":
            qs = qs.filter(scope__in=ProjectLabel.SPAN_SCOPES)
        if active_only is True:
            qs = qs.filter(label__is_active=True)
        elif active_only is False:
            qs = qs.filter(label__is_active=False)
        return list(qs)

    def list_available_for_project(self, project_id: uuid.UUID) -> list[Label]:
        owner_id = self._owner_id_for_project(project_id)
        assigned = ProjectLabel.objects.filter(project_id=project_id).values_list(
            "label_id",
            flat=True,
        )
        return list(
            Label.objects.filter(owner_id=owner_id, is_active=True)
            .exclude(id__in=assigned)
            .order_by("name"),
        )

    def owned_project_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        return set(
            ProjectMembership.objects.filter(
                user_id=user_id,
                role=ProjectMembership.Role.OWNER,
                revoked_at__isnull=True,
            ).values_list("project_id", flat=True),
        )

    def create_global(
        self,
        *,
        owner_user_id: uuid.UUID,
        name: str,
        description: str | None = None,
        include_guidance: str | None = None,
        exclude_guidance: str | None = None,
        color: str | None = None,
        default_scope: str | None = None,
    ) -> Label:
        name = (name or "").strip()
        if not name:
            raise ValidationError(
                "Label name is required",
                details={"fields": [{"field": "name", "code": "REQUIRED"}]},
            )
        try:
            with transaction.atomic():
                return Label.objects.create(
                    owner_id=owner_user_id,
                    name=name,
                    description=description,
                    include_guidance=include_guidance,
                    exclude_guidance=exclude_guidance,
                    color=color,
                    default_scope=self._clean_scope(default_scope),
                    is_active=True,
                )
        except IntegrityError as exc:
            raise ValidationError(
                "Label name already exists in your catalog",
                details={"fields": [{"field": "name", "code": "DUPLICATE_NAME"}]},
            ) from exc

    def create(
        self,
        *,
        project_id: uuid.UUID,
        name: str,
        actor_user_id: uuid.UUID,
        description: str | None = None,
        color: str | None = None,
        sort_order: int = 0,
        scope: str | None = None,
    ) -> ProjectLabel:
        """Create (or reuse) a catalog label and assign it to the project."""
        explicit_scope = scope is not None
        scope_value = self._clean_scope(scope)
        self.memberships.require_owner(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        owner_id = self._owner_id_for_project(project_id)

        name = (name or "").strip()
        if not name:
            raise ValidationError(
                "Label name is required",
                details={"fields": [{"field": "name", "code": "REQUIRED"}]},
            )

        try:
            with transaction.atomic():
                label = (
                    Label.objects.annotate(name_lower=Lower("name"))
                    .filter(owner_id=owner_id, name_lower=name.lower())
                    .first()
                )
                if label is None:
                    label = Label.objects.create(
                        owner_id=owner_id,
                        name=name,
                        description=description,
                        color=color,
                        default_scope=scope_value,
                        is_active=True,
                    )
                project_scope = scope_value if explicit_scope else label.default_scope
                pl, created = ProjectLabel.objects.get_or_create(
                    project_id=project_id,
                    label_id=label.id,
                    defaults={"sort_order": sort_order, "scope": project_scope},
                )
                if not created:
                    raise ValidationError(
                        "Label is already assigned to this project",
                        details={
                            "fields": [{"field": "name", "code": "DUPLICATE_NAME"}],
                            "project_id": str(project_id),
                        },
                    )
                return pl
        except IntegrityError as exc:
            raise ValidationError(
                "Label is already assigned to this project",
                details={
                    "fields": [{"field": "name", "code": "DUPLICATE_NAME"}],
                    "project_id": str(project_id),
                },
            ) from exc

    def _clean_scope(self, scope: str | None) -> str:
        value = (scope or ProjectLabel.Scope.BOTH).strip().upper()
        if value not in ProjectLabel.Scope.values:
            raise ValidationError(
                "Unknown label scope",
                details={"fields": [{"field": "scope", "code": "INVALID"}]},
            )
        return value

    def add_to_project(
        self,
        *,
        project_id: uuid.UUID,
        label_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> ProjectLabel:
        self.memberships.require_owner(project_id, actor_user_id)
        self.memberships.require_active_project(project_id)
        owner_id = self._owner_id_for_project(project_id)

        label = self.get_canonical(label_id)
        if label.owner_id != owner_id:
            raise NotFoundError(
                "Label not found",
                details={"label_id": str(label_id)},
            )
        pl, _ = ProjectLabel.objects.get_or_create(
            project_id=project_id,
            label_id=label.id,
            defaults={"scope": label.default_scope},
        )
        return pl

    def remove_from_project(
        self,
        project_label_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> None:
        pl = self.get(project_label_id)
        self.memberships.require_owner(pl.project_id, actor_user_id)
        self.memberships.require_active_project(pl.project_id)
        pl.delete()

    def update_project_label(
        self,
        project_label_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        override_name: str | None | object = ...,
        override_description: str | None | object = ...,
        override_include_guidance: str | None | object = ...,
        override_exclude_guidance: str | None | object = ...,
        override_color: str | None | object = ...,
        sort_order: int | None = None,
        scope: str | None = None,
    ) -> ProjectLabel:
        pl = self.get(project_label_id)
        self.memberships.require_owner(pl.project_id, actor_user_id)
        self.memberships.require_active_project(pl.project_id)

        if scope is not None:
            pl.scope = self._clean_scope(scope)

        if override_name is not ...:
            pl.override_name = override_name  # type: ignore[assignment]
        if override_description is not ...:
            pl.override_description = override_description  # type: ignore[assignment]
        if override_include_guidance is not ...:
            pl.override_include_guidance = override_include_guidance  # type: ignore[assignment]
        if override_exclude_guidance is not ...:
            pl.override_exclude_guidance = override_exclude_guidance  # type: ignore[assignment]
        if override_color is not ...:
            pl.override_color = override_color  # type: ignore[assignment]
        if sort_order is not None:
            pl.sort_order = sort_order
        pl.save()
        return pl

    def update_canonical(
        self,
        label_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        name: str | None = None,
        description: str | None | object = ...,
        include_guidance: str | None | object = ...,
        exclude_guidance: str | None | object = ...,
        color: str | None | object = ...,
        default_scope: str | None = None,
        is_active: bool | None = None,
        sync_project_scopes: bool = False,
    ) -> Label:
        label = self.get_canonical(label_id)
        if label.owner_id != actor_user_id:
            raise NotFoundError("Label not found", details={"label_id": str(label_id)})

        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationError(
                    "Label name cannot be empty",
                    details={"fields": [{"field": "name", "code": "REQUIRED"}]},
                )
            label.name = name
        if description is not ...:
            label.description = description  # type: ignore[assignment]
        if include_guidance is not ...:
            label.include_guidance = include_guidance  # type: ignore[assignment]
        if exclude_guidance is not ...:
            label.exclude_guidance = exclude_guidance  # type: ignore[assignment]
        if default_scope is not None:
            label.default_scope = self._clean_scope(default_scope)
        if color is not ...:
            label.color = color  # type: ignore[assignment]
        if is_active is not None:
            label.is_active = is_active

        try:
            with transaction.atomic():
                label.save()
                if sync_project_scopes and default_scope is not None:
                    ProjectLabel.objects.filter(label_id=label.id).update(
                        scope=label.default_scope
                    )
        except IntegrityError as exc:
            raise ValidationError(
                "Label name already exists in your catalog",
                details={"fields": [{"field": "name", "code": "DUPLICATE_NAME"}]},
            ) from exc
        return label

    def update(
        self,
        project_label_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        name: str | None = None,
        description: str | None | object = ...,
        color: str | None | object = ...,
        sort_order: int | None = None,
    ) -> ProjectLabel:
        """Update project assignment; name/description/color update the canonical label."""
        pl = self.get(project_label_id)
        self.memberships.require_owner(pl.project_id, actor_user_id)
        self.memberships.require_active_project(pl.project_id)

        label_kwargs: dict = {}
        if name is not None:
            label_kwargs["name"] = name
        if description is not ...:
            label_kwargs["description"] = description
        if color is not ...:
            label_kwargs["color"] = color
        if label_kwargs:
            self.update_canonical(pl.label_id, actor_user_id=actor_user_id, **label_kwargs)

        if sort_order is not None:
            pl.sort_order = sort_order
            pl.save(update_fields=["sort_order"])
        pl.refresh_from_db()
        return pl

    def deactivate(self, project_label_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> ProjectLabel:
        pl = self.get(project_label_id)
        self.memberships.require_owner(pl.project_id, actor_user_id)
        self.memberships.require_active_project(pl.project_id)
        self.update_canonical(pl.label_id, actor_user_id=actor_user_id, is_active=False)
        pl.refresh_from_db()
        return pl

    def deactivate_canonical(self, label_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> Label:
        return self.update_canonical(label_id, actor_user_id=actor_user_id, is_active=False)

    def activate(self, project_label_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> ProjectLabel:
        pl = self.get(project_label_id)
        self.memberships.require_owner(pl.project_id, actor_user_id)
        self.memberships.require_active_project(pl.project_id)
        self.update_canonical(pl.label_id, actor_user_id=actor_user_id, is_active=True)
        pl.refresh_from_db()
        return pl

    def activate_canonical(self, label_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> Label:
        return self.update_canonical(label_id, actor_user_id=actor_user_id, is_active=True)

    def delete_canonical(self, label_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> None:
        label = self.get_canonical(label_id)
        if label.owner_id != actor_user_id:
            raise NotFoundError("Label not found", details={"label_id": str(label_id)})
        if label.project_labels.filter(annotations__removed_at__isnull=True).exists():
            raise ValidationError(
                "Label is in use and cannot be deleted",
                details={"label_id": str(label_id)},
            )
        label.delete()

    def find_by_name_ci(self, project_id: uuid.UUID, name: str) -> ProjectLabel | None:
        needle = name.strip().lower()
        for pl in self.list_for_project(project_id):
            if pl.display_name.strip().lower() == needle:
                return pl
        return None

    def is_in_use(self, label_id: uuid.UUID) -> bool:
        return Label.objects.filter(pk=label_id).filter(
            project_labels__annotations__removed_at__isnull=True,
        ).exists()
