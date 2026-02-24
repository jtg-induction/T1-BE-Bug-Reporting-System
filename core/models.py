from django.db import models
from django.conf import settings
import uuid

class SafeDeleteQuerySet(models.QuerySet):
    
    def delete(self):
        return self.update(isDeleted=True)
    
    def hard_delete(self):
        return super().delete()
    
class SoftDeleteManager(models.Manager.from_queryset(SafeDeleteQuerySet)):
    
    def get_queryset(self):
        return super().get_queryset()

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
    
    def delete(self):
        self.isDeleted = True
        self.save(update_fields=["isDeleted"])
        
    def hard_delete(self):
        super().delete()
        
    objects = SoftDeleteManager()

    class Meta:
        abstract = True
        
class EmailVerification(BaseModel):
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.EmailField()
    verification_token = models.UUIDField(default=uuid.uuid4)
    
    class Meta:
      verbose_name = 'Email Verification'
    