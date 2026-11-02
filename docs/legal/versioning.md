# Legal versioning

Implemented in `apps/legal_knowledge`. A test or a database trigger backs each rule below.

## Two time lines

- **In law:** `valid_from` and `valid_to` on `LegalApplicability`. They answer "what applied on this date?"
- **In the system:** `recorded_at` and `retired_at`. They answer "what did we know at that moment?"

`retrieve(question, on_date=…, known_at=…)` filters on both, so an audit can reconstruct what the application could have used for an earlier answer.

## What never changes

- Documents, acts, provisions, provision versions, chunks and embeddings are immutable, even for the owner role.
- On a version, only `review_status` and `reviewed_at` can change.
- An applicability row can only be retired once. A correction adds a new row.

## How a version enters

- The same bytes from a source change nothing.
- A new text under one act becomes a new version, and the time line is re-derived. A version arriving late fits into place.
- **Portal Legislativ:** an act is identified by its source document id too. Identical type, number, year and issuer do not make two documents versions of one act. Real data showed this: treating two rectifications as versions invented an end date.
- **Manual import:** an operator declares that documents are versions of one act, by leaving out a document id.
- A text with no date gets no applicability, so it cannot be retrieved. It waits for review.
- An incomplete text gets no provisions, so it can never be cited.

## Authority and review

Sources are labelled as legislation, consolidated text, ANAF guidance, procedure, interpretation or draft. Drafts are never retrieved. Law outranks guidance.

Automatic ingestion never marks a text as verified. Only a superadmin's audited decision does, and a rejected text stops being retrieved.

## Known limitations

- **Amending laws quote other laws.** In Legea 296/2023, "Articolul 18^3" is a quoted article of the Fiscal Code, but the parser files it under the amending law. A citation would name the wrong act. The citation step of Milestone 6 must handle this, and until then such results need a specialist's eye.
- **Applicability is per act version**, not per article. Transitional provisions and partial entry into force are not modelled.
- **`DataVigoare`** is taken as the start date. It has not been confirmed that this field always means entry into force.
- References between acts are text matches, stored as `refers_to` only. Amendments and repeals are not detected.
- Retrieval has no separate reranking step beyond rank fusion and authority weighting.
- Semantic search was run only with the fake generator, which matches shared letters and words, not meaning. Its quality is unknown until a real embedding model is used.
- No regression set exists. The 200 specialist-reviewed questions need a fiscal specialist.
- `LegalImpactAssessment` does not exist yet, because there are no tax rules to assess (Milestone 4).
