from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied

from projects.models import Project, ProjectMember
from tickets.models import Ticket


class IsActiveMemberAndProjectActive(permissions.BasePermission):
    """
    Ensures the user is an active member of the project and the ticket belongs to the project.
    For write operations, also ensures the project itself is active.
    """

    def has_permission(self, request, view):
        project_id = view.kwargs.get("project_pk")
        ticket_id = view.kwargs.get("ticket_pk")

        if not project_id or not ticket_id:
            return False

        if not Ticket.objects.filter(id=ticket_id, project_id=project_id).exists():
            raise NotFound(
                detail="This ticket does not exist in the specified project."
            )

        member_record = (
            ProjectMember.objects.filter(
                member=request.user,
                project_id=project_id,
                status=ProjectMember.Status.ACTIVE,
            )
            .select_related("project")
            .first()
        )

        if not member_record:
            raise PermissionDenied("You do not have access to this project's tickets.")

        if request.method not in permissions.SAFE_METHODS:
            if member_record.project.status != Project.Status.ACTIVE:
                raise PermissionDenied(
                    "Cannot modify resources in an inactive project."
                )

        return True


class IsWriteAccessOrReadOnly(permissions.BasePermission):
    """
    Allows read-only access to any active member, but restricts
    modifications (update/delete) strictly to the comment's author.
    """

    message = "You do not have permission to modify this comment. Only the author can do this."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.author == request.user
