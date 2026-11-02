"""Portal Legislativ SOAP connector.

Observed in November 2026, beyond what the service's page documents:
- the working address and a WSDL are at /apiws/FreeWebService.svc, with the /SOAP endpoint;
- results carry an undocumented LinkHtml field;
- number and year match across act types, so one search returns unrelated acts;
- some acts, including the Fiscal Code (Legea 227/2015), return only a header without the
  body, and no result carries consolidated forms or version history.
The public detail pages answered 403 to this client. That is respected, not worked around.
"""

import re
from dataclasses import dataclass
from datetime import date
from xml.sax.saxutils import escape

from defusedxml import ElementTree

from .http import SourceError, fetch

ENDPOINT = "http://legislatie.just.ro/apiws/FreeWebService.svc/SOAP"
ACTION = "http://tempuri.org/IFreeWebService/"
NS = {
    "s": "http://schemas.xmlsoap.org/soap/envelope/",
    "t": "http://tempuri.org/",
    "a": "http://schemas.datacontract.org/2004/07/FreeWebService",
}
_YEAR_IN_TITLE = re.compile(r"\bdin\s+\d{1,2}\s+\w+\s+(\d{4})\b")
_PUBLICATION = re.compile(r"MONITORUL OFICIAL\s+nr\.\s*[\w.\s-]{1,40}?din\s+\d{1,2}\s+\w+\s+\d{4}")


@dataclass(frozen=True)
class PortalAct:
    act_type: str
    number: str
    issuer: str
    title: str
    text: str
    link: str
    valid_from: date | None
    publication: str
    year: int | None
    raw: bytes


def _envelope(body):
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        f"{body}</s:Body></s:Envelope>"
    ).encode()


def _optional(tag, value):
    if value is None or value == "":
        return f'<a:{tag} i:nil="true"/>'
    return f"<a:{tag}>{escape(str(value))}</a:{tag}>"


def build_search(token, *, page, page_size, year=None, number=None, title=None):
    return _envelope(
        '<Search xmlns="http://tempuri.org/">'
        '<SearchModel xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService"'
        ' xmlns:i="http://www.w3.org/2001/XMLSchema-instance">'
        f"<a:NumarPagina>{int(page)}</a:NumarPagina>"
        f"<a:RezultatePagina>{int(page_size)}</a:RezultatePagina>"
        f"{_optional('SearchAn', year)}{_optional('SearchNumar', number)}"
        f"{_optional('SearchText', None)}{_optional('SearchTitlu', title)}"
        f"</SearchModel><tokenKey>{escape(token)}</tokenKey></Search>"
    )


def _text(node, tag):
    found = node.find(f"a:{tag}", NS)
    return (found.text or "") if found is not None else ""


def _parse_date(value):
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def parse_search(body):
    root = ElementTree.fromstring(body)
    if root.find(".//s:Fault", NS) is not None:
        raise SourceError("SOAP fault")
    acts = []
    for node in root.findall(".//a:Legi", NS):
        title = " ".join(_text(node, "Titlu").split())
        text = _text(node, "Text")
        year_match = _YEAR_IN_TITLE.search(title)
        publication = _PUBLICATION.search(title)
        acts.append(
            PortalAct(
                act_type=_text(node, "TipAct").strip(),
                number=_text(node, "Numar").strip(),
                issuer=_text(node, "Emitent").strip(),
                title=title,
                text=text,
                link=_text(node, "LinkHtml").strip(),
                valid_from=_parse_date(_text(node, "DataVigoare")),
                publication=" ".join(publication.group(0).split()) if publication else "",
                year=int(year_match.group(1)) if year_match else None,
                raw=ElementTree.tostring(node),
            )
        )
    return acts


class PortalLegislativClient:
    def __init__(self, fetcher=fetch, max_attempts=3):
        self._fetch = fetcher
        self._max_attempts = max_attempts
        self._token = None

    def _call(self, action, body):
        response, _ = self._fetch(
            ENDPOINT,
            method="POST",
            data=body,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{ACTION}{action}"',
            },
            max_attempts=self._max_attempts,
        )
        return response

    def _get_token(self):
        body = _envelope('<GetToken xmlns="http://tempuri.org/"/>')
        root = ElementTree.fromstring(self._call("GetToken", body))
        result = root.find(".//t:GetTokenResult", NS)
        if result is None or not result.text:
            raise SourceError("No token returned")
        return result.text

    def search(self, *, page=0, page_size=10, year=None, number=None, title=None):
        if self._token is None:
            self._token = self._get_token()
        arguments = {"page": page, "page_size": page_size, "year": year, "number": number,
                     "title": title}
        try:
            return parse_search(self._call("Search", build_search(self._token, **arguments)))
        except SourceError:
            # The token lifetime is undocumented. A single fresh attempt, never a loop.
            self._token = self._get_token()
            return parse_search(self._call("Search", build_search(self._token, **arguments)))
