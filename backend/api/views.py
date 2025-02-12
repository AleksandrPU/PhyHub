import time
from datetime import timedelta, datetime

import numpy as np
import pandas as pd
from django.db.models import Avg, F, Prefetch, Q
from django.db.models.functions import Trunc
from django.http import JsonResponse
from django.utils import timezone
from django.utils.timezone import now
from rest_framework.exceptions import ValidationError, status

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

    def get_queryset(self):
        if self.request.query_params.get('is_enabled'):
            return self.queryset.filter(is_enabled=True)
        return self.queryset


def rms(x):
    """Вычисление среднего квадратичного значения."""
    return np.sqrt(np.mean(np.square(x)))


def parse_datetime(str_datetime: str, default: datetime = None) -> datetime:
    """Преобразование строки в datetime."""
    if isinstance(str_datetime, str):
        return datetime.strptime(
            str_datetime,
            '%Y-%m-%dT%H:%M'
        ).replace(tzinfo=timezone.get_current_timezone())
    return default


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

    work_centers = [int(i) for i in work_centers.split(',')]

    # интервал усреднения по умолчанию 60 минут
    interval = int(request.GET.get('interval', 60) or 60)

    # если не задана дата окончания периода, берем текущую дату
    to_datetime = parse_datetime(request.GET.get('to_datetime'), now())

    # если не задана дата начала периода, берем предыдущие сутки от to_datetime
    from_datetime = parse_datetime(
        request.GET.get('from_datetime'), to_datetime - timedelta(days=1))

    if to_datetime < from_datetime:
        return JsonResponse(
            {'to_datetime': 'Дата окончания периода меньше даты начала '
                            'периода'},
            status=status.HTTP_400_BAD_REQUEST)

    if to_datetime - from_datetime < timedelta(minutes=interval):
        return JsonResponse({'interval': 'Интервал больше заданного периода'},
                            status=status.HTTP_400_BAD_REQUEST)

    # если передано убираем нулевые значения
    # zero = not bool(request.GET.get('zero'))

    # данные по датчикам, усредненные за 1 минуту
    queryset = (
        SensorReading.objects.filter(
            sensor_id__in=work_centers,
            measured_at__gte=from_datetime,
            measured_at__lt=to_datetime
        )
        .annotate(
            timestamp=Trunc(
                'measured_at', 'minute'))
        .order_by('timestamp')
        .values('sensor_id', 'timestamp')
        .annotate(avg_value=Avg('value'))
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
                # end=to_datetime - timedelta(minutes=1),
                end=min(
                    to_datetime - timedelta(minutes=1),
                    timezone.localtime()
                ),
                freq='min'),
            df.index.levels[1],
        ],
        names=['timestamp', 'sensor_id']
    )

    # переиндексируем датафрейм, заполняя недостающие данные нулями
    df = df.reindex(date_range, fill_value=0)

    if interval != 1:
        # усредняем датафрейм с интервалом interval и
        # меняем местами индексы
        df = (df.groupby(level='sensor_id')
              .resample(f'{interval}min', level='timestamp')
              # .mean())
              .aggregate(rms)
              .swaplevel())

    print(f'time = {time.time() - start}')

    sensors = (
        Sensor.objects
        .filter(pk__in=work_centers)
        .in_bulk(field_name='pk')
    )

    start = time.time()
    avg_values = df.to_dict(orient='split', index=True)
    final = []
    values = []
    prev_timestamp = None
    for ((timestamp, sensor_id), [value]) in (
            zip(avg_values['index'], avg_values['data'])):
        if prev_timestamp is None:
            prev_timestamp = timestamp
        elif timestamp != prev_timestamp:
            final.append({'date': prev_timestamp, 'values': values})
            values = []
            prev_timestamp = timestamp
        values.append({
            'sensor_slug': sensors[sensor_id].slug,
            'sensor_name': sensors[sensor_id].name,
            'value': int(value)
        })
    if values:
        final.append({'date': prev_timestamp, 'values': values})
    print(f'split time = {time.time() - start}')
    return JsonResponse(final, safe=False)


class WorkingIntervalMachineViewSet(ListModelMixin,
                                    GenericViewSet):
    permission_classes = [AllowAny]
    serializer_class = WorkingIntervalMachineSerializer
    # filterset_class = WorkingIntervalMachineFilter
    # pagination_class = LimitOffsetPagination
    # lookup_field = 'slug'
    # lookup_url_kwarg = 'sensor_slug'

    def get_queryset(self, *args, **kwargs):
        work_centers = self.request.query_params.get('work_center')
        if not work_centers:
            raise ValidationError({'work_center': 'Не заданы рабочие центры'})

        # если не задана дата окончания периода, берем текущую дату
        to_datetime = parse_datetime(
            self.request.query_params.get('to_datetime'),
            now())

        # если не задана дата начала периода,
        # берем предыдущие сутки от to_datetime
        from_datetime = parse_datetime(
            self.request.query_params.get('from_datetime'),
            to_datetime - timedelta(days=1))

        if to_datetime < from_datetime:
            raise ValidationError(
                {'to_datetime': 'Дата окончания периода меньше даты начала '
                                'периода'})

        work_centers = [int(i) for i in work_centers.split(',')]
        queryset = Sensor.objects.filter(pk__in=work_centers).prefetch_related(
            Prefetch(
                'working_intervals',
                queryset=WorkingInterval.objects.filter(
                    # Отфильтровываем интервалы с длительностью меньше минуты
                    ~Q(
                        started_at__gt=F('finished_at') - timedelta(minutes=1)
                    )
                    | Q(finished_at__isnull=True),
                    # finished_at__gt=from_datetime,
                    # started_at__lt=to_datetime,
                    Q(started_at__lte=to_datetime)
                    & (
                        Q(finished_at__gte=from_datetime)
                        | Q(finished_at__isnull=True)
                    )
                ).select_related('status'),
                to_attr='filtered_intervals'
            ),
        )
        return queryset
