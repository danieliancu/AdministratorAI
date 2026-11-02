"""Turn an uploaded CSV or Excel file into rows of original cells, within firm limits."""

import csv
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 40
MAX_CELL_CHARS = 500
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class ImportFileError(Exception):
    """Carries a message written for the person using the page."""


def _decode(content):
    # Romanian Excel exports are often Windows-1250; UTF-8 is tried first because it can fail.
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("Fișierul nu are o codare de text recunoscută. Salvează-l ca UTF-8.")


def _delimiter(first_line):
    counts = {delimiter: first_line.count(delimiter) for delimiter in (";", ",", "\t")}
    return max(counts, key=counts.get)


def _read_csv(content):
    text = _decode(content)
    if "\x00" in text:
        raise ImportFileError("Fișierul nu este un CSV valid.")
    first_line = text.split("\n", 1)[0]
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(first_line))
    try:
        yield from reader
    except csv.Error as exc:
        raise ImportFileError("Fișierul nu este un CSV valid.") from exc


def _cell(value):
    """Keep what the spreadsheet knows: a number stays a number, so it is never misread."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _read_xlsx(content):
    from openpyxl import load_workbook

    buffer = io.BytesIO(content)
    try:
        with zipfile.ZipFile(buffer) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ImportFileError("Fișierul Excel este prea mare după dezarhivare.")
        workbook = load_workbook(buffer, read_only=True, data_only=True)
    except ImportFileError:
        raise
    except Exception as exc:
        raise ImportFileError("Fișierul nu este un Excel .xlsx valid.") from exc
    try:
        for row in workbook.worksheets[0].iter_rows(values_only=True):
            yield [_cell(value) for value in row[:MAX_COLUMNS]]
    finally:
        workbook.close()


def _is_blank(row):
    return all(cell is None or str(cell).strip() == "" for cell in row)


def read_table(name, content):
    """Return (headers, rows), where a row is (line number, {header: original cell})."""
    if not content:
        raise ImportFileError("Fișierul este gol.")
    if len(content) > MAX_FILE_BYTES:
        raise ImportFileError("Fișierul depășește limita de 5 MB.")
    lowered = name.lower()
    if lowered.endswith(".csv"):
        source = _read_csv(content)
    elif lowered.endswith(".xlsx"):
        source = _read_xlsx(content)
    else:
        raise ImportFileError("Sunt acceptate doar fișiere .csv și .xlsx.")

    headers = None
    rows = []
    for number, row in enumerate(source, start=1):
        if _is_blank(row):
            continue
        if headers is None:
            headers = [str(cell).strip() if cell is not None else "" for cell in row[:MAX_COLUMNS]]
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"Fișierul are peste {MAX_ROWS} de rânduri. Împarte-l.")
        cells = {}
        for index, cell in enumerate(row[: len(headers)]):
            if headers[index]:
                if isinstance(cell, str) and len(cell) > MAX_CELL_CHARS:
                    raise ImportFileError(f"Rândul {number} are o celulă prea lungă.")
                cells[headers[index]] = cell
        rows.append((number, cells))
    if headers is None:
        raise ImportFileError("Fișierul nu conține un rând de antet.")
    if not rows:
        raise ImportFileError("Fișierul are antet, dar niciun rând de date.")
    return headers, rows
