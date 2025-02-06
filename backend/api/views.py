import time
from datetime import timedelta, datetime

import numpy as np
import pandas as pd
from django.db.models import Avg, DateTimeField, Prefetch
from django.db.models.functions import Trunc
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import now
from rest_framework.exceptions import status

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
                          WorkingIntervalCommentSerializer,
                          WorkingIntervalMachineSerializer)


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


def rms(x):
    """Вычисление среднего квадратичного значения."""
    return np.sqrt(np.mean(np.square(x)))


def list_sensor_readings(request):
    """Вывод данных производительности по рабочим центрам.
    Только GET запросы.

    Query параметры:
        work_center: список id рабочих центров через запятую
        interval: интервал усреднения в минутах (по умолчанию 60 минут)
        from_datetime: начало периода в формате YYYY-MM-DDTHH:MM
        to_datetime: конец периода в формате YYYY-MM-DDTHH:MM
        zero: включать в ответ нулевые значения? (по умолчанию True)
    """
    if request.method != 'GET':
        return JsonResponse({'message': 'Method not allowed'},
                            status=status.HTTP_405_METHOD_NOT_ALLOWED)

    work_centers = request.GET.get('work_center')
    if not work_centers:
        return JsonResponse(
            {'work_center': 'Не заданы рабочие центры'},
            status=status.HTTP_400_BAD_REQUEST)

    work_centers = [int(i) for i in request.GET.get('work_center').split(',')]

    # интервал усреднения по умолчанию 60 минут
    interval = int(request.GET.get('interval', 60) or 60)

    # если не задана дата окончания периода, берем текущую дату
    to_datetime = request.GET.get('to_datetime', now()) or now()
    if isinstance(to_datetime, str):
        to_datetime = datetime.strptime(
            to_datetime,
            '%Y-%m-%dT%H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())

    # если не задана дата начала периода, берем предыдущие сутки от to_datetime
    from_datetime = request.GET.get(
        'from_datetime',
        to_datetime - timedelta(days=1)) or (to_datetime - timedelta(days=1))
    if isinstance(from_datetime, str):
        from_datetime = datetime.strptime(
            from_datetime,
            '%Y-%m-%dT%H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())

    if to_datetime < from_datetime:
        return JsonResponse(
            {'to_datetime': 'Дата окончания периода меньше даты начала '
                            'периода'},
            status=status.HTTP_400_BAD_REQUEST)

    if to_datetime - from_datetime < timedelta(minutes=interval):
        return JsonResponse({'interval': 'Интервал больше заданного периода'},
                            status=status.HTTP_400_BAD_REQUEST)

    # если передано убираем нулевые значения
    zero = not bool(request.GET.get('zero'))

    # данные по датчикам, усредненные за 1 минуту
    queryset = (
        SensorReading.objects.filter(
            sensor_id__in=work_centers,
            measured_at__gte=from_datetime,
            measured_at__lt=to_datetime
        )
        .annotate(
            timestamp=Trunc(
                'measured_at', 'minute', output_field=DateTimeField()), )
        .order_by('timestamp')
        .values('timestamp')
        .annotate(
            avg_value=Avg('value'),
        )
        .values('sensor_id', 'timestamp', 'avg_value')
    )

    if not queryset:
        return JsonResponse([], safe=False)

    start = time.time()
    # создаем датафрейм с индексами дата и id датчика
    df = pd.DataFrame.from_records(queryset, index=['timestamp', 'sensor_id'])

    # создаем мультииндекс с полным временным рядом с интервалом 1 минута
    date_range = pd.MultiIndex.from_product(
        [
            pd.date_range(
                start=from_datetime,
                end=to_datetime - timedelta(minutes=1),
                freq='min'),
            df.index.levels[1],
        ],
        names=['timestamp', 'sensor_id']
    )

    # переиндексируем датафрейм, заполняя недостающие данные нулями
    df = df.reindex(date_range, fill_value=0)

    if interval != 1:
        # усредняем датафрейм с интервалом interval
        df = (df.groupby(level='sensor_id')
              .resample(f'{interval}min', level='timestamp')
              # .mean())
              .aggregate(rms))

        # меняем местами индексы
        df = df.swaplevel()

    print(f'time = {time.time() - start}')

    sensors = (
        Sensor.objects
        .filter(pk__in=work_centers)
        .in_bulk(field_name='pk')
    )

    start = time.time()
    # d_json = df.to_json(
    #     orient='index',
    #     double_precision=0,
    #     date_unit='s',
    # )
    # parsed = loads(d_json)
    # print(dumps(parsed, indent=4))
    # print(f'{d_json=}')
    print(f'time = {time.time() - start}')

    start = time.time()
    # если передано zero, не включаем нулевые данные в ответ
    result = []
    timestamps = df.index.levels[0]
    for timestamp in timestamps:
        sensor_data = df.loc[timestamp]

        valid_values = sensor_data['avg_value'].round()
        if not (zero or not valid_values.empty):
            continue

        values = [
            {
                'sensor_slug': sensors[sensor_id].slug,
                'sensor_name': sensors[sensor_id].name,
                'value': value
            }
            for sensor_id, value in valid_values.items()
            if zero or value
        ]

        if values:
            result.append(
                # {'date': int(timestamp.timestamp()), 'values': values})
                {'date': timestamp, 'values': values})

    print(f'time = {time.time() - start}')

    return JsonResponse(result, safe=False)


class WorkingIntervalMachineViewSet(RetrieveModelMixin,
                                    GenericViewSet):
    permission_classes = [AllowAny]
    serializer_class = WorkingIntervalMachineSerializer
    # filterset_class = WorkingIntervalMachineFilter
    # pagination_class = LimitOffsetPagination
    lookup_field = 'slug'
    lookup_url_kwarg = 'sensor_slug'

    def get_queryset(self, *args, **kwargs):
        print(self.request.query_params)
        1/0
        from_datetime = datetime.strptime(
            self.request.query_params.get('from_datetime'),
            '%Y-%m-%dT%H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())
        to_datetime = datetime.strptime(
            self.request.query_params.get('to_datetime'),
            '%Y-%m-%dT%H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())
        queryset = Sensor.objects.prefetch_related(
            Prefetch(
                'working_intervals',
                queryset=WorkingInterval.objects.filter(
                    finished_at__gt=from_datetime,
                    started_at__lt=to_datetime
                ).select_related('status'),
                to_attr='filtered_intervals'
            ),
        )
        return queryset
