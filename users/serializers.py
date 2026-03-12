from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
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
        user = self.context["user"]
        if obj.id == user.id:
            return True
        return False
