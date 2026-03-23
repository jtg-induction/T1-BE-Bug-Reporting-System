import django_filters
from django.contrib.auth import get_user_model

from projects.models import Project, ProjectMember

User = get_user_model()


class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    """
    Provides support for 'IN' lookups with numeric values.
    Allows passing a comma-separated list of numbers in the query (e.g., ?role__in=1,2).
    """

    pass


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """
    Provides support for 'IN' lookups with string values.
    Allows passing a comma-separated list of strings in the query (e.g., ?title__in=App,Web).
    """

    pass


class NotEqualFilter(django_filters.Filter):
    """
    A custom filter that excludes a specific value from the queryset.
    Corresponds to a 'NOT EQUAL' operation.
    """

    def filter(self, qs, value):
        if value in (None, ""):
            return qs
        return qs.exclude(**{self.field_name: value})


class NotContainsFilter(django_filters.Filter):
    """
    A custom filter that excludes records where the field contains a specific string.
    Corresponds to a case-insensitive 'NOT CONTAINS' operation.
    """

    def filter(self, qs, value):
        if not value:
            return qs
        return qs.exclude(**{f"{self.field_name}__icontains": value})


class ProjectFilter(django_filters.FilterSet):
    """
    FilterSet for the Project model.

    Allows advanced filtering on project title, key, and member roles,
    including exact matches, partial string matches, null checks, and exclusions.
    """

    project_role = django_filters.ChoiceFilter(
        field_name="project_members__role", choices=ProjectMember.Role.choices
    )
    project_role__in = NumberInFilter(
        field_name="project_members__role", lookup_expr="in"
    )
    project_role__ne = NotEqualFilter(field_name="project_members__role")
    project_role__isnull = django_filters.BooleanFilter(
        field_name="project_members__role", lookup_expr="isnull"
    )

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

    key = django_filters.CharFilter(field_name="key", lookup_expr="exact")
    key__icontains = django_filters.CharFilter(
        field_name="key", lookup_expr="icontains"
    )
    key__istartswith = django_filters.CharFilter(
        field_name="key", lookup_expr="istartswith"
    )
    key__iendswith = django_filters.CharFilter(
        field_name="key", lookup_expr="iendswith"
    )
    key__isnull = django_filters.BooleanFilter(
        field_name="key", lookup_expr="isnull"
    )
    key__in = CharInFilter(field_name="key", lookup_expr="in")
    key__ne = NotEqualFilter(field_name="key")
    key__noticontains = NotContainsFilter(field_name="key")

    ordering = django_filters.OrderingFilter(
        fields=(
            ("key", "key"),
            ("title", "title"),
            ("project_members__role", "project_role"),
        )
    )

    class Meta:
        model = Project
        fields = []


class ProjectMemberFilter(django_filters.FilterSet):
    """
    FilterSet for the ProjectMember model.

    Provides detailed filtering for project members based on their associated
    User details (first name, last name, email, designation) and their specific
    Project role. Supports complex lookups like 'in', 'not equal', and 'icontains'.
    """

    first_name = django_filters.CharFilter(
        field_name="member__first_name", lookup_expr="exact"
    )
    first_name__icontains = django_filters.CharFilter(
        field_name="member__first_name", lookup_expr="icontains"
    )
    first_name__istartswith = django_filters.CharFilter(
        field_name="member__first_name", lookup_expr="istartswith"
    )
    first_name__iendswith = django_filters.CharFilter(
        field_name="member__first_name", lookup_expr="iendswith"
    )
    first_name__isnull = django_filters.BooleanFilter(
        field_name="member__first_name", lookup_expr="isnull"
    )
    first_name__in = CharInFilter(
        field_name="member__first_name", lookup_expr="in"
    )
    first_name__ne = NotEqualFilter(field_name="member__first_name")
    first_name__noticontains = NotContainsFilter(
        field_name="member__first_name"
    )

    last_name = django_filters.CharFilter(
        field_name="member__last_name", lookup_expr="exact"
    )
    last_name__icontains = django_filters.CharFilter(
        field_name="member__last_name", lookup_expr="icontains"
    )
    last_name__istartswith = django_filters.CharFilter(
        field_name="member__last_name", lookup_expr="istartswith"
    )
    last_name__iendswith = django_filters.CharFilter(
        field_name="member__last_name", lookup_expr="iendswith"
    )
    last_name__isnull = django_filters.BooleanFilter(
        field_name="member__last_name", lookup_expr="isnull"
    )
    last_name__in = CharInFilter(
        field_name="member__last_name", lookup_expr="in"
    )
    last_name__ne = NotEqualFilter(field_name="member__last_name")
    last_name__noticontains = NotContainsFilter(field_name="member__last_name")

    email = django_filters.CharFilter(
        field_name="member__email", lookup_expr="exact"
    )
    email__icontains = django_filters.CharFilter(
        field_name="member__email", lookup_expr="icontains"
    )
    email__istartswith = django_filters.CharFilter(
        field_name="member__email", lookup_expr="istartswith"
    )
    email__iendswith = django_filters.CharFilter(
        field_name="member__email", lookup_expr="iendswith"
    )
    email__isnull = django_filters.BooleanFilter(
        field_name="member__email", lookup_expr="isnull"
    )
    email__in = CharInFilter(field_name="member__email", lookup_expr="in")
    email__ne = NotEqualFilter(field_name="member__email")
    email__noticontains = NotContainsFilter(field_name="member__email")

    designation = django_filters.ChoiceFilter(
        field_name="member__designation", choices=User.Designation.choices
    )
    designation__in = CharInFilter(
        field_name="member__designation", lookup_expr="in"
    )
    designation__ne = NotEqualFilter(field_name="member__designation")
    designation__isnull = django_filters.BooleanFilter(
        field_name="member__designation", lookup_expr="isnull"
    )

    role = django_filters.ChoiceFilter(
        field_name="role", choices=ProjectMember.Role.choices
    )
    role__in = NumberInFilter(field_name="role", lookup_expr="in")
    role__ne = NotEqualFilter(field_name="role")
    role__isnull = django_filters.BooleanFilter(
        field_name="role", lookup_expr="isnull"
    )

    ordering = django_filters.OrderingFilter(
        fields=(
            ("member__first_name", "first_name"),
            ("member__last_name", "last_name"),
            ("member__email", "email"),
            ("member__designation", "designation"),
            ("role", "role"),
        )
    )

    class Meta:
        model = ProjectMember
        fields = []
