from datetime import timedelta

from django import template

register = template.Library()


@register.filter
def add_class(value, arg):
    try:
        value.field.widget.attrs['class'] = arg
    except AttributeError:
        return value
    return value


@register.simple_tag
def widget_with_attrs(field, **attrs):
    field.field.widget.attrs.update(attrs)
    field.field.widget.attrs['type'] = 'datetime-local'
    return field


@register.filter
def duration(value):
    if not isinstance(value, timedelta):
        return value
    seconds = int(value.total_seconds())
    hours = seconds // 3600
    seconds -= hours * 3600
    minutes = seconds // 60
    seconds -= minutes * 60
    return f'{hours}:{minutes:02}:{seconds:02}'
