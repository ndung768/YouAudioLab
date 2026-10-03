from rest_framework.permissions import BasePermission


class IsIdentified(BasePermission):
    """Require X-User-Id principal (or session identity forwarded as principal)."""

    def has_permission(self, request, view) -> bool:
        return bool(getattr(request, "user", None)) and hasattr(request.user, "user_id")
