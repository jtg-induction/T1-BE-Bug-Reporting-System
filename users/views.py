from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q
from django.db.models.functions import TruncDay
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.constants import history_time
from tickets.models import Ticket
from users.serializers import CurrentUserSerializer, UserSerializer

User = get_user_model()


class UserAPIViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
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

    @action(detail=False, methods=["get"], url_path="tickets-summary")
    def tickets_summary(self, request):
        timeline = timezone.now() - timedelta(seconds=history_time)
        summary = Ticket.objects.filter(assignee=request.user).aggregate(
            completed=Count("id", filter=Q(status=4)),
            missed_deadline=Count(
                "id", filter=Q(deadline__lt=timezone.now()) & ~Q(status=4)
            ),
            total=Count("id"),
            near_deadline=Count(
                "id",
                filter=Q(deadline__gte=timezone.now(), deadline__lte=timeline),
            ),
        )
        return Response(summary)

    from django.db.models.functions import TruncDay

    @action(detail=True, methods=["get"], url_path="user-summary")
    def user_summary(self, request, pk=None):
        query = request.query_params
        now = timezone.now()
        filter_date_format = "%Y-%m-%d"

        base_queryset = Ticket.objects.filter(assignee_id=pk)

        start_date = query.get("start-date")
        end_date = query.get("end-date")
        section = query.get("section")

        if start_date:
            start_dt = datetime.strptime(start_date, filter_date_format)
            base_queryset = base_queryset.filter(deadline__gte=start_dt)
        if end_date:
            end_dt = datetime.strptime(end_date, filter_date_format)
            base_queryset = base_queryset.filter(deadline__lte=end_dt)

        data = {}

        if not section or section == "ticket_status":
            data["ticket_status"] = base_queryset.aggregate(
                open=Count("id", filter=Q(status=1)),
                in_progress=Count("id", filter=Q(status=2)),
                resolved=Count("id", filter=Q(status=3)),
                closed=Count("id", filter=Q(status=4)),
            )

        if not section or section == "ticket_severity":
            data["ticket_severity"] = base_queryset.aggregate(
                lowest=Count("id", filter=Q(severity=1)),
                low=Count("id", filter=Q(severity=2)),
                medium=Count("id", filter=Q(severity=3)),
                high=Count("id", filter=Q(severity=4)),
                highest=Count("id", filter=Q(severity=5)),
            )

        if not section or section == "deadline_chart":
            data["deadline_chart"] = (
                base_queryset.filter(deadline__isnull=False)
                .annotate(day=TruncDay("deadline"))
                .values("day")
                .annotate(
                    missed=Count(
                        "id",
                        filter=Q(closed_at__gt=F("deadline"))
                        | Q(closed_at__isnull=True, deadline__lt=now),
                    ),
                    completed_on_time=Count(
                        "id", filter=Q(closed_at__date=F("deadline__date"))
                    ),
                    completed_before_time=Count(
                        "id", filter=Q(closed_at__lt=F("deadline"))
                    ),
                )
                .order_by("day")
            )

        return Response(data)
