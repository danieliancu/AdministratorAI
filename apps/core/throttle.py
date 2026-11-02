import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)


class Throttled(Exception):
    pass


def hit(bucket, key, *, limit, window):
    """Count one attempt. Fails closed: without Redis there is no brute-force protection."""
    digest = hashlib.sha256(str(key).encode()).hexdigest()
    cache_key = f"throttle:{bucket}:{digest}"
    try:
        cache.add(cache_key, 0, window)
        count = cache.incr(cache_key)
    except Exception as exc:
        logger.error("Throttle backend unavailable: %s", type(exc).__name__)
        raise Throttled from exc
    if count > limit:
        raise Throttled
