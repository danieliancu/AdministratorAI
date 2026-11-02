"""Polite HTTP for official sources: timeouts, size limits, and bounded retries only."""

import logging
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60
MAX_RESPONSE_BYTES = 30 * 1024 * 1024
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SourceError(Exception):
    pass


class SourceAccessDenied(SourceError):
    """The source refuses this client. This is not worked around: a person must decide."""


def fetch(url, *, method="GET", data=None, headers=None, max_attempts=3, sleep=time.sleep):
    request_headers = {"User-Agent": settings.AAI_LEGAL_USER_AGENT, **(headers or {})}
    last_error = None
    for attempt in range(max_attempts):
        request = urllib.request.Request(  # noqa: S310
            url, data=data, headers=request_headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise SourceError(f"Response over {MAX_RESPONSE_BYTES} bytes")
                return body, response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SourceAccessDenied(f"HTTP {exc.code}") from exc
            if exc.code not in RETRYABLE_STATUS:
                raise SourceError(f"HTTP {exc.code}") from exc
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = type(exc).__name__
        if attempt + 1 < max_attempts:
            sleep(2**attempt)
    raise SourceError(last_error or "Request failed")
