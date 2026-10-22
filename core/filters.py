from datetime import datetime, timedelta

from django.utils import timezone


PRESETS = {
    'today': 'Today',
    'yesterday': 'Yesterday',
    'week': 'This week',
    'month': 'This month',
    'last_month': 'Last month',
}


def _parse(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def date_range_from_request(request, default='today'):
    """
    Resolve ?range=<preset> or ?start=YYYY-MM-DD&end=YYYY-MM-DD into
    (start_date, end_date, preset_key). Both dates are inclusive.
    """
    today = timezone.localdate()
    start, end = _parse(request.GET.get('start')), _parse(request.GET.get('end'))
    preset = request.GET.get('range', '' if (start or end) else default)

    if preset == 'today':
        start = end = today
    elif preset == 'yesterday':
        start = end = today - timedelta(days=1)
    elif preset == 'week':
        start, end = today - timedelta(days=today.weekday()), today
    elif preset == 'month':
        start, end = today.replace(day=1), today
    elif preset == 'last_month':
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif preset == 'all':
        start = end = None
    else:
        preset = ''
        start = start or today - timedelta(days=30)
        end = end or today
        if start > end:
            start, end = end, start
    return start, end, preset


def filter_by_date(queryset, start, end, field='created_at'):
    if start:
        queryset = queryset.filter(**{f'{field}__date__gte': start})
    if end:
        queryset = queryset.filter(**{f'{field}__date__lte': end})
    return queryset
