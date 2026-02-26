from django.utils import timezone
from uuid import uuid4
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView
from rest_framework.exceptions import ParseError, NotAuthenticated
from core.serializers import UserRegisterSerializer, UserEmailVerifySerializer
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import EmailVerification
from core.utils import send_verification_email
import os
from urllib.parse import unquote
from dotenv import load_dotenv
load_dotenv()

SECURE = os.getenv("SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}

class CustomTokenObtainPairView(TokenObtainPairView):
    
    def post(self, request, *args, **kwargs):
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
            path="/api/"
        )
        return response 
    
class CustomTokenRefreshView(TokenRefreshView):
    
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get("refresh")
        
        if refresh is None:
            return Response({"detail": "No refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
        
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
                path="/api/"
            )
        return response
    
class CustomTokenBlacklistView(TokenBlacklistView):
    
    def post(self, request, *args, **kwargs):
        
        refresh = request.COOKIES.get("refresh")
        
        if refresh is None:
            return Response({"detail": "No refresh token"}, status=status.HTTP_401_UNAUTHORIZED)
        
        request.data["refresh"] = refresh
        response = super().post(request, *args, **kwargs)
        response.delete_cookie(
            key="refresh",
            path="/api/"
        )
        
        return response        

class UserRegistrationAPIView(CreateAPIView):

    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny]
    
    def post(self, request):
        verify_token = unquote(request.data.get("token"))
        email = unquote(request.data.get("email"))
        
        if not verify_token:
            return ParseError("Token not provided", status=status.HTTP_400_BAD_REQUEST)
        
        if not email:
            return ParseError("Email not provided", status=status.HTTP_400_BAD_REQUEST)
        
        emailVerified = EmailVerification.objects.filter(verification_token=verify_token, email=email, expires_at__gte=timezone.now(), isDeleted=False).first()
        
        if (emailVerified):
            request.data.pop("token")
            request.data["email"] = email
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            
            response = Response({"access": str(refresh.access_token)}, status=status.HTTP_201_CREATED)
            response.set_cookie(
                key="refresh",
                value=refresh,
                httponly=True,
                secure=SECURE,
                samesite="Strict",
                path="/api/"
            )
            
            EmailVerification.objects.filter(email=email).delete()
            
            return response

        return NotAuthenticated("Token Expired", status=status.HTTP_401_UNAUTHORIZED)
        
    
class EmailVerifyTokenGenerateAPIView(APIView):

    serializer_class = UserEmailVerifySerializer
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        verify_token = EmailVerification.objects.filter(email=email).first()
        
        if(verify_token):
            
            if(verify_token.isDeleted==True):
                return ParseError("You are already registered", status=status.HTTP_400_BAD_REQUEST)

            
            if(verify_token.expires_at > timezone.now()):
                return Response({"detail": "Mail already sent to your email"}, status=status.HTTP_200_OK)
            
            else:
                verify_token.verification_token = uuid4()
                verify_token.save(update_fields=["verification_token"])
                send_verification_email(email=email, token=verify_token.verification_token)
                return Response({"detail": "Mail sent to your email"}, status=status.HTTP_200_OK)
        
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = serializer.save()
        send_verification_email(email=email, token=verification.verification_token)
        return Response({"detail": "Mail sent to your email"}, status=status.HTTP_200_OK)
