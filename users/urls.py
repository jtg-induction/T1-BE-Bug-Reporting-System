from django.urls import path
from users.views import UserAPIView

app_name = 'users'

urlpatterns = [
    path("<int:pk>/", UserAPIView.as_view(), name="user"), 
]
