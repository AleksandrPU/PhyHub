from datetime import datetime

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from sensors.models import Sensor, SensorReading, StatusReason, WorkingInterval


class SensorReadingSerializer(serializers.ModelSerializer):
    sensor = serializers.SlugField()

    class Meta:
        model = SensorReading
        fields = ['sensor', 'value', 'measured_at']
        read_only_fields = ['measured_at']


class SensorReadingListSerializer(serializers.ListSerializer):
    child = SensorReadingSerializer()

    def create(self, validated_data):
        """
        Создает объекты SensorReading в БД. Игнорирует данные сенсоров
        с атрибутом is_enabled == False
        """
        measured_at = timezone.now()
        sensors = (Sensor
                   .objects
                   .filter(slug__in={i['sensor'] for i in validated_data})
                   .in_bulk(field_name='slug'))

        readings = []
        errors = []
        for reading_data in validated_data:
            slug = reading_data['sensor']
            sensor: Sensor = sensors.get(slug)
            if sensor is None:
                errors.append(f'Не найден сенсор {slug}')
            elif sensor.is_enabled:
                interval = WorkingInterval.objects.check_interval(
                    sensor=sensor,
                    value=reading_data['value'],
                    on_date=measured_at
                )
                reading_data['sensor'] = sensor
                reading_data['measured_at'] = measured_at
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

    class Meta:
        model = Sensor
        fields = '__all__'


# class WorkingIntervalFilteredSerializer(serializers.ListSerializer):
#
#     def to_representation(self, data):
#         request = self.context.get('request')
#         from_datetime = datetime.strptime(
#             request.query_params.get('from_datetime'),
#             '%Y-%m-%dT%H:%M'
#         ).replace(tzinfo=timezone.get_current_timezone())
#         to_datetime = datetime.strptime(
#             request.query_params.get('to_datetime'),
#             '%Y-%m-%dT%H:%M'
#         ).replace(tzinfo=timezone.get_current_timezone())
#
#         data = data.filter(finished_at__gte=from_datetime,
#                            started_at__lte=to_datetime)
#         return super(WorkingIntervalFilteredSerializer, self).to_representation(data)


class WorkingIntervalSerializer(serializers.ModelSerializer):

    start = serializers.DateTimeField(
        format='%Y-%m-%dT%H:%M', source='started_at')
    end = serializers.DateTimeField(
        format='%Y-%m-%dT%H:%M', source='finished_at')
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
        # list_serializer_class = WorkingIntervalFilteredSerializer

    def get_duration(self, obj):
        # Длительность в минутах
        return (
            datetime(
                year=obj.finished_at.year, month=obj.finished_at.month, day=obj.finished_at.day, hour=obj.finished_at.hour, minute=obj.finished_at.minute)
            - datetime(
                year=obj.started_at.year, month=obj.started_at.month, day=obj.started_at.day, hour=obj.started_at.hour, minute=obj.started_at.minute)
            ).total_seconds() / 60


class WorkingIntervalMachineSerializer(serializers.Serializer):

    sensor_slug = serializers.CharField(read_only=True, source='slug')
    intervals = WorkingIntervalSerializer(many=True, read_only=True, source='filtered_intervals')

    class Meta:
        model = Sensor
        fields = ['sensor_slug', 'intervals']
