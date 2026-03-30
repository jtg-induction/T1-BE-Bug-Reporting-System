from django.contrib import admin

from tickets.models import Ticket, TicketSubscriber


class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "description",
        "assignee",
        "status",
        "reporter",
        "is_deleted",
    )
    search_fields = ("title", "status", "assignee__email", "reporter__email")


class TicketSubscriberAdmin(admin.ModelAdmin):
    list_display = ("user", "ticket", "status", "is_deleted")
    search_fields = ("user__email", "ticket__title", "status")


admin.site.register(Ticket, TicketAdmin)
admin.site.register(TicketSubscriber, TicketSubscriberAdmin)
