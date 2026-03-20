import django_filters
from django.http import QueryDict
from rest_framework.filters import OrderingFilter

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


class TicketFilterMixin:
    """Mixin providing query parameter remapping for ticket filtering."""

    field_maps = {}

    def _remap_params(self, query_params, mapping):
        """
        Transforms API-facing keys into internal database-facing keys.
        Handles both standard filters (field__lookup) and the 'ordering' key.
        """
        new_params = QueryDict(mutable=True)

        for key, value in query_params.items():
            if key == "ordering":
                desc = value.startswith("-")
                field = value.lstrip("-")
                mapped = mapping.get(field)
                if mapped:
                    new_params[key] = f"-{mapped}" if desc else mapped
                else:
                    new_params[key] = value
                continue

            parts = key.split("__")
            field = parts[0]
            lookup = "__".join(parts[1:]) if len(parts) > 1 else ""

            mapped = mapping.get(field)
            if mapped:
                key = f"{mapped}__{lookup}" if lookup else mapped
                new_params[key] = value
            else:
                new_params[key] = value

        return new_params

    def filter_queryset(self, queryset):
        """
        Applies remapped query parameters to the queryset.
        """
        self.filterset_class = TicketFilter
        mapping = self.field_maps.get(self.action, {})

        if not mapping and not self.request.query_params:
            return super().filter_queryset(queryset)

        transformed_data = self._remap_params(self.request.query_params, mapping)

        filterset = self.filterset_class(
            data=transformed_data,
            queryset=queryset,
            request=self.request,
        )
        if filterset.is_valid():
            queryset = filterset.qs

        original_params = self.request._request.GET
        try:
            self.request._request.GET = transformed_data
            for backend in self.filter_backends:
                if issubclass(backend, OrderingFilter):
                    queryset = backend().filter_queryset(self.request, queryset, self)
        finally:
            self.request._request.GET = original_params

        return queryset


class TicketFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Ticket.Status.choices)
    severity = django_filters.ChoiceFilter(choices=Ticket.Severity.choices)

    id__in = UUIDInFilter(field_name="id", lookup_expr="in")
    title__in = CharInFilter(field_name="title", lookup_expr="in")
    status__in = NumberInFilter(field_name="status", lookup_expr="in")
    severity__in = NumberInFilter(field_name="severity", lookup_expr="in")

    reporter__email__in = CharInFilter(field_name="reporter__email", lookup_expr="in")
    assignee__email__in = CharInFilter(field_name="assignee__email", lookup_expr="in")

    id__ne = NotEqualFilter(field_name="id")
    title__ne = NotEqualFilter(field_name="title")
    status__ne = NotEqualFilter(field_name="status")
    severity__ne = NotEqualFilter(field_name="severity")
    deadline__ne = NotEqualFilter(field_name="deadline")

    reporter__email__ne = NotEqualFilter(field_name="reporter__email")
    assignee__email__ne = NotEqualFilter(field_name="assignee__email")

    title__noticontains = NotContainsFilter(field_name="title")

    reporter__email__noticontains = NotContainsFilter(field_name="reporter__email")
    assignee__email__noticontains = NotContainsFilter(field_name="assignee__email")

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
