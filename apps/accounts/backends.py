from django.contrib.auth.backends import BaseBackend

from apps.core.db.scope import db_scope

from .models import User, normalize_login


class ScopedBackend(BaseBackend):
    """Reads users through the narrowest scope that row-level security allows."""

    def authenticate(self, request, identifier=None, password=None, **kwargs):
        if identifier is None or password is None:
            return None
        login = normalize_login(identifier)
        with db_scope(lookup_email=login):
            user = User.objects.filter(email=login).first()
        if user is None:
            # Spend the same hashing time, so timing does not reveal who has an account.
            User().set_password(password)
            return None
        # check_password may rehash and save, which needs the user's own scope.
        with db_scope(user_id=user.pk):
            valid = user.check_password(password)
        return user if valid and user.is_active else None

    def get_user(self, user_id):
        with db_scope(user_id=user_id):
            user = User.objects.filter(pk=user_id).first()
        return user if user is not None and user.is_active else None
