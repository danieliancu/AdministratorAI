# Legal source registry

The live registry is `/platform/legislatie/surse/`. **Every source starts disabled**, because reuse terms are unverified. Enabling one is a superadmin decision with a required reason, recorded in the audit log. Commands run by hand work regardless, in small bounded imports.

| Source | State | What it provides today |
|---|---|---|
| Portal Legislativ | Connector works, tested live | Text as first published, for many acts |
| ANAF | Connector works, tested live | Press releases, stored but not searchable |
| Manual import | Works | Whatever an operator imports, with declared provenance |
| Monitorul Oficial, Ministry of Finance, ONRC, EUR-Lex | Not built | Nothing |

## Portal Legislativ: findings from real calls, November 2026

Documented at https://legislatie.just.ro/serviciulweblegislatie.htm.

**Differs from or goes beyond the documentation:**

- The working endpoint is `http://legislatie.just.ro/apiws/FreeWebService.svc/SOAP`, from a WSDL at `…/FreeWebService.svc?wsdl`. Plain `/FreeWebService.svc` answers 404.
- Results include a `LinkHtml` field that the page does not list.
- Year and number match across act types, and two separate documents can share type, number, year and issuer.

**Limits that matter:**

- **The Fiscal Code is not available.** For Legea 227/2015 the service returned only a header, with no articles. It is stored as `incomplete` and is never used as evidence. Other acts may behave the same way.
- **No version history or consolidated text** in any result seen. All Portal text is therefore marked as first published, with a warning that later amendments may be missing.
- **Automated clients get 403** on the public detail pages and on `robots.txt`. This is respected: there is no browser impersonation.
- **Still undocumented:** rate limits, terms of use, token lifetime, page numbering. The endpoint is plain HTTP, so responses cannot be authenticated in transit.

## ANAF

- Channel `comunicate` (https://www.anaf.ro/ANAFRSS/?canal=comunicate) is current.
- Channel `legislatie` answers, but its newest items are from 2016, so it is not used.
- Only `https` links on official ANAF hosts are followed.

## What this means for the product

**The fiscal knowledge base is not usable yet.** Answering "what applies in 2024?" needs consolidated text, which no connector provides. Options, all needing a decision:

1. Import consolidated texts by hand with `legal_import_document`, from official PDFs. This works today and needs someone to choose and check the documents.
2. Ask the Ministry of Justice about programmatic access to consolidated forms.
3. License a consolidated legislation provider.

A legal review of reuse terms is needed before commercial use, whichever is chosen.
