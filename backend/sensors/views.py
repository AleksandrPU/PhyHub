from datetime import datetime
from typing import Iterable

from django.db.models import Avg, Count, FloatField, Q
from django.db.models.functions import Cast, Greatest
from django.views.generic import DetailView

from .filters import WorkingIntervalFilter
from .models import Sensor, SensorReading, WorkingInterval


class SensorChartView(DetailView):
    model = Sensor
    context_object_name = 'sensor'
    template_name = 'sensors/sensor_readings.html'
    filterset_class = WorkingIntervalFilter

    @staticmethod
    def qs_to_chart_data(readings):
        data = (
            f'[new Date({int(r.measured_at.timestamp()) * 1000}), {r.value}]'
            for r in readings
        )
        s = ', '.join(data)
        return f'[{s}]'

    @staticmethod
    def qs_to_timeline_data(intervals: Iterable[WorkingInterval]):
        data = []
        for interval in intervals:
            if interval.status is None:
                name = 'NA'
                color = '#000000'
            else:
                name = interval.status.name
                color = interval.status.color
            data.append(
                f"['{name}', "
                f"'{name}', "
                f"'{color}', "
                f"new Date({int(interval.started_at.timestamp()) * 1000}), "
                f"new Date("
                f"{(int((interval.finished_at or datetime.now()).timestamp()) * 1000)}"
                f")]"
            )
        s = ', '.join(data)
        return f'[{s}]'

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        interval_filter = self.filterset_class(
            self.request.GET,
            queryset=(self
                      .object
                      .working_intervals
                      .prefetch_related('status')
                      .order_by('started_at'))
        )
        working_intervals = interval_filter.qs
        sensor_readings = SensorReading.objects.filter(
            working_interval_id__in=(i.pk for i in working_intervals)
        )
        speed = sensor_readings.aggregate(
            avg_gt0=Avg('value', filter=Q(value__gt=0)),
            avg=Avg('value'),
            idle=(Cast(Count('value', filter=Q(value__gt=0)),
                       output_field=FloatField())
                  / Greatest(Count('value'), 1)
                  * 100.0)
        )
        data['filter'] = interval_filter
        data['working_intervals'] = working_intervals
        data['chart_data'] = self.qs_to_chart_data(sensor_readings)
        data['timeline_data'] = self.qs_to_timeline_data(working_intervals)
        data['summary'] = speed
        data['sensors'] = Sensor.objects.all()
        return data
