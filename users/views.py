from django.contrib.auth import get_user_model
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated

from users.serializers import UserSerializer

User = get_user_model()


class UserAPIView(RetrieveUpdateAPIView):
    """
    API view to retrieve or update the authenticated user's profile.

    This view provides 'GET' and 'PATCH' methods specifically for the
    currently logged-in user, ensuring they can only access their own data.
    """

    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"]
    serializer_class = UserSerializer

    def get_object(self):
        """
        Return the currently authenticated user instance.

        Overrides the default behavior to bypass lookup fields (like pk)
        and return the user attached to the request.
        """
        return self.request.user
