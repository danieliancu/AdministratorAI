from django.core.management.base import BaseCommand

from apps.legal_knowledge.connectors.portal_legislativ import PortalLegislativClient
from apps.legal_knowledge.sync import ingest_portal_act


class Command(BaseCommand):
    help = (
        "Fetch specific acts from Portal Legislativ, for a deliberate and small import. "
        "Run it in the worker service, the only holder of the legal role."
    )

    def add_arguments(self, parser):
        parser.add_argument("--year", required=True)
        parser.add_argument("--number", required=True)
        parser.add_argument("--title", default=None)
        parser.add_argument("--limit", type=int, default=3)

    def handle(self, *args, year, number, title, limit, **options):
        acts = PortalLegislativClient().search(
            page=0, page_size=min(limit, 20), year=year, number=number, title=title
        )
        self.stdout.write(f"Found {len(acts)}")
        for act in acts:
            result = ingest_portal_act(act)
            status = result.document.text_status
            version = "new version" if result.version else "no usable version"
            self.stdout.write(f"- {act.title[:90]} | text={status} | {version}")
