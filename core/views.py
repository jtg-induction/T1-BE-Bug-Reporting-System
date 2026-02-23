from datetime import timedelta
from django.utils import timezone
from uuid import uuid4
from rest_framework import status
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

from core.serializers import UserRegisterSerializer, UserEmailVerifySerializer
from rest_framework_simplejwt.tokens import RefreshToken
from core.models import EmailVerification
from core.utils import send_verification_email
import os
from dotenv import load_dotenv
load_dotenv()

SECURE = os.getenv("SECURE")

class CustomTokenObtainPairView(TokenObtainPairView):
    
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
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
            print(new_refresh)
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

class EmailVerifyAPIView(APIView):
    
    permission_classes=[AllowAny]
    
    def post(self, request):
        verify_token = request.query_params.get("token")
        
        if not verify_token:
            return Response({"detail": "Token not provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        verification = EmailVerification.objects.filter(verification_token=verify_token).first()
        
        if not verification:
            return Response({"detail": "Invalid Token"}, status=status.HTTP_401_UNAUTHORIZED)
        
        elif verification.isDeleted==True:
            return Response({"detail": "You are already registered. Please login"}, status=status.HTTP_200_OK)
        
        elif verification.updated_at < timezone.now() - timedelta(minutes=15):
            return Response({"detail": "Token Expired"}, status=status.HTTP_401_UNAUTHORIZED)

        return Response(status=status.HTTP_200_OK)
        

class UserRegistrationAPIView(CreateAPIView):

    serializer_class = UserRegisterSerializer
    permission_classes = [AllowAny]
    
    def post(self, request):
        verify_token = request.data.get("token")
        email = request.data.get("email")
        
        if not verify_token:
            return Response({"detail": "Token not provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        if not email:
            return Response({"detail": "Email not provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        if (EmailVerification.objects.filter(verification_token=verify_token, updated_at__gte=timezone.now()-timedelta(minutes=15), isDeleted=False).exists()):
            request.data.pop("token")
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

        return Response({"detail": "Token Expired"}, status=status.HTTP_401_UNAUTHORIZED)
        
    
class EmailVerifyTokenGenerateAPIView(APIView):

    serializer_class = UserEmailVerifySerializer
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        verify_token = EmailVerification.objects.filter(email=email).first()
        
        if(verify_token):
            
            if(verify_token.isDeleted==True):
                return Response({"detail": "You are already registered"}, status=status.HTTP_400_BAD_REQUEST)

            
            if(verify_token.updated_at > timezone.now() - timedelta(minutes=15)):
                return Response({"detail": "Mail already sent to your email"}, status=status.HTTP_200_OK)
            
            else:    
                send_verification_email(email=email, token=verify_token.verification_token)
                verify_token.verification_token = uuid4()
                verify_token.save(update_fields=["verification_token", "updated_at"])
                return Response(status=status.HTTP_200_OK)
        
        send_verification_email(email=email, token=verification.verification_token)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = serializer.save()
        return Response(status=status.HTTP_200_OK)