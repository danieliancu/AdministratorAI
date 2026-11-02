class PlatformRouter:
    """The platform and legal aliases are reached explicitly, and never run migrations."""

    def allow_migrate(self, db, app_label, **hints):
        return db not in ("platform", "legal")
