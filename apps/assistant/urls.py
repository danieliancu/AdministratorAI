from django.urls import path

from . import views

urlpatterns = [
    path("asistent/", views.chat, name="assistant"),
    path("asistent/istoric/stergere/", views.clear_history, name="assistant-clear"),
    path("asistent/mesaje/<uuid:pk>/", views.message_status, name="assistant-message"),
]
