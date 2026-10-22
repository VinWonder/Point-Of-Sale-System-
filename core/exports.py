import csv

from django.http import HttpResponse
from django.utils import timezone


def csv_response(filename, header, rows):
    """Stream rows as a CSV download. Adds a BOM so Excel opens it as UTF-8."""
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}-{stamp}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response
