import logging

import requests
from celery import shared_task

from django.conf import settings
from rest_framework import status, request

from change.services import sensor_readings_create
from sensors.models import Sensor

logger = logging.getLogger(__name__)


@shared_task
def get_sensors_value(sensors: list[str] = None):
    if sensors is None:
        sensors = Sensor.objects.filter(is_enabled=True).values_list(
            'slug', flat=True)

    response = None
    try:
        response = requests.get(
            f'{settings.SENSOR_HOST}',
            params={'work_centers': ','.join(sensors)},
        )
        if not status.is_success(response.status_code):
            # TODO райзить ошибку?
            logger.error(
                f'Ошибка при запросе данных {response.request.url}:\n'
                f'{response.status_code} - {response.text}')
    except ConnectionError as error:
        logger.error(f'Ошибка соединения с {settings.SENSOR_HOST}:\n'
                     f'{error}')
    else:
        return sensor_readings_create(response.json())
