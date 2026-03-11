from django.db import models
from django.conf import settings
from core.models import BaseModel
import uuid


class Project(BaseModel):

    class Status(models.IntegerChoices):
        ARCHIVED = 0, ("Archived")
        ACTIVE = 1, ("Active")

    id = models.UUIDField(primary_key=True,
                          default=uuid.uuid4,
                          editable=False)
    title = models.CharField(max_length=100)
    description = models.TextField(verbose_name="Description of project")
    status = models.IntegerField(choices=Status.choices, default=Status.ACTIVE)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                     through="ProjectMember",
                                     through_fields=(
                                         "project",
                                         "member"))
    owner=models.ForeignKey(settings.AUTH_USER_MODEL, related_name="project_managed", on_delete=models.RESTRICT)
    archived_at = models.DateTimeField(null=True, blank=True)
    key = models.CharField(max_length=50)
    jira_url = models.URLField()
    jira_project_id = models.CharField()

    def __str__(self):
        return self.title


class ProjectMember(BaseModel):

    class Role(models.IntegerChoices):
        DEV = 0, ('Developer')
        ADMIN = 1, ('Admin')

    class Status(models.IntegerChoices):
        INVITED = 0, ('Invited')
        ACTIVE = 1, ('Active')
        REVOKED = 2, ('Revoked')
        REJECTED = 3, ('Rejected')

    id = models.UUIDField(primary_key=True,
                          default=uuid.uuid4,
                          editable=False)
    project = models.ForeignKey(Project, related_name="project_members", on_delete=models.CASCADE)
    member = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="user_projects", on_delete=models.CASCADE)
    inviter = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="invited_members", on_delete=models.SET_NULL,null=True)
    role = models.IntegerField(choices=Role.choices, default=Role.DEV)
    status = models.IntegerField(choices=Status.choices, default=Status.INVITED)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "member"],
                name="unique_project_member",
            )
        ]

    def __str__(self):
        member_email = self.member.email
        return f"{self.project.title} - {member_email}"
