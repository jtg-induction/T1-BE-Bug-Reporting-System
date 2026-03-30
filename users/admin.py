from django.contrib import admin

from users.models import CustomUser


class UserAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "created_at",
        "last_login",
        "is_deleted",
    )
    search_fields = ("email",)


admin.site.register(CustomUser, UserAdmin)
