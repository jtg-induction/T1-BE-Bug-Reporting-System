from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.models import EmailVerification

User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for handling new user registration.

    Validates email uniqueness, JiraID uniqueness, and ensures
    password confirmation matches.
    """

    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        """
        Metadata options for UserRegisterSerializer.
        """

        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "date_of_birth",
            "designation",
            "phone",
            "jiraID",
            "created_at",
            "updated_at",
            "password",
            "confirm_password",
            "jira_access_token",
        ]
        read_only_fields = ["id"]

    def validate_email(self, value):
        """
        Check if the provided email is already registered.
        """
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def validate_jiraID(self, value):
        """
        Check if the provided jiraID is already in use by another user.
        """
        if User.objects.filter(jiraID=value).exists():
            raise serializers.ValidationError("JiraID already in Use")
        return value

    def validate(self, value):
        """
        Perform cross-field validation to ensure passwords match.
        """
        if value["password"] != value["confirm_password"]:
            raise serializers.ValidationError("Both passwords dont match")
        return value

    def create(self, validated_data):
        """
        Create and return a new User instance using the validated data.
        """
        validated_data.pop("confirm_password")

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            phone=validated_data.get("phone"),
            date_of_birth=validated_data.get("date_of_birth"),
            designation=validated_data["designation"],
            jiraID=validated_data["jiraID"],
            jira_access_token=validated_data["jira_access_token"],
        )
        return user


class UserEmailVerifySerializer(serializers.ModelSerializer):
    """
    Serializer for creating EmailVerification instances.
    """

    class Meta:
        """
        Metadata options for UserEmailVerifySerializer.
        """

        model = EmailVerification
        fields = ["id", "email", "verification_token", "expires_at"]
        read_only_fields = ["id", "expires_at"]

    def validate_email(self, value):
        """
        Ensure the email is not already associated with an existing user.
        """
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def create(self, validated_data):
        """
        Create and return a new EmailVerification record.
        """
        verification = EmailVerification.objects.create(
            email=validated_data["email"],
        )
        return verification
