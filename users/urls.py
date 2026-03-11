from django.urls import include, path
from rest_framework.routers import DefaultRouter

from users.views import UserAPIView

app_name = "users"

router = DefaultRouter()

router.register("", UserAPIView, basename="user")

urlpatterns = [
    path("", include(router.urls)),
]
