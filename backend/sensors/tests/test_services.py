from django.test import TestCase
import responses

from ..services import SensorReadingsService
from ..models import SensorEndpoint


class TestSensorReadingsServices(TestCase):
    API_URL = 'http://test.tst/sensors/'
    API_RESPONSE = {
        "sensor_1": {"count": 2295941},
        "sensor_2": {"count": 0},
        "sensor_3": {"count": None},
        "sensor_4": {"count": 1234567890}
    }

    @classmethod
    def setUpTestData(cls):
        endpoint = SensorEndpoint(
            name='Test endpoint',
            url=cls.API_URL,
            periodicity=1,
            is_enabled=True,
        )
        endpoint.save()
        cls.endpoint = endpoint

    @responses.activate
    def test_get_endpoint_response_on_200(self):
        """Метод get_endpoint_response() возвращает валидный словарь."""
        responses.add(
            responses.Response(
                method='GET',
                url=self.API_URL,
                json=self.API_RESPONSE
            )
        )
        service = SensorReadingsService(1)
        self.assertEqual(self.API_RESPONSE,
                         service.get_endpoint_response())
