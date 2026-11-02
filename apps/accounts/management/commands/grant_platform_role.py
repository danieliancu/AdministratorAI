import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.accounts.models import PlatformGrant, User, normalize_login
from apps.core.db.scope import db_scope


class Command(BaseCommand):
    help = "Grant platform staff access. Needs owner credentials: run it in the migrate service."

    def add_arguments(self, parser):
        parser.add_argument("login")
        parser.add_argument("role", choices=PlatformGrant.Role.values)
        parser.add_argument("--reason", required=True)

    def handle(self, *args, login, role, reason, **options):
        login = normalize_login(login)
        with db_scope(lookup_email=login):
            user = User.objects.filter(email=login).first()
            if user is None:
                raise CommandError(f"No account with login {login}")
            PlatformGrant.objects.update_or_create(user=user, defaults={"role": role})
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT platform.record_event("
                    "NULL, 'platform.role.granted', NULL, %s, %s::jsonb)",
                    [reason, json.dumps({"user_id": str(user.pk), "role": role})],
                )
        self.stdout.write(f"Granted {role} to {login}")
