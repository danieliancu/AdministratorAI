from datetime import date

import pytest

from apps.legal_knowledge.connectors import anaf_rss
from apps.legal_knowledge.connectors.http import SourceAccessDenied, SourceError, fetch
from apps.legal_knowledge.connectors.portal_legislativ import (
    ENDPOINT,
    PortalLegislativClient,
    build_search,
    parse_search,
)
from apps.legal_knowledge.parsing import (
    find_references,
    fold_for_search,
    parse_legal_text,
    text_checksum,
)

SOAP_RESULT = """<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
<SearchResponse xmlns="http://tempuri.org/"><SearchResult
 xmlns:a="http://schemas.datacontract.org/2004/07/FreeWebService">
<a:Legi><a:DataVigoare>2016-01-01</a:DataVigoare><a:Emitent>Parlamentul</a:Emitent>
<a:LinkHtml>http://legislatie.just.ro/Public/DetaliiDocument/1</a:LinkHtml>
<a:Numar>7</a:Numar><a:Publicatie>Monitorul Oficial</a:Publicatie>
<a:Text> LEGE nr. 7 din 8 septembrie 2015 privind un exemplu </a:Text>
<a:TipAct>LEGE</a:TipAct>
<a:Titlu>   LEGE nr. 7 din 8 septembrie 2015  PUBLICAT ÎN: MONITORUL OFICIAL nr. 688
 din 10 septembrie 2015 </a:Titlu></a:Legi>
</SearchResult></SearchResponse></s:Body></s:Envelope>""".encode()


class TestParsing:
    def test_splits_along_articles_and_paragraphs(self):
        parsed = parse_legal_text(
            "Preambul lung al actului.\nArticolul 1\n(1) Primul alineat.\n(2) Al doilea.\n"
            "Articolul 2\nFără alineate."
        )
        assert [p.label for p in parsed.provisions] == ["Preambul", "Articolul 1", "Articolul 2"]
        assert parsed.is_complete
        chunk = parsed.provisions[1].chunks[0]
        assert "Primul alineat" in chunk.text
        assert "Al doilea" in chunk.text

    def test_an_inline_reference_does_not_start_an_article(self):
        parsed = parse_legal_text(
            "Articolul 1\nDispozițiile prevăzute la Articolul 5 din lege se aplică.\nArticolul 2\nX"
        )
        assert [p.label for p in parsed.provisions] == ["Articolul 1", "Articolul 2"]

    def test_real_portal_layout_with_plus_separators(self):
        parsed = parse_legal_text(
            "DECRET\n + \n Articolul UNIC    Doamna se numește în funcția de test.  ------"
        )
        assert [p.label for p in parsed.provisions] == ["Preambul", "Articolul UNIC"]

    def test_long_article_is_split_at_paragraph_boundaries(self):
        paragraphs = "\n".join(f"({i}) " + "cuvânt " * 150 for i in range(1, 6))
        parsed = parse_legal_text(f"Articolul 1\n{paragraphs}")
        chunks = parsed.provisions[0].chunks
        assert len(chunks) >= 2
        assert all(len(c.text) <= 1800 for c in chunks)
        assert all(c.text.lstrip().startswith("(") or c.text.startswith("Articolul")
                   for c in chunks)

    def test_stub_without_a_body_is_incomplete(self):
        # The shape Portal Legislativ really returned for the Fiscal Code.
        parsed = parse_legal_text(
            "LEGE nr. 227 din 8 septembrie 2015 privind Codul fiscal EMITENT PARLAMENTUL "
            "Publicat în MONITORUL OFICIAL nr. 688 din 10 septembrie 2015 COD FISCAL 08/09/2015"
        )
        assert not parsed.is_complete
        assert parsed.provisions == []

    def test_guidance_without_articles_is_kept_whole(self):
        parsed = parse_legal_text("Comunicat ANAF. " * 30)
        assert parsed.is_complete
        assert [p.label for p in parsed.provisions] == ["Text integral"]

    @pytest.mark.parametrize(
        "variant",
        ["taxa pe valoarea adăugată", "taxa pe valoarea adaugata", "TAXA PE VALOAREA ADĂUGATĂ"],
    )
    def test_diacritics_and_case_are_folded(self, variant):
        assert fold_for_search(variant) == "taxa pe valoarea adaugata"

    def test_old_cedilla_letters_match_the_correct_ones(self):
        assert fold_for_search("Ordonanţa şi") == fold_for_search("Ordonanța și")

    def test_checksum_ignores_layout_but_not_content(self):
        assert text_checksum("cota  de\n10%") == text_checksum("cota de 10%")
        assert text_checksum("cota de 10%") != text_checksum("cota de 16%")

    def test_references_are_found(self):
        found = find_references(
            "conform Legea nr. 227/2015 și Ordonanța de urgență a Guvernului nr. 16/2022, "
            "precum și Legea nr. 227/2015"
        )
        assert found == [
            "Legea nr. 227/2015",
            "Ordonanța de urgență a Guvernului nr. 16/2022",
        ]


class TestPortalLegislativ:
    def test_parses_all_fields(self):
        [act] = parse_search(SOAP_RESULT)
        assert (act.act_type, act.number, act.year) == ("LEGE", "7", 2015)
        assert act.valid_from == date(2016, 1, 1)
        assert act.issuer == "Parlamentul"
        assert act.link.endswith("/1")
        assert "MONITORUL OFICIAL nr. 688" in act.publication

    def test_search_escapes_user_input(self):
        body = build_search("t<o>k", page=0, page_size=1, title="a&b<c>").decode()
        assert "a&amp;b&lt;c&gt;" in body
        assert "t&lt;o&gt;k" in body

    def test_hostile_xml_is_refused(self):
        bomb = b"""<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><a>&lol;</a>"""
        with pytest.raises(Exception, match="(?i)entity|forbidden"):
            parse_search(bomb)

    def test_a_soap_fault_is_an_error(self):
        fault = b"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>
        <s:Fault><faultcode>x</faultcode></s:Fault></s:Body></s:Envelope>"""
        with pytest.raises(SourceError):
            parse_search(fault)

    def test_uses_the_address_from_the_wsdl_and_refreshes_the_token_once(self):
        calls = []
        token = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b'<GetTokenResponse xmlns="http://tempuri.org/"><GetTokenResult>T</GetTokenResult>'
            b"</GetTokenResponse></s:Body></s:Envelope>"
        )
        fault = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b"<s:Fault/></s:Body></s:Envelope>"
        )
        replies = [token, fault, token, SOAP_RESULT]

        def fetcher(url, **kwargs):
            calls.append((url, kwargs["headers"]["SOAPAction"]))
            return replies.pop(0), "text/xml"

        acts = PortalLegislativClient(fetcher=fetcher).search(year=2015, number=7)
        assert len(acts) == 1
        assert len(calls) == 4
        assert all(url == ENDPOINT for url, _ in calls)

    def test_a_persistent_fault_fails_instead_of_looping(self):
        token = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b'<GetTokenResponse xmlns="http://tempuri.org/"><GetTokenResult>T</GetTokenResult>'
            b"</GetTokenResponse></s:Body></s:Envelope>"
        )
        fault = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            b"<s:Fault/></s:Body></s:Envelope>"
        )
        calls = []

        def fetcher(url, **kwargs):
            calls.append(kwargs["headers"]["SOAPAction"])
            return (token if "GetToken" in kwargs["headers"]["SOAPAction"] else fault), "text/xml"

        with pytest.raises(SourceError):
            PortalLegislativClient(fetcher=fetcher).search(year=2015)
        assert len(calls) == 4


class TestAnafRss:
    FEED = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
    <item><title>Comunicat  de test</title>
    <link>https://static.anaf.ro/static/3/Anaf/com 1010 30oct2026.pdf</link>
    <pubDate>Fri, 30 Oct 2026 00:00:00 +0200</pubDate></item>
    <item><title>Link străin</title><link>https://rau.example/x.pdf</link></item>
    <item><title>Fără https</title><link>http://static.anaf.ro/x.pdf</link></item>
    </channel></rss>""".encode()

    def test_parses_items_and_encodes_spaces(self):
        [item] = anaf_rss.parse_feed(self.FEED)
        assert item.title == "Comunicat de test"
        assert item.link == "https://static.anaf.ro/static/3/Anaf/com%201010%2030oct2026.pdf"
        assert item.published_on == date(2026, 10, 30)

    def test_links_outside_official_hosts_are_ignored(self):
        links = [i.link for i in anaf_rss.parse_feed(self.FEED)]
        assert not any("rau.example" in link for link in links)
        assert len(links) == 1


class FakeHTTPError:
    pass


def _http_error(code):
    import urllib.error

    return urllib.error.HTTPError("http://x.test", code, "err", {}, None)


class TestHttp:
    def test_retries_are_bounded_with_backoff(self, monkeypatch):
        attempts, delays = [], []

        def fail(request, timeout):
            attempts.append(1)
            raise _http_error(503)

        monkeypatch.setattr("urllib.request.urlopen", fail)
        with pytest.raises(SourceError):
            fetch("http://x.test", max_attempts=3, sleep=delays.append)
        assert len(attempts) == 3
        assert delays == [1, 2]

    @pytest.mark.parametrize("code", [401, 403])
    def test_access_denied_is_never_retried_or_worked_around(self, monkeypatch, code):
        attempts = []

        def deny(request, timeout):
            attempts.append(request.headers)
            raise _http_error(code)

        monkeypatch.setattr("urllib.request.urlopen", deny)
        with pytest.raises(SourceAccessDenied):
            fetch("http://x.test", max_attempts=3, sleep=lambda s: None)
        assert len(attempts) == 1

    def test_identifies_itself_honestly(self, monkeypatch):
        seen = []

        class Response:
            headers = {"Content-Type": "text/plain"}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                return b"ok"

        def capture(request, timeout):
            seen.append(request.get_header("User-agent"))
            return Response()

        monkeypatch.setattr("urllib.request.urlopen", capture)
        fetch("http://x.test")
        assert "AdministratorAI" in seen[0]
        assert "Mozilla" not in seen[0]
