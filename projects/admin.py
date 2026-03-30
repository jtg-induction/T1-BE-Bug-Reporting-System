from django.contrib import admin

from projects.models import Project, ProjectMember


class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "description", "status", "is_deleted")
    search_fields = ("title", "key")
    list_filter = ("status", "is_deleted")


class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ("project", "member", "role", "status", "is_deleted")
    search_fields = ("project__title", "member__email")
    list_filter = ("role", "status", "is_deleted")


admin.site.register(Project, ProjectAdmin)
admin.site.register(ProjectMember, ProjectMemberAdmin)
