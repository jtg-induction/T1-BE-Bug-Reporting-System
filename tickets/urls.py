from django.urls import include, path
from rest_framework_nested import routers

from projects.urls import project_router
from tickets.views import ProjectTicketViewSet, UserTicketViewSet

router = routers.DefaultRouter()
router.register(r'tickets', UserTicketViewSet, basename="user-tickets")

project_router.register(
    r'tickets',
    ProjectTicketViewSet,
    basename='project-tickets',
)

ticket_router = routers.NestedDefaultRouter(project_router, r'tickets', lookup="ticket")

urlpatterns = [
    path("", include(router.urls)),
    path("", include(project_router.urls))
]
