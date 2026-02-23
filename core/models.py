from django.db import models
import uuid

class SafeDeleteQuerySet(models.QuerySet):
    
    def delete(self):
        return self.update(isDeleted=True)
    
    
class SoftDeleteManager(models.Manager):
    
    def get_queryset(self):
        return SafeDeleteQuerySet(self.model, using=self._db)

class BaseModel(models.Model):
    
    def delete(self):
        self.isDeleted = True
        self.save()
        
    objects = SoftDeleteManager()

    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    isDeleted = models.BooleanField(default=False)

    class Meta:
        abstract = True
        
class EmailVerification(BaseModel):
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    email = models.EmailField()
    verification_token = models.UUIDField(default=uuid.uuid4)
    
    class Meta:
      verbose_name = 'Email Verification'
    