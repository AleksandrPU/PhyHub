from datetime import datetime
from datetime import timedelta
from typing import Optional

from django.db import models
from django.db.models import OuterRef, Q
from django.utils import timezone


class Sensor(models.Model):
    """
    Сенсор физической величины.
    """
    name = models.CharField('Полное наименование',
                            max_length=50)
    slug = models.SlugField('Slug',
                            unique=True,
                            max_length=25)
    is_enabled = models.BooleanField('Включен',
                                     default=False)
    description = models.CharField('Описание',
                                   max_length=100,
                                   blank=True)
    default_status = models.ForeignKey('SensorStatus',
                                       on_delete=models.SET_NULL,
                                       blank=True,
                                       null=True,
                                       verbose_name='Статус по умолчанию',
                                       related_name='+')

    class Meta:
        verbose_name = 'Сенсор'
        verbose_name_plural = 'Сенсоры'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_working_status(self, value: float) -> Optional['SensorStatus']:
        """
        :param value: Показание сенсора.
        :return: Статус сенсора в зависимости от value.
        """
        return (self
                .statuses
                .filter(value_from__lte=value,
                        value_to__gt=value)
                .order_by('value_from')
                .last())


class SensorStatusQueryset(models.QuerySet):

    def get_status(self,
                   value: float,
                   duration: timedelta,
                   **kwargs):
        """
        Фильтрует queryset по kwargs, возвращает объект,
        соответствующий параметрам value и duration.
        """
        return (self
                .filter(**kwargs)
                .filter(value_from__lte=value,
                        value_to__gt=value)
                .filter((Q(duration_to__gt=duration)
                         | Q(duration_to__isnull=True)),
                        duration_from__lte=duration)
                .order_by('-value_to')
                .first())


class SensorStatus(models.Model):
    """
    Статус (состояние) сенсора.
    """
    class SensorStatuses(models.TextChoices):
        WORK = 'WORK', 'Работа'
        PAUSE = 'PAUSE', 'Тех. пауза'
        STOP = 'STOP', 'Остановка'
        OFFLINE = 'OFFLINE', 'Отключен'

    name = models.CharField('Название',
                            max_length=50)
    value_from = models.FloatField('Значение с')
    value_to = models.FloatField('Значение до')
    duration_from = models.DurationField('Длительность с',
                                         default=timedelta(0))
    duration_to = models.DurationField('Длительность до',
                                       blank=True,
                                       null=True)
    need_comment = models.BooleanField('Необходим комментарий')
    color = models.CharField('Цвет',
                             max_length=7,
                             help_text='html цвет, например #4285f4')
    sensor = models.ForeignKey(Sensor,
                               related_name='statuses',
                               on_delete=models.CASCADE,
                               verbose_name='Сенсор')

    object = SensorStatusQueryset.as_manager()
    status_type = models.CharField('Тип статуса',
                                   max_length=15,
                                   choices=SensorStatuses.choices)

    class Meta:
        verbose_name = 'Состояние сенсора'
        verbose_name_plural = 'Состояния сенсоров'
        ordering = ['name']

    def __str__(self):
        return f'{self.sensor.slug} - {self.name}'


class StatusReason(models.Model):
    """
    Причина нахождения сенсора в статусе. Выбирается оператором процесса.
    """
    reason = models.CharField('Причина состояния',
                              max_length=100)
    group = models.CharField('Группа',
                             max_length=50,
                             blank=True)
    priority = models.PositiveSmallIntegerField('Приоритет',
                                                default=32767)
    sensor_status = models.ForeignKey(SensorStatus,
                                      related_name='reasons',
                                      on_delete=models.CASCADE,
                                      verbose_name='Состояние сенсора')

    class Meta:
        verbose_name = 'Причина состояния'
        verbose_name_plural = 'Причины состояний'
        ordering = ['group', 'priority', 'reason']

    def __str__(self):
        return self.reason


class WorkingIntervalQueryset(models.QuerySet):

    def check_interval(self,
                       sensor: Sensor,
                       value: float,
                       on_date: datetime):
        """
        Возвращает новый WorkingInterval, если статус не изменился,
        иначе новый.
        :param on_date: Момент времени измерения.
        :param sensor: Сенсор.
        :param value: Новое значение.
        :return: Рабочий интервал.
        """
        # получаем текущий интервал или создаем новый
        interval = (self
                    .filter(sensor=sensor,
                            finished_at__isnull=True)
                    .order_by('started_at')
                    .last())
        # если предыдущих интервалов нет, создаем новый
        if interval is None:
            return self.create(sensor=sensor,
                               started_at=on_date,
                               last_reading_value=value,
                               status=sensor.default_status)

        # определяем предшествующий и текущий статус
        duration = on_date - interval.started_at
        prev_status = (sensor
                       .statuses
                       .get_status(value=interval.last_reading_value,
                                   duration=duration))
        cur_status = (sensor
                      .statuses
                      .get_status(value=value,
                                  duration=duration))

        # если статус не изменился
        if (None in (prev_status, cur_status)
                or prev_status.id == cur_status.id):
            interval.last_reading_value = value
            interval.save()
            return interval

        # если статус изменился, сохраняем интервал и создаем новый
        interval.last_reading_value = value
        interval.status = prev_status
        interval.finished_at = on_date
        interval.save()

        return self.create(sensor=sensor,
                           last_reading_value=value,
                           started_at=on_date)


class WorkingInterval(models.Model):
    """
    Временной интервал, группирующий показания сенсора.
    """

    started_at = models.DateTimeField('С')
    finished_at = models.DateTimeField('До',
                                       blank=True,
                                       null=True)
    last_reading_value = models.FloatField('Крайнее измеренное значение')
    comment = models.CharField('Комментарий',
                               max_length=200,
                               blank=True)
    sensor = models.ForeignKey(Sensor,
                               on_delete=models.CASCADE,
                               related_name='working_intervals',
                               verbose_name='Сенсор')
    status = models.ForeignKey(SensorStatus,
                               on_delete=models.SET_NULL,
                               blank=True,
                               null=True,
                               verbose_name='Статус')

    objects = WorkingIntervalQueryset.as_manager()

    class Meta:
        verbose_name = 'Рабочий интервал'
        verbose_name_plural = 'Рабочие интервалы'
        ordering = ['started_at']

    def __str__(self):
        date_format = "%d.%m.%y %H:%M:%S"
        started_at = self.started_at.strftime(date_format)
        finished_at = (self.finished_at.strftime(date_format)
                       if self.finished_at is not None
                       else 'настоящее время')
        return f'{started_at} - {finished_at}'

    @property
    def duration(self):
        return (self.finished_at or timezone.now()) - self.started_at


class SensorReadingQuerySet(models.QuerySet):

    def filter_latest(self, **kwargs):
        latest_reading = (self
                          .filter(sensor=OuterRef('sensor'))
                          .order_by('-measured_at')
                          .values('pk')[:1])
        return self.filter(pk=latest_reading, **kwargs)


class SensorReading(models.Model):
    """
    Показание сенсора.
    """
    sensor = models.ForeignKey(Sensor,
                               on_delete=models.CASCADE,
                               related_name='readings',
                               verbose_name='Сенсор')
    value = models.FloatField('Значение')
    measured_at = models.DateTimeField('Дата и время измерения',
                                       default=timezone.now)
    working_interval = models.ForeignKey(WorkingInterval,
                                         on_delete=models.CASCADE,
                                         related_name='readings',
                                         verbose_name='Измерения')

    objects = SensorReadingQuerySet().as_manager()

    class Meta:
        verbose_name = 'Измерение'
        verbose_name_plural = 'Измерения'
        ordering = ['measured_at']

    def __str__(self):
        return str(self.value)
