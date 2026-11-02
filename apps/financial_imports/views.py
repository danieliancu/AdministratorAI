from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.exports import csv_response
from apps.core.listing import page_of
from apps.core.throttle import Throttled, hit
from apps.tenants import roles
from apps.tenants.roles import requires

from . import services
from .forms import UploadForm
from .models import ImportBatch, ImportRow
from .parsing import MAX_FILE_BYTES, ImportFileError
from .specs import SPECS

UPLOADS_PER_HOUR = 60


def _guides():
    return [
        {
            "kind": kind,
            "label": ImportBatch.Kind(kind).label,
            "required": [c.label for c in spec.columns if c.required],
            "optional": [c.label for c in spec.columns if not c.required],
        }
        for kind, spec in SPECS.items()
    ]


@requires(roles.VIEW_FINANCE)
def import_list(request, tenant_id):
    can_import = request.tenant_access.can(roles.IMPORT_FINANCE)
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not can_import:
            raise Http404
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                hit("import-upload", tenant_id, limit=UPLOADS_PER_HOUR, window=3600)
                if upload.size > MAX_FILE_BYTES:
                    raise ImportFileError("Fișierul depășește limita de 5 MB.")
                batch, created = services.create_batch(
                    form.cleaned_data["kind"],
                    upload.name,
                    upload.read(),
                    user_id=request.user.pk,
                )
            except ImportFileError as exc:
                form.add_error("file", str(exc))
            except Throttled:
                form.add_error("file", "Prea multe importuri într-o oră. Încearcă mai târziu.")
            else:
                if not created:
                    messages.success(request, "Acest fișier a fost deja încărcat.")
                return redirect("tenant:import-detail", tenant_id=tenant_id, pk=batch.pk)
    return render(
        request,
        "imports/import_list.html",
        {
            "form": form,
            "can_import": can_import,
            "page": page_of(request, ImportBatch.objects.order_by("-created_at")),
            "guides": _guides(),
        },
    )


@requires(roles.VIEW_FINANCE)
def import_detail(request, tenant_id, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    state = request.GET.get("stare", "")
    rows = ImportRow.objects.filter(batch=batch).order_by("number")
    if state in ImportRow.Status.values:
        rows = rows.filter(status=state)
    page = page_of(request, rows)
    # jsonb sorts its keys, so the file's own column order comes from the batch.
    for row in page:
        row.cells = [row.raw.get(header) for header in batch.headers if header]
    return render(
        request,
        "imports/import_detail.html",
        {
            "batch": batch,
            "page": page,
            "state": state,
            "states": ImportRow.Status.choices,
            "is_preview": batch.status == ImportBatch.Status.PREVIEW,
            "can_import": request.tenant_access.can(roles.IMPORT_FINANCE),
            "rejected": batch.invalid_rows + batch.failed_rows,
            "active_section": "import-list",
        },
    )


@require_POST
@requires(roles.IMPORT_FINANCE)
def import_commit(request, tenant_id, pk):
    get_object_or_404(ImportBatch, pk=pk)
    batch = services.commit_batch(pk, user_id=request.user.pk)
    messages.success(request, f"Rânduri importate: {batch.imported_rows}.")
    return redirect("tenant:import-detail", tenant_id=tenant_id, pk=pk)


@require_POST
@requires(roles.IMPORT_FINANCE)
def import_discard(request, tenant_id, pk):
    get_object_or_404(ImportBatch, pk=pk)
    services.discard_batch(pk, user_id=request.user.pk)
    messages.success(request, "Ai renunțat la acest import. Nu a fost salvată nicio înregistrare.")
    return redirect("tenant:import-list", tenant_id=tenant_id)


@requires(roles.VIEW_FINANCE)
def import_rejected(request, tenant_id, pk):
    """The rows to fix, in the file's own columns, ready to correct and upload again."""
    batch = get_object_or_404(ImportBatch, pk=pk)
    rows = ImportRow.objects.filter(
        batch=batch, status__in=[ImportRow.Status.INVALID, ImportRow.Status.FAILED]
    ).order_by("number")
    headers = [header for header in batch.headers if header]
    return csv_response(
        f"respinse-{batch.pk}.csv",
        [*headers, "Eroare"],
        ([*(row.raw.get(h) for h in headers), " ".join(row.errors)] for row in rows),
    )


@requires(roles.VIEW_FINANCE)
def import_template(request, tenant_id, kind):
    spec = SPECS.get(kind)
    if spec is None:
        raise Http404
    return csv_response(f"model-{kind}.csv", [column.label for column in spec.columns], [])
