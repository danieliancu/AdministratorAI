class PlatformRouter:
    """The platform alias is reached explicitly, and it never runs migrations."""

    def allow_migrate(self, db, app_label, **hints):
        return db != "platform"
