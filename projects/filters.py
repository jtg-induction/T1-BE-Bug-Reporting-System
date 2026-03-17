import django_filters
from projects.models import Project, ProjectMember
from django.contrib.auth import get_user_model

User = get_user_model()

class NumberInFilter(django_filters.BaseInFilter, django_filters.NumberFilter):
    pass


class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
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


class ProjectFilter(django_filters.FilterSet):

    role = django_filters.ChoiceFilter(field_name="project_members__role", choices=ProjectMember.Role.choices)

    role__in = NumberInFilter(field_name="project_members__role", lookup_expr="in")
    key__in = CharInFilter(field_name="key", lookup_expr="in")
    title__in = CharInFilter(field_name="title", lookup_expr="in")

    role__ne = NotEqualFilter(field_name="project_members__role")
    key__ne = NotEqualFilter(field_name="key")
    title__ne = NotEqualFilter(field_name="title")

    key__noticontains = NotContainsFilter(field_name="key")
    title__noticontains = NotContainsFilter(field_name="title")

    class Meta:
        model = Project

        fields = {
            "key": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "title": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "project_members__role": [
                "exact",
                "isnull",
            ]
        }
        
        
class ProjectMemberFilter(django_filters.FilterSet):

    role = django_filters.ChoiceFilter(choices=ProjectMember.Role.choices)
    designation = django_filters.ChoiceFilter(field_name="member__designation", choices=User.Designation.choices)
    
    role__in = NumberInFilter(field_name="role", lookup_expr="in")
    designation__in = CharInFilter(field_name="member__designation", lookup_expr="in")
    first_name__in = CharInFilter(field_name="member__first_name")
    last_name__in = CharInFilter(field_name="member__last_name")
    email__in = CharInFilter(field_name="member__email")

    role__ne = NotEqualFilter(field_name="role")
    designation__ne = NotEqualFilter(field_name="member__designation")
    first_name__in = CharInFilter(field_name="member__first_name", lookup_expr="in")
    last_name__in = CharInFilter(field_name="member__last_name", lookup_expr="in")
    email__in = CharInFilter(field_name="member__email", lookup_expr="in")
    
    first_name__noticontains = NotContainsFilter(field_name="member__first_name")
    last_name__noticontains = NotContainsFilter(field_name="member__last_name")
    email__noticontains = NotContainsFilter(field_name="member__email")


    class Meta:
        model = ProjectMember

        fields = {
            "member__first_name": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "member__last_name": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "member__email": [
                "exact",
                "icontains",
                "istartswith",
                "iendswith",
                "isnull",
            ],
            "role": [
                "exact",
                "isnull",
            ],
            "member__designation": [
                "exact",
                "isnull",
            ]
        }
        
        