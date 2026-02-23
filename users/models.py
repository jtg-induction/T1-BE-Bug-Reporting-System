from django.db import models
from core.models import BaseModel
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import MinLengthValidator
from django.db import models
import uuid

class UserManager(BaseUserManager):

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
      return self.create_user(email, password, **extra_fields)

class CustomUser(BaseModel, AbstractBaseUser, PermissionsMixin):
   
   class Designation(models.TextChoices):
       INTERN = 'INTERN', 'Intern'
       SD = 'SD', 'Software Developer'
       SSD = 'SSD', 'Senior Software Developer'
       TL = 'TL','Team Lead'
       M = 'M','Manager'

   id = models.UUIDField(primary_key=True,
        default=uuid.uuid4,
        editable=False)
   email = models.EmailField(unique=True)
   first_name = models.CharField(max_length=30)
   last_name = models.CharField(max_length=30)
   date_of_birth = models.DateField(null=True, blank=True)
   phone=models.CharField(max_length=10, null=True, blank=True, validators=[MinLengthValidator(10)])
   designation = models.CharField(choices=Designation.choices)
   is_staff = models.BooleanField(default=False)
   is_active = models.BooleanField(default=True)
   jiraID=models.CharField(max_length=128, unique=True)


   objects = UserManager()
   USERNAME_FIELD = "email"
   REQUIRED_FIELDS = ["first_name", "last_name", "designation"]


   def __str__(self):
       return self.email
   
   class Meta:
      verbose_name = 'User'
      verbose_name_plural = 'Users'
