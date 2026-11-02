# Legal source registry

**Not implemented.** Ingestion is Milestone 3. No legal data is stored, and the application gives no legal information.

## Findings so far (November 2026)

These come from reading the public pages. Nothing has been called.

**Portal Legislativ**, documented at https://legislatie.just.ro/serviciulweblegislatie.htm

- SOAP at `http://legislatie.just.ro/apiws`, with methods `GetToken` and `Search`.
- Search parameters: `tokenKey`, `NumarPagina`, `RezultatePagina`, optional `SearchAn`, `SearchNumar`, `SearchTitlu`. The example also shows an unexplained `SearchText`.
- Result fields: `DataVigoare`, `Emitent`, `Numar`, `Publicatie`, `Text`, `TipAct`, `Titlu`.
- **Not documented:** a WSDL, token lifetime, rate limits, terms of use or licensing, errors, page numbering, date formats, or whether `Text` is complete.
- The documented endpoint is plain HTTP.

**Open question:** the reuse terms are unknown, so a legal review is needed before commercial use.
