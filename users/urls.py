from django.urls import include, path
from rest_framework.routers import DefaultRouter

from users.views import UserAPIViewSet

app_name = "users"

router = DefaultRouter()
router.register("", UserAPIViewSet, basename="user")

urlpatterns = [
    path("", UserAPIViewSet.as_view({"get": "current_user"}), name="user-current"),
    path("", include(router.urls)),
]
