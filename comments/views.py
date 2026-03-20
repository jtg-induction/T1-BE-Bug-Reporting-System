from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from comments.models import Comment
from comments.serializers import CommentSerializer
from core.utils import JiraClient, JiraClientException
from projects.models import Project, ProjectMember
from tickets.models import Ticket


class CommentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing comments on a specific ticket.
    """

    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Retrieves comments strictly for the ticket specified in the URL.
        """
        ticket_id = self.kwargs.get("ticket_id")
        project_id = self.kwargs.get("project_id")
        return Comment.objects.filter(
            ticket_id=ticket_id,
            ticket__project_id=project_id,
        ).select_related("author")

    def _check_project_access(self, ticket, user):
        """
        Internal helper to ensure the user is an active member of the ticket's project.
        """
        is_member = ProjectMember.objects.filter(
            project=ticket.project, member=user, status=ProjectMember.Status.ACTIVE
        ).exists()

        if not is_member:
            raise PermissionDenied("You do not have access to this project's tickets.")

    def create(self, request, *args, **kwargs):
        """
        Creates a local comment and syncs it to the associated Jira issue.
        """
        ticket_id = self.kwargs.get("ticket_id")
        project_id = self.kwargs.get("project_id")
        ticket = get_object_or_404(
            Ticket.objects.select_related("project"),
            id=ticket_id,
            project_id=project_id,
        )
        user = request.user
        project = ticket.project

        if project.status != Project.Status.ACTIVE:
            raise ValidationError(
                {"project": "Cannot add comments to an inactive project."}
            )

        self._check_project_access(ticket, user)
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                display_name = (
                    f"{user.first_name} {user.last_name}".strip() or user.email
                )
                comment = serializer.save(
                    ticket=ticket, author=user, author_name=display_name
                )

                if project.jira_url and user.jira_access_token and ticket.jira_key:
                    jira_client = JiraClient(
                        project.jira_url, user.email, user.jira_access_token
                    )

                    jira_response = jira_client.add_comment(
                        jira_issue_key=ticket.jira_key, text=comment.description
                    )

                    comment.jira_id = jira_response.get("id")
                    comment.save(update_fields=["jira_id"])

            response_serializer = self.get_serializer(
                comment, context={"request": request}
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except JiraClientException as e:
            return Response(
                {
                    "error": f"Failed to sync comment with Jira: {str(e)}",
                    "jira_details": e.response_data,
                },
                status=e.status_code
                if e.status_code
                else status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            return Response(
                {"error": "An internal error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, *args, **kwargs):
        """
        Updates an existing comment locally and syncs the edit to Jira.
        """
        comment = self.get_object()
        ticket = comment.ticket
        project = ticket.project
        user = request.user

        if project.status != Project.Status.ACTIVE:
            raise ValidationError(
                {"project": "Cannot edit comments in an inactive project."}
            )
        self._check_project_access(ticket, user)

        if comment.author != user:
            raise PermissionDenied("You can only edit your own comments.")

        serializer = self.get_serializer(
            comment, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                updated_comment = serializer.save(updated_by=user)

                if (
                    project.jira_url
                    and user.jira_access_token
                    and ticket.jira_key
                    and updated_comment.jira_id
                ):
                    jira_client = JiraClient(
                        project.jira_url, user.email, user.jira_access_token
                    )

                    jira_client.update_comment(
                        jira_issue_key=ticket.jira_key,
                        jira_comment_id=updated_comment.jira_id,
                        text=updated_comment.description,
                    )

            response_serializer = self.get_serializer(
                updated_comment, context={"request": request}
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except JiraClientException as e:
            return Response(
                {
                    "error": f"Failed to update comment in Jira: {str(e)}",
                    "jira_details": e.response_data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": "An internal error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def destroy(self, request, *args, **kwargs):
        """
        Soft-deletes the comment locally and permanently deletes it from Jira.
        Strictly limits deletion rights to the original author of the comment.
        """
        comment = self.get_object()
        ticket = comment.ticket
        project = ticket.project
        user = request.user

        if project.status != Project.Status.ACTIVE:
            raise ValidationError(
                {"project": "Cannot delete comments in an inactive project."}
            )

        self._check_project_access(ticket, user)

        if comment.author != user:
            raise PermissionDenied(
                "You do not have permission to delete this comment. Only the author can delete it."
            )

        try:
            with transaction.atomic():
                comment.delete()

                if (
                    project.jira_url
                    and user.jira_access_token
                    and ticket.jira_key
                    and comment.jira_id
                ):
                    jira_client = JiraClient(
                        project.jira_url, user.email, user.jira_access_token
                    )

                    jira_client.delete_comment(
                        jira_issue_key=ticket.jira_key, jira_comment_id=comment.jira_id
                    )

            return Response(status=status.HTTP_204_NO_CONTENT)

        except JiraClientException as e:
            return Response(
                {
                    "error": f"Failed to delete comment from Jira: {str(e)}",
                    "jira_details": e.response_data,
                },
                status=e.status_code if e.status_code else status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": "An internal error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
