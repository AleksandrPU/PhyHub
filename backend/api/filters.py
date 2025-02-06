from django_filters import FilterSet, filters
from django_filters.constants import EMPTY_VALUES

from sensors.models import WorkingInterval


class EmptyStringFilter(filters.BooleanFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs
        exclude = self.exclude ^ (value is False)
        method = qs.exclude if exclude else qs.filter
        return method(**{self.field_name: ''})


class WorkingIntervalFilter(FilterSet):

    need_comment = filters.BooleanFilter('status__need_comment',
                                         label='Необходим комментарий')
    commented = EmptyStringFilter('comment',
                                  exclude=True,
                                  label='С комментарием')
    from_datetime = filters.DateTimeFilter('started_at', lookup_expr='gte')
    to_datetime = filters.DateTimeFilter('finished_at', lookup_expr='lte')

    class Meta:
        model = WorkingInterval
        fields = ['need_comment', 'commented', 'from_datetime', 'to_datetime']


class WorkingIntervalMachineFilter(FilterSet):
    from_datetime = filters.DateTimeFilter('started_at', lookup_expr='gte')
    to_datetime = filters.DateTimeFilter('finished_at', lookup_expr='lte')

    class Meta:
        model = WorkingInterval
        fields = ['from_datetime', 'to_datetime']
