from rest_framework import serializers

from projects.models import Project, ProjectMember
from tickets.models import Ticket, TicketSubscriber


class TicketListSerializer(serializers.ModelSerializer):
    """
    Serializer for handling list views of Ticket model instances.
    Transforms relational fields into readable formats and dynamically evaluates
    the requesting user's subscription status.
    """
    assignee_id = serializers.SerializerMethodField()
    assignee_email = serializers.SerializerMethodField()
    assignee_name = serializers.SerializerMethodField()
    reporter_email = serializers.EmailField(source="reporter.email", read_only=True)
    reporter_name = serializers.SerializerMethodField()
    project = serializers.CharField(source="project.key", read_only=True)
    project_id = serializers.UUIDField(source="project.id", read_only=True)
    is_subscribed = serializers.SerializerMethodField()

    class Meta:
        """
        Metadata options for TicketListSerializer.
        """

        model = Ticket
        fields = [
            "id",
            "title",
            "assignee_id",
            "assignee_name",
            "assignee_email",
            "reporter_name",
            "reporter_email",
            "project",
            "status",
            "severity",
            "deadline",
            "project_id",
            "jira_key",
            "is_subscribed",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_subscribed(self, obj):
        """
        Retrieves the subscription status of the currently authenticated user making the request.
        """
        request = self.context.get("request")
        if not request:
            return False

        return TicketSubscriber.objects.filter(
            ticket=obj, user=request.user, status=TicketSubscriber.Status.SUBSCRIBED
        ).exists()
    
    def get_assignee_id(self, obj):
        """Returns the assignee's ID if assignee exists."""
        return obj.assignee.id if obj.assignee else None

    def get_assignee_email(self, obj):
        """Returns the assignee's email if assignee exists."""
        return obj.assignee.email if obj.assignee else None
    
    def get_assignee_name(self, obj):
        """Returns the assignee's full name if assignee exists."""
        return f"{obj.assignee.first_name} {obj.assignee.last_name}" if obj.assignee else None
    
    def get_reporter_name(self, obj):
        """Returns the reporter's full name"""
        return f"{obj.reporter.first_name} {obj.reporter.last_name}"


class TicketReadSerializer(TicketListSerializer):
    """
    Serializer for retrieving detailed information about a single Ticket instance.
    Inherits from TicketListSerializer and expands upon it by including the description,
    project active status, and calculating the user's specific permission tier.
    """

    permission_class = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        """
        Metadata options for TicketReadSerializer.
        """

        fields = TicketListSerializer.Meta.fields + [
            "description",
            "permission_class",
            "is_active",
        ]
        read_only_fields = fields

    def get_permission_class(self, obj):
        """
        Calculates an integer-based permission tier for the requesting user based on their relationship
        to the ticket and project. Used by the frontend for conditional UI rendering.

        Hierarchy: 4 (Reporter) > 3 (Admin) > 2 (Assignee) > 1 (Normal Dev)
        """
        request = self.context.get("request")
        if not request:
            return 1

        user = request.user

        if obj.reporter == user:
            return 4

        is_admin = ProjectMember.objects.filter(
            project=obj.project,
            member=user,
            role=ProjectMember.Role.ADMIN,
            status=ProjectMember.Status.ACTIVE,
        ).exists()

        if is_admin:
            return 3

        if obj.assignee == user:
            return 2

        return 1

    def get_is_active(self, obj):
        """
        Evaluates whether the ticket's parent project is currently active.
        """
        return obj.project.status == Project.Status.ACTIVE


class TicketWriteSerializer(serializers.ModelSerializer):
    """
    Serializer strictly for creating and updating Ticket model instances.
    Exposes only the core fields permissible to be modified via POST, PUT, or PATCH requests.
    """

    class Meta:
        """
        Metadata options for TicketWriteSerializer.
        """

        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "assignee",
            "status",
            "severity",
            "deadline",
        ]
