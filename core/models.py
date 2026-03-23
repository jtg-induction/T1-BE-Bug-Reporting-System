import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.constants import invite_expiration_limit


class SafeDeleteQuerySet(models.QuerySet):
    """
    QuerySet that overrides the default delete behavior to perform a soft delete.
    """

    def delete(self, using=None, keep_parents=False):
        """
        Bulk soft-delete that also triggers bulk soft-delete on related models.
        """
        for relation in self.model._meta.related_objects:
            if relation.on_delete == models.CASCADE:
                if hasattr(relation.related_model, "isDeleted"):
                    related_queryset = relation.related_model.objects.filter(
                        **{f"{relation.remote_field.name}__in": self}
                    )
                    related_queryset.delete()

        return self.update(isDeleted=True, updated_at=timezone.now())

    def hard_delete(self, using=None, keep_parents=False):
        """
        Permanently removes records from the database.
        """
        return super().delete(using=using, keep_parents=keep_parents)


class SoftDeleteManager(models.Manager.from_queryset(SafeDeleteQuerySet)):
    """
    Manager that automatically filters out records marked as deleted.
    """

    def get_queryset(self):
        """
        Returns a queryset of objects where isDeleted is False.
        """
        return super().get_queryset().filter(isDeleted=False)


class BaseModel(models.Model):
    """
    An abstract base model that provides auditing fields and soft-delete logic.

    Attributes:
        created_at (DateTimeField): Timestamp of record creation.
        updated_at (DateTimeField): Timestamp of last update.
        updated_by (ForeignKey): Reference to the user who last modified the record.
        isDeleted (BooleanField): Flag to indicate if the record is soft-deleted.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_%(class)s_set",
    )
    isDeleted = models.BooleanField(default=False)

    def delete(self, using=None, keep_parents=False):
        """
        Marks the instance as deleted without removing it from the DB.
        """
        self.isDeleted = True
        self.save(update_fields=["isDeleted", "updated_at"], using=using)
        for related_object in self._meta.related_objects:
            if related_object.on_delete == models.CASCADE and issubclass(
                related_object.related_model, BaseModel
            ):
                related_queryset = getattr(
                    self, related_object.get_accessor_name()
                ).all()
                related_queryset.delete()

    def hard_delete(self, using=None, keep_parents=False):
        """
        Permanently removes the instance from the database.
        """
        return super().delete(using=using, keep_parents=keep_parents)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        """
        Metadata options for the BaseModel.
        """

        abstract = True


class EmailVerification(BaseModel):
    """
    Stores email verification tokens and their expiration logic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    verification_token = models.UUIDField(default=uuid.uuid4, editable=False)
    expires_at = models.DateTimeField()

    class Meta:
        """
        Metadata options for the EmailVerification model.
        """

        verbose_name = "Email Verification"

    def save(self, *args, **kwargs):
        """
        Overrides save to automatically set the expiration timestamp.
        """
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(
                seconds=invite_expiration_limit
            )
        return super().save(*args, **kwargs)
