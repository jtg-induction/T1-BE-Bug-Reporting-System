from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CommentViewSet

router = DefaultRouter()

router.register(
    r"projects/(?P<project_id>[0-9a-f-]+)/tickets/(?P<ticket_id>[0-9a-f-]+)/comments",
    CommentViewSet,
    basename="ticket-comments",
)

urlpatterns = [
    path("", include(router.urls)),
]
