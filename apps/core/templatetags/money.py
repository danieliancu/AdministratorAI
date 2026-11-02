from decimal import Decimal

from django import template

register = template.Library()


def _grouped(value, places):
    # Python groups with "," and "."; Romanian notation is the reverse.
    text = f"{Decimal(value):,.{places}f}"
    return text.translate(str.maketrans({",": ".", ".": ","}))


@register.filter
def lei(value):
    if value is None or value == "":
        return "—"
    return f"{_grouped(value, 2)} lei"


@register.filter
def quantity(value):
    if value is None or value == "":
        return "—"
    return _grouped(value, 3).rstrip("0").rstrip(",")


@register.simple_tag(takes_context=True)
def query_without(context, *names):
    """The current query string minus some parameters, for pagination and export links."""
    query = context["request"].GET.copy()
    for name in names:
        query.pop(name, None)
    return query.urlencode()
