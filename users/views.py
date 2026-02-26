from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated

from users.serializers import UserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()

class UserAPIView(RetrieveUpdateAPIView):
    
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']
    serializer_class = UserSerializer
    
    def get_object(self):
        return self.request.user
