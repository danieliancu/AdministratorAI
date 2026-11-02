import csv
import io
from decimal import Decimal

from django.http import HttpResponse
from django.utils.http import content_disposition_header

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Stop a spreadsheet from running text as a formula. Real numbers keep their sign."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value).replace(".", ",")
    if isinstance(value, int | float):
        return str(value).replace(".", ",")
    text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def csv_response(filename, headers, rows):
    """Semicolons and decimal commas, as Excel expects under Romanian regional settings."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([safe_cell(header) for header in headers])
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(True, filename)
    return response
