from django.contrib import admin

from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "author_name", "created_at", "isDeleted")

    list_filter = ("isDeleted", "created_at")

    search_fields = ("description", "author_name", "ticket__title", "jira_id")

    readonly_fields = ("id", "created_at", "updated_at", "jira_id")
