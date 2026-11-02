from .base import *  # noqa: F403
from .base import env

# Used only by the one-shot migrate container, the single holder of owner credentials.
AAI_DB_ROLE_GUARD = False

# Lets the development catalog command install the fake provider.
AAI_ALLOW_FAKE_AI = env("AAI_ALLOW_FAKE_AI", "") == "true"
