from django.contrib import admin
from projects.models import Project, ProjectMember 

class ProjectAdmin(admin.ModelAdmin):
   
   list_display = ('title', 'key', 'description', 'status', 'isDeleted')
   search_fields=('title', 'key', 'status')

class ProjectMemberAdmin(admin.ModelAdmin):
   
   list_display = ('project', 'member', 'role', 'status', 'isDeleted')
   search_fields=('role', 'status')


admin.site.register(Project, ProjectAdmin)
admin.site.register(ProjectMember, ProjectMemberAdmin)