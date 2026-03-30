from urllib.parse import unquote

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from core.models import EmailVerification

User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "date_of_birth",
            "designation",
            "phone",
            "jira_id",
            "created_at",
            "updated_at",
            "password",
            "confirm_password",
            "token",
            "jira_access_token",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs.get("password") != attrs.get("confirm_password"):
            raise serializers.ValidationError(
                {"password": "Both passwords don't match."}
            )
        raw_token = attrs.get("token")
        raw_email = attrs.get("email")

        verify_token = unquote(raw_token)
        email = unquote(raw_email)

        email_verified = EmailVerification.objects.filter(
            verification_token=verify_token, email=email, expires_at__gte=timezone.now()
        ).first()

        if not email_verified:
            raise serializers.ValidationError(
                {"token": "Invalid Token or Token Expired"}
            )

        attrs["email"] = email

        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password", None)
        validated_data.pop("token", None)

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            phone=validated_data.get("phone"),
            date_of_birth=validated_data.get("date_of_birth"),
            designation=validated_data["designation"],
            jira_id=validated_data["jira_id"],
            jira_access_token=validated_data.get("jira_access_token"),
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
