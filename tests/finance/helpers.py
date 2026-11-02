from datetime import date
from decimal import Decimal as D

from apps.core.db.scope import db_scope
from apps.expenses.models import Expense
from apps.inventory.models import Product
from apps.sales.models import Customer, Invoice, SaleTransaction
from tests.factories import make_tenant, make_user


def world(name="Firma"):
    user = make_user()
    return user, make_tenant(user, name)


def scope(user, tenant):
    return db_scope(tenant_id=tenant.pk, user_id=user.pk)


def customer(tenant, name="Client SRL", cui=""):
    return Customer.objects.create(tenant=tenant, name=name, cui=cui)


def invoice(tenant, number="F1", gross="119.00", net="100.00", vat="19.00", **extra):
    defaults = {"issue_date": date(2026, 3, 10)}
    defaults.update(extra)
    who = defaults.pop("customer", None) or customer(tenant, name=f"Client {number}")
    return Invoice.objects.create(
        tenant=tenant,
        number=number,
        customer=who,
        net=D(net),
        vat=D(vat),
        gross=D(gross),
        **defaults,
    )


def sale(tenant, net="50.00", vat="9.50", gross="59.50", on=date(2026, 3, 11), **extra):
    return SaleTransaction.objects.create(
        tenant=tenant,
        date=on,
        description=extra.pop("description", "Casa de marcat"),
        net=D(net),
        vat=D(vat),
        gross=D(gross),
        **extra,
    )


def expense(tenant, net="40.00", vat="7.60", gross="47.60", on=date(2026, 3, 12), **extra):
    return Expense.objects.create(
        tenant=tenant,
        date=on,
        supplier=extra.pop("supplier", "Furnizor SA"),
        net=D(net),
        vat=D(vat),
        gross=D(gross),
        **extra,
    )


def product(tenant, sku="P1", **extra):
    return Product.objects.create(tenant=tenant, sku=sku, name=f"Produs {sku}", **extra)
