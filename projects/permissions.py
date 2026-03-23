from rest_framework import permissions

from projects.models import ProjectMember


class IsAdmin(permissions.BasePermission):
    """
    To define Admin-level permissions, so only admins can perform certain actions
    """

    message = "You are not an active admin of this project."

    def has_object_permission(self, request, view, obj):

        return ProjectMember.objects.filter(
            member=request.user,
            project=obj,
            status=ProjectMember.Status.ACTIVE,
            role=ProjectMember.Role.ADMIN,
        ).exists()
