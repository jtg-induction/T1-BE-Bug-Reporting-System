from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for handling User model instances.
    Provides basic user details and a dynamic flag indicating if the request user can edit this profile.
    """

    can_edit = serializers.SerializerMethodField()

    class Meta:
        """
        Metadata options for UserSerializer.
        """

        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "designation",
            "can_edit",
        ]
        read_only_fields = ["email"]

    def validate(self, data):
        """
        Perform cross-field validation and enforce strict read-only constraints.

        Explicitly checks initial_data to ensure that read_only_fields
        are not included in the update request.
        """
        if self.instance:
            errors = {}
            for field_name in self.Meta.read_only_fields:
                if field_name in self.initial_data:
                    errors[field_name] = "This field cannot be updated."
            if errors:
                raise serializers.ValidationError(errors)

        return data

    def get_can_edit(self, obj):
        """
        Evaluates whether the currently authenticated user making the request
        has permission to edit this specific user instance.
        """
        request = self.context.get("request")
        if request:
            return obj.id == request.user.id

        return False


class CurrentUserSerializer(UserSerializer):
    """
    Serializer for the current logged-in user.
    Includes Jira credentials and tokens.
    """

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ["jiraID", "jira_access_token"]
        extra_kwargs = {"jira_access_token": {"write_only": True}}
