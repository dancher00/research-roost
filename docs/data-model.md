# Data model and evidence contracts

The database and private files live under the selected workspace. JSON output is UTF-8, deterministic-key ordered and rejects NaN/Infinity. Source values and unknowns are preserved; a null is not false, zero or an eligibility veto.

## Profile

`profile.json` follows `phd_search/resources/profile.example.json`, schema version 1. Identity, research, education, experience, outputs, skills, languages, preferences and confirmed facts are separate. See [profile.md](profile.md). A profile digest covers the full canonical JSON; any change invalidates assessments bound to an older profile.

## Opportunity and snapshots

`opportunities` stores id, canonical URL, current extracted data, first/last observation and organisation status (`new`, `shortlist`, `dismissed`, `archived`). IDs are deterministic SHA-256 prefixes of the original canonical URL. Only known tracking parameters and fragments are removed; cycle/requisition/query parameters are preserved. Cross-board identity requires an explicit alias/merge. A merge creates a database backup, preserves snapshots/assessments/applications and keeps the selected primary observation active.

Each snapshot records raw SHA-256, immutable raw/cleaned file paths, observed URL, requested URL, observation time, content type, extraction method, cleaned text digest, integrity findings and source. Raw bytes are content addressed; cleaned files also incorporate their own digest, so a different interpretation cannot overwrite another snapshot's text. Manual file import records when it was imported, not proof of a contemporaneous live retrieval. `last_seen`/report `last_verified` indicate local observation, not a certificate of current availability.

Extracted fields include title, institution, country/city, source URL, complete description, deadline, posted date, reference, funding, requirements, supervisors, topics, methods and skills. Generic extraction deliberately leaves non-established values null/empty. `salary_raw` is not interpreted as fully funded. Per-field `provenance` names the source, locator and original quote.

## Source-backed annotations

Annotations are separate from raw extraction and tied to the current snapshot. The `values` object replaces the named top-level fields; preserve other desired values when editing a nested object. An annotation file has this shape:

After a posting changes, its old annotations remain visible as historical
evidence but no longer override current extracted fields in screening, ranking,
reports or calendars. Reverify and import annotations against the new snapshot.

```json
{
  "values": {
    "opportunity_type": "project",
    "requirements": {"reviewed": true, "degree": "master", "languages": [], "other": []},
    "funding": {"status": "fully_funded", "tuition_covered": true, "amount": 2200, "currency": "EUR", "period": "month", "basis": "gross"}
  },
  "evidence": {
    "opportunity_type": {"quote": "EXACT POSTING EXCERPT", "evidence_sha256": "CURRENT RAW SHA256"},
    "requirements": {"quote": "EXACT REQUIREMENTS EXCERPT", "evidence_sha256": "CURRENT RAW SHA256"},
    "funding": {"quote": "EXACT FUNDING EXCERPT", "evidence_sha256": "CURRENT RAW SHA256"}
  }
}
```

The amounts/text above illustrate the schema and are not real funding advice. Quotes must occur in the current cleaned posting; the digest must match. Genuine user-supplied information may instead use `{"basis":"user_confirmed","note":"User confirmed X on DATE from SOURCE"}`. Agents must not mint user confirmations. Separate official sources can be preserved as dossier evidence and synthesised by the agent; do not falsely quote the board as their source.

Opportunity types: `project`, `doctoral_programme`, `studentship`, `doctoral_network`, `scholarship`, `supervisor_led`, `other`. Funding statuses: `fully_funded`, `partial`, `self_funded`, `unknown`. Funding amount/period/currency/gross-net basis, tuition coverage, award/fee eligibility and duration are distinct. Minimum-funding comparisons require matching currency, period and basis; no FX, inflation or tax rates are invented.

Requirements can include degree (`bachelor`, `master`, `doctorate`, `other`), languages (`name`, `cefr`, or `test`/`minimum_score`), allowed/excluded citizenships, exact mobility rule and `other` sourced criteria (`name`, `verdict`, `reason`). Mark `reviewed` only after full source inspection. Unknown/ambiguous equivalence, subscores, validity/reference dates and mobility rules require explicit review, not a guessed pass.

Deadlines store raw text, parsed `value`, timezone and precision. ISO offset timestamps remain exact; dates remain dates. A time lacking its timezone is not converted to midnight UTC. Date-only expiry is conservative through the latest possible end-of-day unless a zone is established; near-cutoff uncertainty remains visible.

## Assessments

Generate an exact template with `assessment packet ID`. It binds opportunity ID, profile SHA-256, raw evidence SHA-256 and a context SHA-256 covering extracted data + annotations. `assessor` and method (`human`/`agent_semantic`) name the judgment source. Each dimension has `score` (null or finite 0–5), reason, posting_quotes, profile_refs (JSON pointers) and optional external_evidence. Scored research/methods/preparation require profile evidence; all scored dimensions require source evidence. External evidence is an archived workspace file + SHA-256 + quote + original URL. Mechanical validation verifies anchors/digests, not entailment or expertise.

The ranker returns eligibility, assessment state (`missing`, `current`, `stale`), coverage, score interval, and a point score only at 100% dimensional coverage. Unknown dimensions span their full possible weighted contribution; the known subtotal is never renamed a complete score. Changes to profile, posting or annotations invalidate older judgments. Ranking and tracker exports recheck archived external evidence files, digests and quotes. Missing or changed evidence makes the assessment stale, clears its usable score/coverage and reports `assessment_issues`. Direct Python callers of `ranking` must pass `root=workspace_path` to verify external evidence; without that context, an externally supported assessment cannot be called current.

## Application packets

`applications` stores the opportunity relation, version/variant, immutable profile/source bindings, document inventory, references, status and events. A preparing packet contains snapshots, posting, briefing, exact requirements, active Markdown documents, `claims.json`, `review.json`, rendered artifacts and verification results. Missing/unfinished prose is explicit.

`claims.json` uses `{"schema_version":1,"coverage_reviewed":true,"claims":[{"file":"motivation.md","text":"Exact factual span in the final document","profile_refs":["/facts/0"],"posting_quotes":[],"external_evidence":[]}]}`. Provide the appropriate support rather than all three kinds. At least one supported factual span must be registered per active document. `coverage_reviewed` attests a semantic audit, not an automatically measured claim-extraction guarantee.

`review.json` requires reviewer, approved verdict, document_hashes, support_hashes for claims/requirements, profile/evidence bindings, semantic/requirements/integrity checks and no unresolved major/critical findings. Required PDFs need build provenance and a visual-review attestation. See [application-review.md](application-review.md). This is a review artifact, not proof of human independence.

Submission creates a separate immutable directory with exact document/support files, rendered versions and a manifest of hashes. Later working edits cannot alter what was submitted. Use a new variant to refresh a materially changed frozen profile/source; interview prep uses the submitted archive.

New submissions also bind the manifest digest in the application record.
Interview preparation verifies the manifest, declared file inventories, all
archived file hashes and the original source/profile bindings before reading
submitted material. Legacy archives without a recorded manifest digest still
undergo inventory, content and identity checks; those checks cannot create a
historical digest anchor retroactively.

## State and exports

All writes use SQLite transactions and atomic file replacement. Database schema version 2 supports distinct edition/session identities at one original URL. Existing schema-1 databases migrate transactionally after a separate SQLite backup; original IDs, snapshots, relationships and archives are preserved. Unknown versions fail rather than overwrite. The profile/source JSON schema remains version 1 with optional additive fields. Opportunities, aliases, snapshots, annotations, assessments, applications, events, dossiers, runs and artifacts have dedicated ownership. Audit events distinguish event date from recording time. See [migration](migration.md) and [opportunity contracts](opportunities.md).

CSV has stable columns and neutralises spreadsheet formula prefixes. JSON is the structured export; Notion payload is a minimal one-way view. ICS preserves date-vs-time semantics and folds UTF-8 lines. Backup uses SQLite's consistent backup API and checksummed files; restore checks paths, expansion limits, all manifest entries and database integrity. These checks do not prove scientific correctness.
