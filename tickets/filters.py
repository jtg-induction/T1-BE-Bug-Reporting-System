import django_filters
from django.db.models import Value
from django.db.models.functions import Concat, Trim

from tickets.models import Ticket


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class UUIDInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    pass


class NotEqualFilter(django_filters.Filter):
    def filter(self, qs, value):
        if value in (None, ""):
            return qs
        return qs.exclude(**{self.field_name: value})


class NotContainsFilter(django_filters.Filter):
    def filter(self, qs, value):
        if not value:
            return qs
        return qs.exclude(**{f"{self.field_name}__icontains": value})


class TicketFilter(django_filters.FilterSet):
    """
    FilterSet for the Ticket model.
    """

    id = django_filters.UUIDFilter(field_name="id", lookup_expr="exact")
    id__in = UUIDInFilter(field_name="id", lookup_expr="in")
    id__ne = NotEqualFilter(field_name="id")
    id__isnull = django_filters.BooleanFilter(field_name="id", lookup_expr="isnull")

    title = django_filters.CharFilter(field_name="title", lookup_expr="exact")
    title__icontains = django_filters.CharFilter(
        field_name="title", lookup_expr="icontains"
    )
    title__istartswith = django_filters.CharFilter(
        field_name="title", lookup_expr="istartswith"
    )
    title__iendswith = django_filters.CharFilter(
        field_name="title", lookup_expr="iendswith"
    )
    title__isnull = django_filters.BooleanFilter(
        field_name="title", lookup_expr="isnull"
    )
    title__in = CharInFilter(field_name="title", lookup_expr="in")
    title__ne = NotEqualFilter(field_name="title")
    title__noticontains = NotContainsFilter(field_name="title")

    reporter_name = django_filters.CharFilter(
        field_name="reporter_full_name", lookup_expr="exact"
    )
    reporter_name__icontains = django_filters.CharFilter(
        field_name="reporter_full_name", lookup_expr="icontains"
    )
    reporter_name__istartswith = django_filters.CharFilter(
        field_name="reporter_full_name", lookup_expr="istartswith"
    )
    reporter_name__iendswith = django_filters.CharFilter(
        field_name="reporter_full_name", lookup_expr="iendswith"
    )
    reporter_name__isnull = django_filters.BooleanFilter(
        field_name="reporter", lookup_expr="isnull"
    )
    reporter_name__in = CharInFilter(field_name="reporter_full_name", lookup_expr="in")
    reporter_name__ne = NotEqualFilter(field_name="reporter_full_name")
    reporter_name__noticontains = NotContainsFilter(field_name="reporter_full_name")

    assignee_name = django_filters.CharFilter(
        field_name="assignee_full_name", lookup_expr="exact"
    )
    assignee_name__icontains = django_filters.CharFilter(
        field_name="assignee_full_name", lookup_expr="icontains"
    )
    assignee_name__istartswith = django_filters.CharFilter(
        field_name="assignee_full_name", lookup_expr="istartswith"
    )
    assignee_name__iendswith = django_filters.CharFilter(
        field_name="assignee_full_name", lookup_expr="iendswith"
    )
    assignee_name__isnull = django_filters.BooleanFilter(
        field_name="assignee", lookup_expr="isnull"
    )
    assignee_name__in = CharInFilter(field_name="assignee_full_name", lookup_expr="in")
    assignee_name__ne = NotEqualFilter(field_name="assignee_full_name")
    assignee_name__noticontains = NotContainsFilter(field_name="assignee_full_name")
    status = django_filters.ChoiceFilter(
        field_name="status", choices=Ticket.Status.choices
    )
    status__in = NumberInFilter(field_name="status", lookup_expr="in")
    status__ne = NotEqualFilter(field_name="status")
    status__isnull = django_filters.BooleanFilter(
        field_name="status", lookup_expr="isnull"
    )

    severity = django_filters.ChoiceFilter(
        field_name="severity", choices=Ticket.Severity.choices
    )
    severity__in = NumberInFilter(field_name="severity", lookup_expr="in")
    severity__ne = NotEqualFilter(field_name="severity")
    severity__isnull = django_filters.BooleanFilter(
        field_name="severity", lookup_expr="isnull"
    )

    deadline = django_filters.DateTimeFilter(field_name="deadline", lookup_expr="exact")
    deadline__isnull = django_filters.BooleanFilter(
        field_name="deadline", lookup_expr="isnull"
    )
    deadline__ne = NotEqualFilter(field_name="deadline")
    deadline__gt = django_filters.DateTimeFilter(
        field_name="deadline", lookup_expr="gt"
    )
    deadline__gte = django_filters.DateTimeFilter(
        field_name="deadline", lookup_expr="gte"
    )
    deadline__lt = django_filters.DateTimeFilter(
        field_name="deadline", lookup_expr="lt"
    )
    deadline__lte = django_filters.DateTimeFilter(
        field_name="deadline", lookup_expr="lte"
    )

    ordering = django_filters.OrderingFilter(
        fields=(
            ("id", "id"),
            ("title", "title"),
            ("reporter_full_name", "reporter_name"),
            ("assignee_full_name", "assignee_name"),
            ("severity", "severity"),
            ("status", "status"),
            ("deadline", "deadline"),
            ("created_at", "created_at"),
        )
    )

    def __init__(self, data=None, queryset=None, *, request=None, prefix=None):
        if queryset is None:
            queryset = Ticket.objects.all()
        queryset = queryset.annotate(
            reporter_full_name=Trim(
                Concat("reporter__first_name", Value(" "), "reporter__last_name")
            ),
            assignee_full_name=Trim(
                Concat("assignee__first_name", Value(" "), "assignee__last_name")
            ),
        )
        super().__init__(data=data, queryset=queryset, request=request, prefix=prefix)

    class Meta:
        model = Ticket
        fields = []
