from django.db import models
from core.models import BaseModel
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import MinLengthValidator
from core.models import SoftDeleteManager
import uuid
from encrypted_model_fields.fields import EncryptedCharField


class UserManager(SoftDeleteManager, BaseUserManager):

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class CustomUser(BaseModel, AbstractBaseUser, PermissionsMixin):

    class Designation(models.TextChoices):
        INTERN = 'INTERN', 'Intern'
        SD = 'SD', 'Software Developer'
        SSD = 'SSD', 'Senior Software Developer'
        TL = 'TL', 'Team Lead'
        M = 'M', 'Manager'

    id = models.UUIDField(primary_key=True,
                          default=uuid.uuid4,
                          editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    date_of_birth = models.DateField(null=True)
    phone = models.CharField(max_length=10, null=True, validators=[MinLengthValidator(10)])
    designation = models.CharField(max_length=6, choices=Designation.choices)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    jiraID = models.CharField(max_length=128, unique=True)
    jira_access_token = EncryptedCharField(max_length=256, unique=True)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "designation", "jiraID", "jira_access_token"]

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
