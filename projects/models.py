import uuid

from django.conf import settings
from django.db import models

from core.models import BaseModel


class Project(BaseModel):
    """
    Model representing a project workspace.
    Stores core project details, owner information, and Jira integration settings.
    """

    class Status(models.IntegerChoices):
        ARCHIVED = 0, ("Archived")
        ACTIVE = 1, ("Active")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)
    description = models.TextField(verbose_name="Description of project")
    status = models.IntegerField(choices=Status.choices, default=Status.ACTIVE)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ProjectMember", through_fields=("project", "member")
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="project_managed", on_delete=models.RESTRICT)
    archived_at = models.DateTimeField(null=True, blank=True)
    key = models.CharField(max_length=50)
    jira_url = models.URLField()
    jira_project_id = models.CharField()

    def __str__(self):
        """
        Returns the project title as its string representation.
        """
        return self.title


class ProjectMember(BaseModel):
    """
    Intermediary model managing the relationship between users and projects.
    Tracks user roles and their invitation or active status within a specific project.
    """

    class Role(models.IntegerChoices):
        DEV = 0, ("Developer")
        ADMIN = 1, ("Admin")

    class Status(models.IntegerChoices):
        INVITED = 0, ("Invited")
        ACTIVE = 1, ("Active")
        REVOKED = 2, ("Revoked")
        REJECTED = 3, ("Rejected")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, related_name="project_members", on_delete=models.CASCADE)
    member = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="user_projects", on_delete=models.CASCADE)
    inviter = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="invited_members", on_delete=models.SET_NULL, null=True
    )
    role = models.IntegerField(choices=Role.choices, default=Role.DEV)
    status = models.IntegerField(choices=Status.choices, default=Status.INVITED)

    class Meta:
        """
        Metadata options for ProjectMember.
        Enforces a unique constraint so a user can only have one membership record per project.
        """

        constraints = [
            models.UniqueConstraint(
                fields=["project", "member"],
                name="unique_project_member",
            )
        ]

    def __str__(self):
        """
        Returns a descriptive string combining the project title and the member's email.
        """
        member_email = self.member.email
        return f"{self.project.title} - {member_email}"
