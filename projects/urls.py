from django.urls import include, path
from rest_framework_nested import routers

from projects.views import ProjectViewSet

router = routers.DefaultRouter()

router.register(r'projects', ProjectViewSet, basename="project")

project_router = routers.NestedDefaultRouter(router, r'projects', lookup='project')

urlpatterns = [
    path("", include(router.urls)),
]
