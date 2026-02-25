from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from users.serializers import UserSerializer

User = get_user_model()


class UserAPIView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        target_user = get_object_or_404(User, pk=pk)
        data = {"user": request.user}
        serializer = UserSerializer(target_user, context=data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def update(self, request, pk=None):
        if str(request.user.id) != pk:
            raise PermissionDenied("You can only update your own profile.")
        data = {"user": request.user}
        serializer = UserSerializer(request.user, data=request.data, partial=True, context=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
