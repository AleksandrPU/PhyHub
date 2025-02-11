from enum import StrEnum

from rest_framework import serializers

from sensors.models import SensorReading, Sensor


class ReadingSerializer(serializers.ModelSerializer):

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
