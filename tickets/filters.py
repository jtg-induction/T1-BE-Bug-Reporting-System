import django_filters

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
    status = django_filters.ChoiceFilter(choices=Ticket.Status.choices)
    severity = django_filters.ChoiceFilter(choices=Ticket.Severity.choices)

    id__in = UUIDInFilter(field_name="id", lookup_expr="in")
    title__in = CharInFilter(field_name="title", lookup_expr="in")
    reporter__in = CharInFilter(field_name="reporter__email", lookup_expr="in")
    assignee__in = CharInFilter(field_name="assignee__email", lookup_expr="in")
    status__in = NumberInFilter(field_name="status", lookup_expr="in")
    severity__in = NumberInFilter(field_name="severity", lookup_expr="in")

    id__ne = NotEqualFilter(field_name="id")
    title__ne = NotEqualFilter(field_name="title")
    reporter__ne = NotEqualFilter(field_name="reporter__email")
    assignee__ne = NotEqualFilter(field_name="assignee__email")
    status__ne = NotEqualFilter(field_name="status")
    severity__ne = NotEqualFilter(field_name="severity")
    deadline__ne = NotEqualFilter(field_name="deadline")

    title__noticontains = NotContainsFilter(field_name="title")
    reporter__noticontains = NotContainsFilter(field_name="reporter__email")
    assignee__noticontains = NotContainsFilter(field_name="assignee__email")

    class Meta:
        model = Ticket
        fields = {
            "id": ["exact"],
            "title": ["exact", "icontains", "istartswith", "iendswith", "isnull"],
            "reporter__email": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "assignee__email": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "status": ["exact", "isnull"],
            "severity": ["exact", "isnull"],
            "deadline": ["exact", "isnull", "gt", "gte", "lt", "lte"],
        }
