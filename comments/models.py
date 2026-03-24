import uuid

from django.conf import settings
from django.db import models

from core.models import BaseModel
from tickets.models import Ticket


class Comment(BaseModel):
    """
    Model representing a comment on a ticket.
    Inherits from BaseModel for auditing and soft-delete functionality.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    description = models.TextField()
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ticket_comments",
        null=True,
        blank=True,
    )

    author_name = models.CharField(max_length=100, blank=True)

    jira_id = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        author = self.author_name or "Unknown"
        return f"Comment by {author} on Ticket {self.ticket.title}"
