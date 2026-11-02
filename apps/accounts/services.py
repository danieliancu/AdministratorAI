import uuid

from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from apps.audit.services import record_security_event
from apps.core.db.scope import db_scope

from .models import User, normalize_login

VERIFY_SALT = "accounts.verify-email"
VERIFY_MAX_AGE = 60 * 60 * 24 * 3


def _send_verification(request, user_id, email):
    token = signing.dumps(str(user_id), salt=VERIFY_SALT)
    link = request.build_absolute_uri(reverse("public:verify-email", args=[token]))
    send_mail(
        "Confirmă adresa de email",
        f"Confirmă adresa ta pentru Administrator AI:\n\n{link}\n\nLinkul expiră în 3 zile.",
        None,
        [email],
    )


def register_user(request, *, email, password, full_name=""):
    """Answers identically whether or not the address already has an account."""
    email = normalize_login(email)
    user_id = uuid.uuid4()
    try:
        with db_scope(user_id=user_id):
            User.objects.create_user(
                id=user_id, email=email, password=password, full_name=full_name
            )
    except IntegrityError:
        send_mail(
            "Cont existent",
            "Cineva a încercat să creeze un cont cu această adresă, care are deja unul.\n"
            "Dacă ai fost tu, folosește resetarea parolei.",
            None,
            [email],
        )
        return
    _send_verification(request, user_id, email)


def verify_email(token):
    try:
        user_id = uuid.UUID(signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE))
    except (signing.BadSignature, ValueError):
        return False
    with db_scope(user_id=user_id):
        return (
            User.objects.filter(pk=user_id, email_verified_at__isnull=True).update(
                email_verified_at=timezone.now()
            )
            > 0
            or User.objects.filter(pk=user_id).exists()
        )


def request_password_reset(request, email):
    email = normalize_login(email)
    with db_scope(lookup_email=email):
        user = User.objects.filter(email=email, is_active=True).first()
    if user is None or "@" not in email:
        return
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(
        reverse("public:password-reset-confirm", args=[user.pk, token])
    )
    send_mail(
        "Resetează parola",
        f"Alege o parolă nouă pentru Administrator AI:\n\n{link}",
        None,
        [email],
    )


def load_user_for_reset(user_id, token):
    with db_scope(user_id=user_id):
        user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not default_token_generator.check_token(user, token):
        return None
    return user


def set_new_password(user, password):
    user.set_password(password)
    with db_scope(user_id=user.pk):
        user.save(update_fields=["password"])
        record_security_event("password.reset", actor_user_id=user.pk)
