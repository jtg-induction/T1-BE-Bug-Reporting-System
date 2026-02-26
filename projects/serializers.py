from rest_framework import serializers
from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    project_role = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id", "title", "description", "status", "key", "jira_url", "jira_project_id", "project_role","owner"
        ]
        read_only_fields = ["id", "jira_project_id", "project_role","owner"]

    def get_project_role(self, obj):
        request = self.context.get('request')
        member = obj.project_members.filter(member=request.user).first()
        return member.role if member else None

    def validate(self, data):

        if self.instance:
            unchangeable_fields = ["jira_url", "key"]

            for field in unchangeable_fields:
                if field in data:
                    raise serializers.ValidationError({
                        field: "This field cannot be updated."
                    })

        else:
            required_jira_fields = ["key", "title", "jira_url","description"]
            for field in required_jira_fields:
                if not data.get(field):
                    raise serializers.ValidationError({
                        field: "This field is required when creating a new project."
                    })

        return data
