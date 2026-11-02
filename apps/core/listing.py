from django.core.paginator import Paginator

PAGE_SIZE = 25


def page_of(request, queryset, size=PAGE_SIZE):
    return Paginator(queryset, size).get_page(request.GET.get("pagina"))


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"
