from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for viewing and updating user profile information.

    Restricts updates to sensitive identity fields like email and jiraID
    while allowing modifications to personal details.
    """

    is_owner = serializers.SerializerMethodField()

    class Meta:
        """
        Metadata options for UserSerializer.
        """

        model = User
        fields = [
            "first_name",
            "last_name",
            "email",
            "designation",
            "phone",
            "jiraID",
            "date_of_birth",
            "is_owner",
        ]
        read_only_fields = ["email", "jiraID"]

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

    def get_is_owner(self, obj):
        print(self.context)
        if obj.id == self.context["user_id"]:
            return True
        return False
