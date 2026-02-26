from rest_framework import serializers
from django.contrib.auth import get_user_model
from core.models import EmailVerification

User = get_user_model()


class UserRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta():
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
            "jira_access_token"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def validate_jiraID(self, value):
        if User.objects.filter(jiraID=value).exists():
            raise serializers.ValidationError("JiraID already in Use")
        return value

    def validate(self, value):
        if value["password"] != value["confirm_password"]:
            raise serializers.ValidationError("Both passwords dont match")
        return value

    def create(self, validated_data):
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
            jira_access_token=validated_data["jira_access_token"]
        )
        return user


class UserEmailVerifySerializer(serializers.ModelSerializer):

    class Meta():
        model = EmailVerification
        fields = ["id", "email", "verification_token", "expires_at"]
        read_only_fields = ["id", "expires_at"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value

    def create(self, validated_data):

        verification = EmailVerification.objects.create(
            email=validated_data["email"],
        )
        return verification
