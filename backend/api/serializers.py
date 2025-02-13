import logging
from enum import StrEnum
from typing import Callable

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from sensors.models import (Sensor, SensorReading, StatusReason, SensorStatus,
                            WorkingInterval)

logger = logging.getLogger(__name__)

# class SensorReadingSerializer(serializers.ModelSerializer):
#     sensor = serializers.SlugField()
#
#     class Meta:
#         model = SensorReading
#         fields = ['sensor', 'value', 'measured_at']
#         read_only_fields = ['measured_at']


class SensorReadingSerializer(serializers.ModelSerializer):

    class ReadingStatuses(StrEnum):
        OK = 'OK'
        NOT_FOUND = 'Not Found'

    name = serializers.SlugRelatedField(
        slug_field='slug',
        queryset=Sensor.objects.all(),
        source='sensor',
    )
    reading = serializers.FloatField(
        source='value',
        allow_null=True,
        required=False,
    )

    reading_time = serializers.DateTimeField(
        source='measured_at',
        required=False,
    )
    status = serializers.ChoiceField(
        choices=ReadingStatuses,
    )

    class Meta:
        model = SensorReading
        fields = ['name', 'reading', 'reading_time', 'status']
        # fields = ['name', 'reading', 'reading_time']


class SensorReadingListSerializer(serializers.ListSerializer):
    child = SensorReadingSerializer()

    def create(self, validated_data):
        """
        Создает объекты SensorReading в БД. Игнорирует данные сенсоров
        с атрибутом is_enabled == False
        """
        logger.error('=============== in serializer create')
        measured_at = timezone.now()
        # sensors = (Sensor
        #            .objects
        #            .filter(slug__in={i['sensor'] for i in validated_data})
        #            .in_bulk(field_name='slug'))

        readings = []
        errors = []
        logger.error(f'{validated_data=}')
        for reading_data in validated_data:
            # slug = reading_data['sensor']
            # sensor: Sensor = sensors.get(slug)
            # if sensor is None:
            #     errors.append(f'Не найден сенсор {slug}')
            # elif sensor.is_enabled:
            if reading_data['status'] == SensorReadingSerializer.ReadingStatuses.NOT_FOUND:
                sensor_name = reading_data['sensor'].name
                logger.error(f'Рабочий центр {sensor_name} не найден: '
                             f'{reading_data}')
                continue
            interval = WorkingInterval.objects.check_interval(
                sensor=reading_data['sensor'],
                value=reading_data['value'],
                # on_date=measured_at
                on_date=reading_data['measured_at']
            )
            if reading_data['value'] is None:
                continue
            reading_data.pop('status')
            reading_data['sensor'] = reading_data['sensor']
            reading_data['measured_at'] = reading_data['measured_at']
            reading_data['working_interval'] = interval
            readings.append(SensorReading(**reading_data))

        if errors:
            raise ValidationError(errors)

        return SensorReading.objects.bulk_create(readings)

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)


class StatusReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusReason
        fields = ['reason']


class StatusWithReasonsSerializer(serializers.RelatedField):
    def to_representation(self, status):
        return {
            'name': status.name,
            'reasons': [
                {'group': r.group, 'reason': r.reason}
                for r in status.reasons.all()
            ]
        }

    def to_internal_value(self, data):
        super().to_internal_value(data)


class WorkingIntervalCommentSerializer(serializers.ModelSerializer):

    sensor = serializers.SlugRelatedField(read_only=True, slug_field='name')
    status = StatusWithReasonsSerializer(read_only=True)

    class Meta:
        model = WorkingInterval
        fields = ['id',
                  'started_at',
                  'finished_at',
                  'sensor',
                  'status',
                  'comment']
        read_only_fields = ['id',
                            'started_at',
                            'finished_at',
                            'sensor',
                            'status']


class SensorSerializer(serializers.ModelSerializer):

    status = serializers.SerializerMethodField()

    class Meta:
        model = Sensor
        fields = ['id',
                  'name',
                  'slug',
                  'description',
                  'status']
        read_only_fields = fields

    def get_status(self, obj):
        last_reading = obj.readings.latest('measured_at')
        last_interval = obj.working_intervals.latest('started_at')
        if last_reading.measured_at > last_interval.started_at:
            if last_reading.value > 0:
                return SensorStatus.SensorStatuses.WORK.value
            else:
                return last_interval.status.status_type
        return 'N/A'


class WorkingIntervalSerializer(serializers.ModelSerializer):

    # start = serializers.DateTimeField(
    #     format='%Y-%m-%dT%H:%M', source='started_at')
    # end = serializers.DateTimeField(
    #     format='%Y-%m-%dT%H:%M', source='finished_at')
    start = serializers.SerializerMethodField()
    end = serializers.SerializerMethodField()
    status = serializers.SlugRelatedField(
        read_only=True, slug_field='status_type')
    duration = serializers.SerializerMethodField()

    class Meta:
        model = WorkingInterval
        fields = ['start',
                  'end',
                  'status',
                  'duration']
        read_only_fields = fields

    @staticmethod
    def datetime_from_interval(
            obj_datetime: timezone.datetime,
            query_datetime: str,
            func: Callable,
            is_string: bool = True
    ) -> timezone.datetime | str:
        result = func(
            timezone.datetime(
                obj_datetime.year,
                obj_datetime.month,
                obj_datetime.day,
                obj_datetime.hour,
                obj_datetime.minute,
                tzinfo=obj_datetime.tzinfo
            ).astimezone(tz=timezone.get_current_timezone()),
            timezone.datetime.strptime(
                query_datetime,
                '%Y-%m-%dT%H:%M'
            ).replace(tzinfo=timezone.get_current_timezone())
        )
        if is_string:
            return result.strftime('%Y-%m-%dT%H:%M:00%z')
        return result

    def get_start(self, obj, is_string=True):
        return self.datetime_from_interval(
            obj.started_at,
            self.context['request'].query_params.get('from_datetime'),
            max,
            is_string
        )

    def get_end(self, obj, is_string=True):
        return self.datetime_from_interval(
            obj.finished_at,
            self.context['request'].query_params.get('to_datetime'),
            min,
            is_string
        )

    def get_duration(self, obj):
        # Длительность в минутах
        return int(
            (
                self.get_end(obj, is_string=False)
                - self.get_start(obj, is_string=False)
            ).total_seconds() / 60)


class WorkingIntervalMachineSerializer(serializers.Serializer):

    sensor_slug = serializers.CharField(read_only=True, source='slug')
    intervals = WorkingIntervalSerializer(
        many=True, read_only=True, source='filtered_intervals')

    class Meta:
        model = Sensor
        fields = ['sensor_slug', 'intervals']
