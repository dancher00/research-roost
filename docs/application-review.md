# Application preparation and verification

The canonical full process is `phd_search/resources/workflows/apply.md`. An application is preparing until substantive drafting, grounding and review are complete. There is no universal document list, CV page count or proposal requirement.

## Required local artifacts

Each packet freezes `profile.snapshot.json`, `opportunity.snapshot.json` and `posting.txt`. Original digests are checked so editing a frozen snapshot cannot silently support a new claim. Requirements and claims are separately bound into the final review. Use a new variant after a material source/profile change.

`requirements.json` records the original requirements quote and per-document constraints (`required`, language, min_words, max_words, max_pages, require_pdf). The CLI checks whitespace-delimited word count; portals may count characters/words differently, so inspect the actual field counter before submission. Use exact programme limits, not stock defaults. An unverified requirement source remains `needs_review`.

Requirements on a separate official admissions page can use `external_evidence` entries (workspace file, SHA-256, verbatim quote and original URL). The same validator checks those sources for assessments, claims and requirements; a changed file fails verification. Required inactive documents and missing required attachments fail. `requirements.referees.minimum` and `received_by_submission` can encode actual source requirements; confirmed permission is required for counted referees.

Register original transcripts, diplomas, writing samples, language tests or other supporting files with `application attach APP_ID --file PATH --kind transcript` (or the actual kind). Their original digests are preserved; final review hashes must include them. They cannot be appended to a submitted packet. At submission, `--files` can explicitly identify the reviewed relative files actually sent; defaults follow require_pdf settings and registered attachments. The manifest distinguishes submitted files from local support/source files and freezes external evidence separately. Compilation logs and incidental generated files are not described as submitted attachments.

Register exact factual spans in `claims.json`; support candidate facts with profile JSON pointers and programme/institution facts with exact archived source quotes. The validator checks that spans, pointers, excerpts and digests exist. The reviewer must still determine semantic support, completeness, authorship, contribution, publication status, appropriate strength and whether cited work says what the prose claims. Setting a boolean alone is not substantive review.

## Final review record

After revision, populate `review.json` using this pattern:

```json
{
  "schema_version": 1,
  "reviewer": "Agent/person name; same-agent critical pass where applicable",
  "verdict": "approved",
  "profile_sha256": "ORIGINAL PACKET PROFILE DIGEST",
  "evidence_sha256": "ORIGINAL RAW POSTING DIGEST",
  "document_hashes": {"cv.md": "SHA256", "motivation.md": "SHA256"},
  "support_hashes": {"requirements.json": "SHA256", "claims.json": "SHA256"},
  "claims_semantically_checked": true,
  "requirements_checked": true,
  "source_integrity_checked": true,
  "visual_pdf_checked": false,
  "findings": [],
  "limitations": ["State actual review limitations here"]
}
```

Include each required compiled PDF as `rendered/name.pdf` in document_hashes, and set visual_pdf_checked true only after rendered-page inspection. `python3 -c`/a small script using `hashlib.sha256(Path(...).read_bytes()).hexdigest()` computes digests; verification output lists the document hashes it actually observed. Any later document/claims/requirements edit invalidates this review.

Findings should record severity (`critical`, `major`, `minor`), location, issue, source/reason, concrete revision and resolved state. Unresolved critical/major findings fail verification. Separate drafting and critical phases; the same agent's second pass is not independent validation.

## Rendering and PDF

`application render APP_ID` makes editable `.tex` and print `.html`; `--pdf` chooses an available XeLaTeX, LuaLaTeX or Tectonic engine (or `--engine` explicitly). TeX shell escape is disabled; Tectonic uses untrusted mode. A real build manifest binds Markdown, TeX and PDF digests. If the source or PDF later changes, rebuild it. Installed font coverage still limits which scripts can render; choose an appropriate supplied/system font in a custom template and check actual glyphs.

Optional `pypdf` or system pdfinfo/pdftotext checks pages and text extraction. Missing compiler/extractor is `unavailable`/`unverified`, never a passing PDF. `tools/verify_pdf.py` and `tools/verify_layout.py` provide additional page/text/layout diagnostics; use their `--help` for precise flags. Automatic geometry checks do not replace visual inspection.

Check clipping, orphans, page breaks, contact text, language/script coverage, reading order, citations and actual institutional limits on the final rendered pages. Do not claim visual inspection from source code or PDF metadata alone.

## Lifecycle

`preparing → drafted → submitted → assessment/interview/waitlisted/offer/rejected`, followed by `accepted/declined/withdrawn/expired` where valid. The CLI rejects invalid transitions. Accepted/rejected/withdrawn/declined/expired records remain historical; a new application cycle is a new opportunity/variant.

Marking drafted/submitted reruns verification. `fail` blocks the transition; `needs_review` can be explicitly acknowledged with `--allow-unknown`, preserving that decision in the event. It never bypasses failed grounding, placeholders, stale sources, a missing review or required PDF failure.

Submission must reflect a user-confirmed actual submission and creates an immutable submitted archive. The tracker never performs a remote submission. References and scheduled interview/assessment events are separate records. Interview prep uses the exact submitted documents. Profile learning after submission does not rewrite that history.
