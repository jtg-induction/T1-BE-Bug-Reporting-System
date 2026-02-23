from django.urls import path
from users.views import UserAPIView

app_name = 'users'

urlpatterns = [
    path("me/", UserAPIView.as_view(), name="me"), 
]
