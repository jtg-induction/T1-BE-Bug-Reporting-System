from rest_framework import permissions

from projects.models import Project, ProjectMember
from tickets.models import Ticket


class IsProjectActive(permissions.BasePermission):
    """
    Blocks write actions if the project is archived
    """

    message = "Cannot modify resources in an archived project."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        project_id = view.kwargs.get("project_id")
        if not project_id:
            return True

        return Project.objects.filter(
            id=project_id, status=Project.Status.ACTIVE
        ).exists()


class IsActiveProjectMember(permissions.BasePermission):
    """
    Ensures the user is an active member of the project.
    """

    message = "You do not have permission to view  this project's tickets."

    def has_permission(self, request, view):
        project_id = view.kwargs.get("project_id")
        if not project_id:
            return True

        return ProjectMember.objects.filter(
            project_id=project_id,
            member=request.user,
            status=ProjectMember.Status.ACTIVE,
        ).exists()


class IsProjectAdmin(permissions.BasePermission):
    """
    Ensures the user has the ADMIN role in the project.
    """

    message = "Admin role required."

    def has_permission(self, request, view):
        project_id = view.kwargs.get("project_id")
        if not project_id:
            return True

        return ProjectMember.objects.filter(
            project_id=project_id,
            member=request.user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()


class CanUpdateTicketRestrictions(permissions.BasePermission):
    """
    Handles the complex field-level permissions for updating a ticket:
    - Admins and Reporters can update general fields.
    - Assignees can ONLY update the 'status' field.
    - ONLY the Reporter can change the status to CLOSED.
    """

    message = "You do not have permission to edit this ticket."

    def has_object_permission(self, request, view, obj):
        if request.method not in ["PUT", "PATCH"]:
            return True

        user = request.user
        is_reporter = obj.reporter == user
        is_assignee = obj.assignee == user
        is_admin = ProjectMember.objects.filter(
            project=obj.project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        if not (is_admin or is_reporter or is_assignee):
            return False

        data = request.data
        new_status = data.get("status")

        if new_status and int(new_status) == Ticket.Status.CLOSED:
            if not is_reporter:
                self.message = "Only the reporter can mark a ticket as Closed."
                return False

        if is_assignee and not (is_admin or is_reporter):
            allowed_fields = {"status"}
            request_keys = set(data.keys())
            if not request_keys.issubset(allowed_fields):
                self.message = (
                    "Assignees can only update the status. Cannot edit other fields."
                )
                return False

        return True
