from django.http import HttpResponse
from django.urls import path

urlpatterns = [path("nescopat/", lambda request: HttpResponse("nu trebuie servit"))]
