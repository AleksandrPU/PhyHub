import logging

from api.serializers import SensorReadingListSerializer, \
    SensorReadingSerializer
from sensors.models import SensorReading

logger = logging.getLogger(__name__)


def sensor_readings_create(response: dict):
    logger.error(f'{response=}')
    logger.error(f'{type(response)=}')
    serializer = SensorReadingListSerializer(data=response)
    serializer.is_valid(raise_exception=True)
    logger.error('------------------------\n'
                 f'{serializer.validated_data=}\n'
                 '------------------------')
    # readings = []
    # for reading in serializer.validated_data:
    #     if reading['status'] == SensorReadingSerializer.ReadingStatuses.OK:
    #         reading.pop('status')
    #         SensorReading(**reading).save()
    #         # readings.append(SensorReading(**reading))
    # logger.info(f'{readings=}')
    # SensorReading.objects.bulk_create(readings)
    readings = serializer.save()
    return readings
