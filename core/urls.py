from django.urls import path
from core.views import UserRegistrationAPIView, EmailVerifyAPIView, EmailVerifyTokenGenerateAPIView, CustomTokenObtainPairView, CustomTokenRefreshView, CustomTokenBlacklistView

app_name = 'core'

urlpatterns = [
    path("register/", UserRegistrationAPIView.as_view(), name="register"),
    path("generate-email-link/", EmailVerifyTokenGenerateAPIView.as_view(), name="generate-email-link"),
    path("verify-link/", EmailVerifyAPIView.as_view(), name="verify-link"),
    path('refresh/', CustomTokenRefreshView.as_view(), name="token_refresh"),
    path('login/', CustomTokenObtainPairView.as_view(), name="login"),
    path('logout/', CustomTokenBlacklistView.as_view(), name="logout")
]
