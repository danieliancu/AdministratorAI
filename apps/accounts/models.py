import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


def normalize_login(value):
    return value.strip().lower()


class UserManager(BaseUserManager):
    def create_user(self, email, password, **fields):
        user = self.model(email=normalize_login(email), **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Registration validates this as an email. The development seed account alone
    # holds the plain identifier "admin" here.
    email = models.CharField(max_length=254, unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []


class PlatformGrant(models.Model):
    """Platform staff access. The application role can only read its own row."""

    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", "Superadmin"
        SUPPORT = "support", "Suport"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="platform_grant")
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.user_id} / {self.role}"
