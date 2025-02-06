from django.urls import path

from .views import (
    SensorViewSet, list_sensor_readings, WorkingIntervalMachineViewSet)

urlpatterns = [
    path('sensors/<str:sensor_slug>/intervals/',
         WorkingIntervalMachineViewSet.as_view({'get': 'retrieve'}),
         name='working_interval_by_machine_list'),

    path('sensors/',
         SensorViewSet.as_view({'get': 'list'}),
         name='sensors_list'),

    path('list_readings/',
         list_sensor_readings,
         name='list_sensor_readings'),
]
