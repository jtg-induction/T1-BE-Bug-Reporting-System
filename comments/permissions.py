from rest_framework import permissions
from rest_framework.exceptions import NotFound

from projects.models import Project, ProjectMember
from tickets.models import Ticket


class IsActiveProjectMember(permissions.BasePermission):
    """
    Ensures the user is an active member of the project specified in the URL.
    Also validates that the ticket actually belongs to that project.
    """

    message = "You do not have access to this project's tickets."

    def has_permission(self, request, view):
        project_id = view.kwargs.get("project_id")
        ticket_id = view.kwargs.get("ticket_id")

        if not project_id:
            return True

        if ticket_id:
            if not Ticket.objects.filter(id=ticket_id, project_id=project_id).exists():
                raise NotFound(
                    detail="This ticket does not exist in the specified project."
                )

        return ProjectMember.objects.filter(
            member=request.user,
            project_id=project_id,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

    def has_object_permission(self, request, view, obj):
        return ProjectMember.objects.filter(
            member=request.user,
            project=obj.ticket.project,
            status=ProjectMember.Status.ACTIVE,
        ).exists()


class IsCommentAuthorOrReadOnly(permissions.BasePermission):
    """
    Allows read-only access to any active member, but restricts
    modifications (update/delete) strictly to the comment's author.
    """

    message = "You do not have permission to modify this comment. Only the author can do this."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.author == request.user


class IsProjectActive(permissions.BasePermission):
    """
    Allows write operations only if the project is active.
    Read-only operations (GET, HEAD, OPTIONS) are allowed regardless of project status.
    """

    message = "Cannot modify resources in an inactive project."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        project_id = view.kwargs.get("project_id")
        if not project_id:
            return True

        return Project.objects.filter(
            id=project_id, status=Project.Status.ACTIVE
        ).exists()
