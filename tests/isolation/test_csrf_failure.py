"""A stale form is refused, and the refusal page gives a working way forward."""

import re

import pytest
from django.urls import reverse

from tests.factories import make_user

pytestmark = pytest.mark.django_db


def _signed_in_strict_client(client):
    user = make_user()
    response = client.post(
        reverse("public:login"), {"identifier": user.email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 302
    client.handler.enforce_csrf_checks = True
    return user


def test_stale_token_does_not_log_out_and_offers_a_fresh_form(client):
    _signed_in_strict_client(client)
    client.get(reverse("public:landing"))
    logout = reverse("account:logout")

    refused = client.post(logout, {"csrfmiddlewaretoken": "x" * 64})

    assert refused.status_code == 403
    content = refused.content.decode()
    assert "Pagina a expirat" in content
    assert "Help" not in content
    assert client.get(reverse("account:tenant-list")).status_code in (200, 302)
    assert "_auth_user_id" in client.session

    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', content).group(1)
    assert client.post(logout, {"csrfmiddlewaretoken": token}).status_code == 302
    assert "_auth_user_id" not in client.session


def test_anonymous_visitor_is_sent_to_login(client):
    client.handler.enforce_csrf_checks = True
    refused = client.post(reverse("public:login"), {"identifier": "x", "password": "y"})
    assert refused.status_code == 403
    assert reverse("public:login") in refused.content.decode()
