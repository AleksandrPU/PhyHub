from datetime import timedelta, datetime

import pandas as pd
from django.db.models import Avg, DateTimeField
from django.db.models.functions import Trunc
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import now

from rest_framework.generics import CreateAPIView, get_object_or_404
from rest_framework.mixins import (ListModelMixin, RetrieveModelMixin,
                                   UpdateModelMixin)
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny
from rest_framework.viewsets import GenericViewSet

from sensors.models import Sensor, SensorReading, WorkingInterval
from .filters import WorkingIntervalFilter
from .serializers import (SensorReadingListSerializer,
                          SensorSerializer,
                          WorkingIntervalCommentSerializer)


class SensorReadingsCreateView(CreateAPIView):
    queryset = SensorReading.objects.all()
    serializer_class = SensorReadingListSerializer


class WorkingIntervalViewSet(RetrieveModelMixin,
                             UpdateModelMixin,
                             ListModelMixin,
                             GenericViewSet):
    permission_classes = [AllowAny]
    serializer_class = WorkingIntervalCommentSerializer
    filterset_class = WorkingIntervalFilter
    pagination_class = LimitOffsetPagination
    lookup_url_kwarg = 'interval_pk'
    queryset = (WorkingInterval
                .objects
                .prefetch_related('sensor', 'status__reasons'))

    def get_queryset(self):
        sensor = get_object_or_404(Sensor.objects.all(),
                                   slug=self.kwargs['sensor_slug'])
        return self.queryset.filter(sensor=sensor)


class SensorViewSet(ListModelMixin, GenericViewSet):
    queryset = Sensor.objects.all()
    serializer_class = SensorSerializer


def list_sensor_readings(request):
    if request.method != 'GET':
        return JsonResponse({'message': 'Method not allowed'}, status=405)

    work_centers = request.GET.get('work_center')

    assert work_centers, 'Параметр work_center не может быть пустым'

    work_centers = [int(i) for i in request.GET.get('work_center').split(',')]

    interval = int(request.GET.get('interval', 60) or 60)

    to_datetime = request.GET.get('to_datetime', now()) or now()
    if isinstance(to_datetime, str):
        to_datetime = datetime.strptime(
            to_datetime,
            '%Y-%m-%d %H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())

    from_datetime = request.GET.get(
        'from_datetime',
        to_datetime - timedelta(days=1)) or (to_datetime - timedelta(days=1))
    if isinstance(from_datetime, str):
        from_datetime = datetime.strptime(
            from_datetime,
            '%Y-%m-%d %H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())

    assert (to_datetime - from_datetime > timedelta(minutes=interval),
            'Интервал больше заданного периода')

    queryset = (
        SensorReading.objects.filter(
            # sensor_id__in=(1, 2, 5),
            # sensor_id=1,
            # measured_at__gte='2025-01-25 00:00',
            # measured_at__lt='2025-01-26 00:00'
            sensor_id__in=work_centers,
            measured_at__gte=from_datetime,
            measured_at__lt=to_datetime
        )
        .annotate(
            date_to_minute=Trunc(
                'measured_at', 'minute', output_field=DateTimeField()), )
        .order_by('date_to_minute')
        .values('date_to_minute')
        .annotate(
            avg_value=Avg('value'),
        )
        .values('sensor_id', 'date_to_minute', 'avg_value')
    )

    assert (queryset,
            f'Данные за период с {from_datetime} по {to_datetime} отсутствуют')

    sensors = (
        Sensor.objects
        .filter(pk__in=work_centers)
        .values('pk', 'slug', 'name')
        .in_bulk(field_name='pk')
    )

    df = pd.DataFrame.from_records(
        queryset, index=['date_to_minute', 'sensor_id'])
    date_range = pd.MultiIndex.from_product(
        [
            pd.date_range(
                # start=datetime(
                # 2025, 1, 25, 0, 0, tzinfo=timezone.get_current_timezone()),
                # end=datetime(
                # 2025, 1, 25, 23, 59, tzinfo=timezone.get_current_timezone()),
                start=from_datetime,
                end=to_datetime - timedelta(minutes=1),
                freq='min'),
            df.index.levels[1],
        ],
        names=['date_to_minute', 'sensor_id']
    )

    df_filled = df.reindex(date_range, fill_value=0)
    df_resample = (
        df_filled
        .groupby(level='sensor_id')
        .resample(f'{interval}min', level='date_to_minute')
        .mean())

    df_resample = df_resample.swaplevel()
    # result = df_resample['avg_value'].unstack().to_dict(orient='index')
    #
    # final = {
    #     key.to_pydatetime().strftime('%Y-%m-%dT%H:%M:%S.%f'): value
    #     for key, value in result.items()}

    # result = []
    # for timestamp, group in df_resample.groupby(level='date_to_minute'):
    #     values = [{'sensor_id': sensor_id, 'value': float(row['avg_value'])} for sensor_id, row in
    #               group.iterrows()]
    #     result.append({'date': int(timestamp.timestamp()), 'values': values})

    result = []
    for timestamp in df_resample.index.levels[0]:
        values = []
        for sensor_id in df_resample.loc[timestamp].index:
            # values.append({'sensor_id': sensor_id,
            values.append({'sensor_id': Sensor.objects.get,
                           'value': float(df_resample.loc[timestamp].loc[sensor_id, 'avg_value'])})
        result.append({'date': int(timestamp.timestamp()), 'values': values})

    return JsonResponse(result)
