from rest_framework import serializers

from projects.models import Project, ProjectMember
from users.serializers import UserSerializer


class ProjectSerializer(serializers.ModelSerializer):
    """
    Serializer for handling Project model instances.
    Provides project details and dynamically evaluates the requesting user's role within the project.
    """

    project_role = serializers.SerializerMethodField()

    class Meta:
        """
        Metadata options for ProjectSerializer.
        """

        model = Project
        fields = [
            "id",
            "title",
            "description",
            "status",
            "key",
            "jira_url",
            "jira_project_id",
            "project_role",
            "owner",
        ]
        read_only_fields = ["id", "jira_project_id", "project_role", "owner"]

    def get_project_role(self, obj):
        """
        Retrieves the specific project role of the currently authenticated user making the request.
        """
        request = self.context.get("request")
        if not request or not request.user:
            return None
        member = obj.project_members.filter(member=request.user).first()
        return member.role if member else None

    def validate(self, data):
        """
        Validates project data based on whether a project is being created or updated.
        Prevents modifications to 'jira_url' and 'key' on existing projects,
        and enforces the presence of required fields during initial creation.
        """
        if self.instance:
            unchangeable_fields = ["jira_url", "key"]

            for field in unchangeable_fields:
                if field in data:
                    raise serializers.ValidationError(
                        {field: "This field cannot be updated."}
                    )

        else:
            required_jira_fields = ["key", "title", "jira_url", "description"]
            for field in required_jira_fields:
                if not data.get(field):
                    raise serializers.ValidationError(
                        {field: "This field is required when creating a new project."}
                    )

        return data


class ProjectMemberSerializer(serializers.ModelSerializer):
    member = UserSerializer()

    class Meta:
        model = ProjectMember
        fields = ["id", "member", "role"]
        read_only_fields = ["member", "id"]
