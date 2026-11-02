from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

FEATURES = [
    (
        "Vânzări și profit estimat",
        ["Vânzări pe perioade", "Profit estimat", "Tendințe și comparații"],
    ),
    ("Produse rentabile", ["Top produse", "Produse cu vânzări mici", "Marjă estimată"]),
    ("Stocuri și aprovizionare", ["Nivel stocuri", "Produse de reînnoit", "Alerte stoc redus"]),
    ("Plăți și obligații viitoare", ["Calendar fiscal", "Notificări și alerte", "Termene limită"]),
    (
        "Asistent AI în limbaj obișnuit",
        ["Întrebări în limbaj simplu", "Explicații clare", "Recomandări personalizate"],
    ),
    (
        "Rapoarte clare",
        ["Rapoarte transparente", "Ușor de descărcat", "Gata de trimis contabilului"],
    ),
]

AUDIENCES = [
    ("Magazine independente", "Alimentare, băcănii, magazine mixte"),
    ("Microîntreprinderi", "Servicii, comerț, producție mică"),
    ("Ateliere", "Croitorie, tâmplărie, producție artizanală"),
    ("Saloane", "Coafură, înfrumusețare, îngrijire personală"),
    ("Cafenele", "Cafenele, bistrouri, restaurante mici"),
]


def landing(request):
    return render(
        request,
        "landing.html",
        {
            "features": FEATURES,
            "audiences": AUDIENCES,
            "price_text": settings.AAI_LANDING_PRICE_TEXT,
        },
    )


def healthz(request):
    return JsonResponse({"status": "ok"})


def readyz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
