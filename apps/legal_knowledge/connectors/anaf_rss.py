"""ANAF RSS discovery.

Observed in November 2026: the "comunicate" channel is current. The "legislatie" channel
answers normally, but its newest items date from 2016, so it is not a usable signal of
new legislation and is not treated as one.
"""

from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit, urlunsplit

from defusedxml import ElementTree

from .http import fetch

COMUNICATE_URL = "https://www.anaf.ro/ANAFRSS/?canal=comunicate"
ALLOWED_DOCUMENT_HOSTS = {"static.anaf.ro", "www.anaf.ro", "anaf.ro"}


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    published_on: date | None


def _safe_url(value):
    """Item links contain raw spaces, and only official ANAF hosts are followed."""
    parts = urlsplit(value.strip())
    if parts.scheme != "https" or parts.hostname not in ALLOWED_DOCUMENT_HOSTS:
        return None
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path), parts.query, ""))


def _parse_date(value):
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def parse_feed(body):
    items = []
    for node in ElementTree.fromstring(body).findall("./channel/item"):
        link = _safe_url(node.findtext("link") or "")
        if link is None:
            continue
        items.append(
            FeedItem(
                title=" ".join((node.findtext("title") or "").split()),
                link=link,
                published_on=_parse_date(node.findtext("pubDate")),
            )
        )
    return items


def fetch_feed(url=COMUNICATE_URL, fetcher=fetch, max_attempts=3):
    body, _ = fetcher(url, max_attempts=max_attempts)
    return parse_feed(body)
