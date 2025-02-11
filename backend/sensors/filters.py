from datetime import timedelta
from typing import Any

from django.db.models import Q
from django.forms import TextInput
from django.utils import timezone
from django_filters.filters import DateTimeFilter
from django_filters.filterset import FilterSet

from .models import SensorReading


class WorkingIntervalFilter(FilterSet):
    datetime_min = DateTimeFilter(
        widget=TextInput(attrs={'type': 'datetime-local'}),
        label='С'
    )
    datetime_max = DateTimeFilter(
        widget=TextInput(attrs={'type': 'datetime-local'}),
        label='По'
    )

    class Meta:
        model = SensorReading
        fields = []

    def filter_queryset(self, queryset):
        cleaned_data: dict[str, Any] = self.form.cleaned_data
        datetime_max = cleaned_data['datetime_max'] or timezone.now()
        datetime_min = (cleaned_data['datetime_min']
                        or datetime_max - timedelta(days=1))
        queryset = queryset.filter(
            (Q(started_at__gte=datetime_min) & Q(started_at__lt=datetime_max))
            | (Q(started_at__lt=datetime_min)
               & (Q(finished_at__gt=datetime_min)
                  | Q(finished_at__isnull=True)))
        )
        return queryset

