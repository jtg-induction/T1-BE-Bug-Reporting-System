from rest_framework.generics import RetrieveAPIView, UpdateAPIView
from rest_framework.permissions import IsAuthenticated

from users.serializers import UserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()

class UserAPIView(RetrieveAPIView, UpdateAPIView):
    
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        return UserSerializer
    
    def get_object(self):
        return self.request.user
