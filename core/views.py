import os
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from core.models import EmailVerification
from core.serializers import UserEmailVerifySerializer, UserRegisterSerializer
from core.utils import send_verification_email

User = get_user_model()

SECURE = os.getenv("SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom view to obtain JWT access and refresh tokens.
    Stores the refresh token in an HttpOnly cookie instead of the response body.
    """

    def post(self, request, *args, **kwargs):
        """
        Overrides the post method to move the refresh token to a secure cookie.
        """
        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK or "refresh" not in response.data:
            return response
        refresh = response.data.pop("refresh")

        response.set_cookie(
            key="refresh",
            value=refresh,
            httponly=True,
            secure=SECURE,
            samesite="Strict",
            path="/api/",
        )
        return response


class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom view to refresh JWT access tokens.
    Reads the refresh token from an HttpOnly cookie.
    """

    def post(self, request, *args, **kwargs):
        """
        Extracts the refresh token from cookies and updates it if rotated.
        """
        refresh = request.COOKIES.get("refresh")

        if refresh is None:
            return Response(
                {"detail": "No refresh token"}, status=status.HTTP_401_UNAUTHORIZED
            )

        request.data["refresh"] = refresh

        response = super().post(request, *args, **kwargs)

        if "refresh" in response.data:
            new_refresh = response.data.pop("refresh")
            response.set_cookie(
                key="refresh",
                value=new_refresh,
                httponly=True,
                secure=SECURE,
                samesite="Strict",
                path="/api/",
            )
        return response


class CustomTokenBlacklistView(TokenBlacklistView):
    """
    Custom view to blacklist the refresh token and log out the user.
    """

    def post(self, request, *args, **kwargs):
        """
        Blacklists the token found in cookies and deletes the cookie from the client.
        """
        refresh = request.COOKIES.get("refresh")

        if refresh is None:
            return Response(
                {"detail": "No refresh token"}, status=status.HTTP_401_UNAUTHORIZED
            )

        request.data["refresh"] = refresh
        response = super().post(request, *args, **kwargs)
        response.delete_cookie(key="refresh", path="/api/")

        return response


class UserRegistrationAPIView(CreateAPIView):
    """
    API view for user registration using a valid email verification token.
    """

    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        response = Response(
            {"access": str(refresh.access_token)}, status=status.HTTP_201_CREATED
        )
        response.set_cookie(
            key="refresh",
            value=str(refresh),
            httponly=True,
            secure=SECURE,
            samesite="Strict",
            path="/api/",
        )

        EmailVerification.objects.filter(email=user.email).delete()

        return response


class EmailVerifyTokenGenerateAPIView(APIView):
    """
    API view to generate or regenerate an email verification link.
    """

    serializer_class = UserEmailVerifySerializer
    permission_classes = [AllowAny]

    def post(self, request):
        """
        Checks for existing valid tokens or creates a new one to send via email.
        """
        email = request.data.get("email")

        if User.objects.filter(email=email).exists():
            raise ParseError("You are already registered")

        verify_token = EmailVerification.objects.filter(email=email).first()

        if verify_token:
            if verify_token.expires_at > timezone.now():
                return Response(
                    {"detail": "Mail already sent to your email"},
                    status=status.HTTP_200_OK,
                )

            else:
                verify_token.verification_token = uuid4()
                verify_token.save(update_fields=["verification_token"])
                send_verification_email(
                    email=email, token=verify_token.verification_token
                )
                return Response(
                    {"detail": "Mail sent to your email"}, status=status.HTTP_200_OK
                )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = serializer.save()
        send_verification_email(email=email, token=verification.verification_token)
        return Response(
            {"detail": "Mail sent to your email"}, status=status.HTTP_200_OK
        )
