from django.contrib import admin

from projects.models import Project, ProjectMember


class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "description", "status", "isDeleted")
    search_fields = ('title', 'key')
    list_filter = ('status', 'isDeleted')


class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ("project", "member", "role", "status", "isDeleted")
    search_fields = ('project__title', 'member__email')
    list_filter = ('role', 'status', 'isDeleted')


admin.site.register(Project, ProjectAdmin)
admin.site.register(ProjectMember, ProjectMemberAdmin)
