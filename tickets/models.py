import uuid

from django.conf import settings
from django.db import models

from core.models import BaseModel
from projects.models import Project


class Ticket(BaseModel):
    class Status(models.IntegerChoices):
        OPEN = 1, ("Open")
        IN_PROGRESS = 2, ("In Progress")
        RESOLVED = 3, ("Resolved")
        CLOSED = 4, ("Closed")

    class Severity(models.IntegerChoices):
        LOW = 1, ("Low")
        MID = 2, ("Medium")
        HIGH = 3, ("High")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)
    description = models.TextField()
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
        null=True,
        blank=True,
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reported_tickets",
    )
    status_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ticket_updates",
    )
    status = models.IntegerField(choices=Status.choices, default=Status.OPEN)
    prev_status = models.IntegerField(choices=Status.choices, null=True, blank=True)
    severity = models.IntegerField(choices=Severity.choices, default=Severity.LOW)
    deadline = models.DateTimeField(null=True, blank=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    jira_id = models.CharField(max_length=100, null=True, blank=True)
    reminder_task_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.title


class TicketSubscriber(BaseModel):
    class Status(models.IntegerChoices):
        UNSUBSCRIBED = 1, "Unsubscribed"
        SUBSCRIBED = 2, "Subscribed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_subscriptions",
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="subscribers"
    )
    status = models.IntegerField(choices=Status.choices, default=Status.SUBSCRIBED)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "ticket"], name="unique_ticket_subscription"
            )
        ]
        verbose_name = "Ticket Subscriber"

    def __str__(self):
        return f"{self.user.email} : {self.ticket.title} ({self.get_status_display()})"
