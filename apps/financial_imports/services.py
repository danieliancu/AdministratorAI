from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from apps.audit.services import record_tenant_event
from apps.core import filestore
from apps.core.db.scope import current_scope
from apps.core.numbers import BadValue

from .models import ImportBatch, ImportRow
from .parsing import ImportFileError, read_table
from .specs import SPECS, Context, RowDuplicate, RowInvalid, fold


def map_headers(spec, headers):
    """Find each expected column among the file's headers. Missing required ones are fatal."""
    available = {}
    for header in headers:
        if header:
            available.setdefault(fold(header), header)
    mapping = {}
    for column in spec.columns:
        for name in (column.label, *column.aliases):
            if fold(name) in available:
                mapping[column.key] = available[fold(name)]
                break
    missing = [c.label for c in spec.columns if c.required and c.key not in mapping]
    if missing:
        raise ImportFileError(
            "Lipsesc coloanele obligatorii: " + ", ".join(missing) + ". Descarcă modelul de fișier."
        )
    return mapping


def read_values(spec, mapping, raw):
    values, errors = {}, []
    for column in spec.columns:
        cell = raw.get(mapping[column.key]) if column.key in mapping else None
        if cell is None or str(cell).strip() == "":
            if column.required:
                errors.append(f"Lipsește valoarea pentru {column.label}.")
            continue
        try:
            values[column.key] = column.parse(cell)
        except BadValue as exc:
            errors.append(f"{column.label}: {exc}")
    return values, errors


def _classify(spec, mapping, raw, context):
    values, errors = read_values(spec, mapping, raw)
    if errors:
        return ImportRow.Status.INVALID, errors, values, None
    try:
        key = spec.check(values, context)
    except RowInvalid as exc:
        return ImportRow.Status.INVALID, [str(exc)], values, None
    except RowDuplicate as exc:
        return ImportRow.Status.DUPLICATE, [str(exc)], values, None
    return ImportRow.Status.VALID, [], values, key


def _refresh_counts(batch):
    counts = dict(
        ImportRow.objects.filter(batch=batch)
        .order_by()
        .values_list("status")
        .annotate(n=Count("pk"))
    )
    batch.valid_rows = counts.get(ImportRow.Status.VALID, 0)
    batch.invalid_rows = counts.get(ImportRow.Status.INVALID, 0)
    batch.duplicate_rows = counts.get(ImportRow.Status.DUPLICATE, 0)
    batch.imported_rows = counts.get(ImportRow.Status.IMPORTED, 0)
    batch.failed_rows = counts.get(ImportRow.Status.FAILED, 0)
    batch.total_rows = sum(counts.values())


def create_batch(kind, name, content, *, user_id):
    """Read a file into a preview. Nothing reaches the financial tables yet."""
    spec = SPECS[kind]
    headers, rows = read_table(name, content)
    mapping = map_headers(spec, headers)
    tenant_id = current_scope().tenant_id
    key, checksum = filestore.put(tenant_id, content)

    existing = ImportBatch.objects.filter(kind=kind, sha256=checksum).exclude(
        status=ImportBatch.Status.DISCARDED
    )
    if existing.exists():
        return existing.get(), False
    try:
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                tenant_id=tenant_id,
                kind=kind,
                original_name=name[:255],
                file_key=key,
                sha256=checksum,
                size=len(content),
                headers=headers,
                created_by_id=user_id,
            )
            context = Context(previewing=True)
            records = []
            for number, raw in rows:
                status, errors, _values, _key = _classify(spec, mapping, raw, context)
                records.append(
                    ImportRow(
                        tenant_id=tenant_id,
                        batch=batch,
                        number=number,
                        raw=raw,
                        status=status,
                        errors=errors,
                    )
                )
            ImportRow.objects.bulk_create(records, batch_size=500)
            _refresh_counts(batch)
            batch.save()
    except IntegrityError:
        # The same file uploaded at the same moment: the first one stands.
        return existing.get(), False
    record_tenant_event(
        "import.previewed",
        actor_user_id=user_id,
        metadata={"batch_id": str(batch.pk), "kind": kind, "rows": batch.total_rows},
    )
    return batch, True


def commit_batch(batch_id, *, user_id):
    """Create the records of the valid rows, each on its own, so one failure stays one row."""
    batch = ImportBatch.objects.select_for_update(of=("self",)).get(pk=batch_id)
    if batch.status != ImportBatch.Status.PREVIEW:
        return batch
    spec = SPECS[batch.kind]
    mapping = map_headers(spec, batch.headers)
    context = Context(previewing=False)
    for row in ImportRow.objects.filter(batch=batch, status=ImportRow.Status.VALID):
        # Checked again: the data may have changed since the preview.
        status, errors, values, key = _classify(spec, mapping, row.raw, context)
        target_id = None
        if status == ImportRow.Status.VALID:
            try:
                with transaction.atomic():
                    target_id = spec.create(values, key=key, batch=batch, user_id=user_id)
                status = ImportRow.Status.IMPORTED
            except RowInvalid as exc:
                status, errors = ImportRow.Status.FAILED, [str(exc)]
            except IntegrityError:
                status, errors = ImportRow.Status.DUPLICATE, ["Înregistrarea există deja."]
            except (DatabaseError, ValidationError):
                status, errors = ImportRow.Status.FAILED, ["Rândul nu a putut fi salvat."]
        row.status, row.errors, row.target_id = status, errors, target_id
        row.save(update_fields=["status", "errors", "target_id"])
    _refresh_counts(batch)
    batch.status = ImportBatch.Status.COMMITTED
    batch.finished_at = timezone.now()
    batch.save()
    record_tenant_event(
        "import.committed",
        actor_user_id=user_id,
        metadata={
            "batch_id": str(batch.pk),
            "kind": batch.kind,
            "imported": batch.imported_rows,
            "invalid": batch.invalid_rows,
            "duplicate": batch.duplicate_rows,
            "failed": batch.failed_rows,
        },
    )
    return batch


def discard_batch(batch_id, *, user_id):
    batch = ImportBatch.objects.select_for_update(of=("self",)).get(pk=batch_id)
    if batch.status == ImportBatch.Status.PREVIEW:
        batch.status = ImportBatch.Status.DISCARDED
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])
        record_tenant_event(
            "import.discarded", actor_user_id=user_id, metadata={"batch_id": str(batch.pk)}
        )
    return batch
