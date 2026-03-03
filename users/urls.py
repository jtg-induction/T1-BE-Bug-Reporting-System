from rest_framework.routers import DefaultRouter

from users.views import UserAPIView

app_name = "users"

router = DefaultRouter()

<<<<<<< HEAD
router.register("", UserAPIView, basename="")
=======
router.register('', UserAPIView, basename='user')

urlpatterns = [
    path("", include(router.urls)),
]
>>>>>>> 036397d (FS_02: Test cases fixes)
