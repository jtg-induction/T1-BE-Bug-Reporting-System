from django.contrib import admin
from tickets.models import Ticket,TicketSubscriber

class TicketAdmin(admin.ModelAdmin):
   
   list_display = ('title', 'description','assignee', 'status','reporter', 'isDeleted')
   search_fields=('title','status','assignee')

class TicketSubscriberAdmin(admin.ModelAdmin):
   
   list_display = ('user', 'ticket', 'status', 'isDeleted')
   search_fields=('role', 'status')


admin.site.register(Ticket, TicketAdmin)
admin.site.register(TicketSubscriber, TicketSubscriberAdmin)
