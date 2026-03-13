from django.contrib.auth import get_user_model
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from users.serializers import CurrentUserSerializer, UserSerializer

User = get_user_model()


class UserAPIViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    ViewSet for managing user profiles.
    Provides endpoints to retrieve user details and allows users to update their own profile.
    """

    queryset = User.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """
        Determines the appropriate serializer based on the current action.
        Uses CurrentUserSerializer for updates and the current user endpoint, otherwise defaults to UserSerializer.
        """
        if self.action in ["update", "partial_update", "current_user"]:
            return CurrentUserSerializer
        return UserSerializer

    def check_object_permissions(self, request, obj):
        """
        Checks object-level permissions before executing an action.
        Ensures that users can only modify their own profile information.
        """
        super().check_object_permissions(request, obj)
        if self.action in ["update", "partial_update"] and obj != request.user:
            raise PermissionDenied("You can only update your own profile.")

    def perform_update(self, serializer):
        """
        Saves the updated user object and records the user who made the modification.
        """
        serializer.save(updated_by=self.request.user)

    def current_user(self, request, *args, **kwargs):
        """
        Retrieves the profile information of the currently authenticated user.
        """
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)
