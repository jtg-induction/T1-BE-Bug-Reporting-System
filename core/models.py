from django.db import models
from django.conf import settings
import uuid
from core.constants import expiration_limit
from django.utils import timezone
from datetime import timedelta

class SafeDeleteQuerySet(models.QuerySet):
    
    def delete(self, using=None, keep_parents=False):
        self.update(isDeleted=True)
    
    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)
    
class SoftDeleteManager(models.Manager.from_queryset(SafeDeleteQuerySet)):
    
    def get_queryset(self):
        return super().get_queryset().filter(isDeleted=False)

class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
       settings.AUTH_USER_MODEL,
       null=True,
       blank=True,
       on_delete=models.SET_NULL,
       related_name="updated_%(class)s_set"
   )
    isDeleted = models.BooleanField(default=False)
    
    
    def delete(self, using=None, keep_parents=False):
        self.isDeleted = True
        self.save(update_fields=["isDeleted"], using=using)
         
    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

        
    objects = SoftDeleteManager()

    class Meta:
        abstract = True
        
class EmailVerification(BaseModel):
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.EmailField()
    verification_token = models.UUIDField(default=uuid.uuid4)
    expires_at = models.DateTimeField()
    
    class Meta:
      verbose_name = 'Email Verification'
      
    def save(self, *args, **kwargs):
        self.expires_at = timezone.now() + timedelta(seconds=expiration_limit)
        return super().save(*args, **kwargs)
