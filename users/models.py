import uuid

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager, PermissionsMixin
from django.core.validators import MinLengthValidator
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField

from core.models import BaseModel, SoftDeleteManager


class UserManager(SoftDeleteManager, BaseUserManager):
    """
    Custom manager for CustomUser model where email is the unique identifier
    for authentication instead of usernames.
    """

    def create_user(self, email, password=None, **extra_fields):
        """
        Create and save a User with the given email and password.
        """
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create and save a SuperUser with the given email and password.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class CustomUser(BaseModel, AbstractBaseUser, PermissionsMixin):
    """
    Custom User model representing a system user with Jira integration
    and role-based designations.

    Inherits from BaseModel to support soft-delete and auditing.
    """

    class Designation(models.TextChoices):
        """Enumeration for user job roles within the organization."""

        INTERN = "INTERN", "Intern"
        SD = "SD", "Software Developer"
        SSD = "SSD", "Senior Software Developer"
        TL = "TL", "Team Lead"
        M = "M", "Manager"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    date_of_birth = models.DateField(null=True)
    phone = models.CharField(
        max_length=10, null=True, validators=[MinLengthValidator(10)]
    )
    designation = models.CharField(max_length=6, choices=Designation.choices)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    jiraID = models.CharField(max_length=128, unique=True)
    jira_access_token = EncryptedCharField(max_length=256, unique=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = [
        "first_name",
        "last_name",
        "designation",
        "jiraID",
        "jira_access_token",
    ]

    def __str__(self):
        """Return the string representation of the user (email)."""
        return self.email

    class Meta:
        """Metadata options for the CustomUser model."""

        verbose_name = "User"
        verbose_name_plural = "Users"
