from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ProjectTicketViewSet, UserTicketViewSet

router = DefaultRouter()
router.register(r"tickets", UserTicketViewSet, basename="user-tickets")

router.register(
    r"projects/(?P<project_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/tickets",
    ProjectTicketViewSet,
    basename="project-tickets",
)

urlpatterns = [
    path("", include(router.urls)),
]
