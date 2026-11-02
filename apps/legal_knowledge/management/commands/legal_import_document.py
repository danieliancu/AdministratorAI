from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.legal_knowledge.ingestion import ActIdentity, IncomingDocument, ingest_act
from apps.legal_knowledge.models import Authority, LegalActVersion
from apps.legal_knowledge.sync import extract_pdf_text


class Command(BaseCommand):
    help = (
        "Import one official document, such as a consolidated Fiscal Code, with its provenance. "
        "The operator answers for the source and dates, and the text still awaits review. "
        "Run it in the worker service."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--type", required=True, dest="act_type")
        parser.add_argument("--number", required=True)
        parser.add_argument("--year", required=True, type=int)
        parser.add_argument("--issuer", default="")
        parser.add_argument("--title", required=True)
        parser.add_argument("--official-url", required=True)
        parser.add_argument("--valid-from", required=True, type=date.fromisoformat)
        parser.add_argument("--basis", required=True, help="Where the valid-from date comes from")
        parser.add_argument(
            "--form", required=True, choices=LegalActVersion.TextForm.values
        )
        parser.add_argument("--consolidated-as-of", type=date.fromisoformat)
        parser.add_argument(
            "--authority", default=Authority.LEGISLATION, choices=Authority.values
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        if options["form"] == LegalActVersion.TextForm.CONSOLIDATED and not options[
            "consolidated_as_of"
        ]:
            raise CommandError("A consolidated text needs --consolidated-as-of.")
        content = path.read_bytes()
        if path.suffix.lower() == ".pdf":
            content_type, text = "application/pdf", extract_pdf_text(content)
        else:
            content_type, text = "text/plain", content.decode("utf-8")
        if not text.strip():
            raise CommandError("No text could be extracted. OCR is not available.")
        result = ingest_act(
            IncomingDocument(
                source_key="manual_official",
                url=options["official_url"],
                title=options["title"],
                authority=options["authority"],
                content=content,
                content_type=content_type,
                text=text,
                published_on=options["valid_from"],
            ),
            ActIdentity(
                act_type=options["act_type"],
                number=options["number"],
                year=options["year"],
                issuer=options["issuer"],
            ),
            valid_from=options["valid_from"],
            basis=options["basis"],
            text_form=options["form"],
            consolidated_as_of=options["consolidated_as_of"],
        )
        outcome = "new" if result.created else "unchanged"
        self.stdout.write(
            f"{outcome}: text={result.document.text_status} version={bool(result.version)}"
        )
