"""Project membership resolution and role checks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apps.core.errors import ForbiddenError, NotFoundError, ProjectArchivedError, ValidationError
from apps.workspace.models import AppUser, Project, ProjectMembership


class MembershipService:
    def resolve_user_ref(self, user_ref: str) -> AppUser:
        """Resolve an existing user by UUID or login_identifier (case-insensitive)."""
        raw = (user_ref or "").strip()
        if not raw:
            raise ValidationError(
                "User reference is required",
                details={"fields": [{"field": "user_ref", "code": "REQUIRED"}]},
            )
        try:
            uid = uuid.UUID(raw)
        except ValueError:
            uid = None
        if uid is not None:
            user = AppUser.objects.filter(pk=uid).first()
            if user is not None:
                return user
        user = AppUser.objects.filter(login_identifier__iexact=raw).first()
        if user is not None:
            return user
        raise NotFoundError(
            "User not found",
            details={"user_ref": raw},
        )

    def get_active_membership(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProjectMembership | None:
        return ProjectMembership.objects.filter(
            project_id=project_id,
            user_id=user_id,
            revoked_at__isnull=True,
        ).first()

    def require_member(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProjectMembership:
        membership = self.get_active_membership(project_id, user_id)
        if membership is None:
            raise ForbiddenError(
                "Not a member of this project",
                details={"project_id": str(project_id)},
            )
        return membership

    def require_owner(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ProjectMembership:
        membership = self.require_member(project_id, user_id)
        if membership.role != ProjectMembership.Role.OWNER:
            raise ForbiddenError(
                "OWNER role required",
                details={"project_id": str(project_id), "role": membership.role},
            )
        return membership

    def require_active_project(self, project_id: uuid.UUID) -> Project:
        try:
            project = Project.objects.get(pk=project_id)
        except Project.DoesNotExist as exc:
            raise NotFoundError(
                "Project not found",
                details={"project_id": str(project_id)},
            ) from exc
        if project.status == Project.Status.ARCHIVED:
            raise ProjectArchivedError(
                "Project is archived",
                details={"project_id": str(project_id)},
            )
        return project

    def add_member(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
        actor_user_id: uuid.UUID,
    ) -> ProjectMembership:
        self.require_owner(project_id, actor_user_id)
        self.require_active_project(project_id)

        if role not in {ProjectMembership.Role.OWNER, ProjectMembership.Role.ANNOTATOR}:
            raise ValidationError(
                "Invalid membership role",
                details={"fields": [{"field": "role", "code": "INVALID_ROLE"}]},
            )
        if not AppUser.objects.filter(pk=user_id).exists():
            raise NotFoundError(
                "User not found",
                details={"user_id": str(user_id)},
            )

        existing = ProjectMembership.objects.filter(
            project_id=project_id,
            user_id=user_id,
        ).first()
        if existing is not None:
            existing.role = role
            existing.revoked_at = None
            existing.save(update_fields=["role", "revoked_at"])
            return existing

        return ProjectMembership.objects.create(
            project_id=project_id,
            user_id=user_id,
            role=role,
        )

    def revoke_member(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> ProjectMembership:
        self.require_owner(project_id, actor_user_id)
        membership = ProjectMembership.objects.filter(
            project_id=project_id,
            user_id=user_id,
        ).first()
        if membership is None:
            raise NotFoundError(
                "Membership not found",
                details={"project_id": str(project_id), "user_id": str(user_id)},
            )
        if membership.revoked_at is None:
            membership.revoked_at = datetime.now(timezone.utc)
            membership.save(update_fields=["revoked_at"])
            from apps.workspace.services.assignment import AssignmentService

            AssignmentService().release_for_user_in_project(
                project_id=project_id,
                user_id=user_id,
            )
        return membership

    def list_active(self, project_id: uuid.UUID) -> list[ProjectMembership]:
        return list(
            ProjectMembership.objects.filter(
                project_id=project_id,
                revoked_at__isnull=True,
            )
            .select_related("user")
            .order_by("created_at")
        )
