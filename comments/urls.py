from django.urls import path, include

from comments.views import CommentViewSet
from tickets.urls import ticket_router

ticket_router.register(
    r'comments',
    CommentViewSet,
    basename="ticket-comments",
)

urlpatterns = [
    path("", include(ticket_router.urls))
]
