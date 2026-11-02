from datetime import timedelta
from decimal import Decimal as D

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.management.commands.seed_dev import ADMIN_LOGIN, TENANT_KEY
from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.expenses.models import Expense, ExpenseCategory, RecurringExpense
from apps.inventory.models import Product
from apps.inventory.services import record_movement
from apps.reports.figures import add_months
from apps.sales.models import Customer, Invoice, SalesCategory, SaleTransaction
from apps.sales.services import record_payment
from apps.tenants.models import Tenant

DEMO_PREFIX = "DEMO-"


class Command(BaseCommand):
    help = "Fill the fictional development tenant with fictional records. Development only."

    def handle(self, *args, **options):
        if not (settings.DEBUG and settings.AAI_ALLOW_DEV_SEED):
            raise CommandError("seed_finance_dev is refused outside the development settings.")
        with db_scope(lookup_email=ADMIN_LOGIN):
            admin = User.objects.get(email=ADMIN_LOGIN)
        with db_scope(user_id=admin.pk):
            tenant = Tenant.objects.get(created_by=admin, idempotency_key=TENANT_KEY)
        with db_scope(tenant_id=tenant.pk, user_id=admin.pk):
            if Invoice.objects.filter(number__startswith=DEMO_PREFIX).exists():
                self.stdout.write("Fictional records already exist.")
                return
            self._fill(tenant, admin)
        self.stdout.write(f"Fictional records added to {tenant.name}")

    def _fill(self, tenant, admin):
        today = timezone.localdate()
        month = today.replace(day=1)
        services = SalesCategory.objects.create(tenant=tenant, name="Servicii (fictiv)")
        goods = SalesCategory.objects.create(tenant=tenant, name="Marfă (fictiv)")
        rent = ExpenseCategory.objects.create(tenant=tenant, name="Chirie (fictiv)")
        supplies = ExpenseCategory.objects.create(tenant=tenant, name="Consumabile (fictiv)")
        customers = [
            Customer.objects.create(tenant=tenant, name=f"Client Fictiv {letter} SRL")
            for letter in "ABC"
        ]
        for back in range(5, -1, -1):
            start = add_months(month, -back)
            base = D(1800 + (5 - back) * 260)
            number = 5 - back + 1
            invoice = Invoice.objects.create(
                tenant=tenant,
                number=f"{DEMO_PREFIX}{number:03d}",
                customer=customers[back % 3],
                category=services,
                issue_date=start + timedelta(days=4),
                due_date=start + timedelta(days=34),
                net=base,
                vat=(base * D("0.19")).quantize(D("0.01")),
                gross=base + (base * D("0.19")).quantize(D("0.01")),
                notes="Date fictive pentru dezvoltare.",
                created_by=admin,
            )
            # The two newest invoices stay open, so overdue and outstanding figures appear.
            if back >= 2 and invoice.issue_date <= today:
                record_payment(
                    invoice.pk,
                    date=min(start + timedelta(days=20), today),
                    amount=invoice.gross,
                    user_id=admin.pk,
                )
            SaleTransaction.objects.create(
                tenant=tenant,
                date=min(start + timedelta(days=14), today),
                description="Total casă de marcat (fictiv)",
                category=goods,
                net=D("500.00") + back * 40,
                vat=D("0.00"),
                gross=D("500.00") + back * 40,
                created_by=admin,
            )
            Expense.objects.create(
                tenant=tenant,
                date=start + timedelta(days=1),
                supplier="Proprietar Fictiv",
                document_number=f"CH-{number}",
                category=rent,
                net=D("900.00"),
                vat=D("0.00"),
                gross=D("900.00"),
                paid_date=start + timedelta(days=2) if back else None,
                created_by=admin,
            )
            Expense.objects.create(
                tenant=tenant,
                date=min(start + timedelta(days=9), today),
                supplier="Furnizor Fictiv SA",
                document_number=f"FF-{number}",
                category=supplies,
                net=D("300.00") + back * 25,
                vat=D("57.00") + back * D("4.75"),
                gross=D("357.00") + back * D("29.75"),
                paid_date=min(start + timedelta(days=12), today),
                created_by=admin,
            )
        RecurringExpense.objects.create(
            tenant=tenant,
            description="Abonament software (fictiv)",
            supplier="Furnizor Fictiv SA",
            category=supplies,
            net=D("100.00"),
            vat=D("19.00"),
            gross=D("119.00"),
            day_of_month=5,
            first_month=month,
        )
        for sku, name, threshold, cost, received, issued in (
            ("FICT-1", "Produs fictiv 1", "10", "12.50", "40", "34"),
            ("FICT-2", "Produs fictiv 2", "5", "80.00", "20", "4"),
            ("FICT-3", "Produs fictiv 3", None, None, "7", "0"),
        ):
            product = Product.objects.create(
                tenant=tenant,
                sku=sku,
                name=name,
                reorder_threshold=D(threshold) if threshold else None,
                unit_cost=D(cost) if cost else None,
                created_by=admin,
            )
            record_movement(
                product.pk,
                date=month,
                kind="receipt",
                quantity=D(received),
                reference="NIR fictiv",
                user_id=admin.pk,
            )
            if D(issued):
                record_movement(
                    product.pk,
                    date=today,
                    kind="issue",
                    quantity=D(issued),
                    reference="Aviz fictiv",
                    user_id=admin.pk,
                )
